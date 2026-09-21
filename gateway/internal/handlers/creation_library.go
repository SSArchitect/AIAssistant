package handlers

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"image"
	"image/color"
	"image/jpeg"
	_ "image/png"
	"net/http"
	"strconv"
	"strings"

	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"golang.org/x/image/draw"
	_ "golang.org/x/image/webp"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

func libraryLimit(c *gin.Context, fallback int) int {
	n, _ := strconv.Atoi(c.Query("limit"))
	if n < 1 {
		return fallback
	}
	if n > 100 {
		return 100
	}
	return n
}
func libraryOffset(c *gin.Context) int {
	n, _ := strconv.Atoi(c.Query("offset"))
	if n < 0 {
		return 0
	}
	return n
}
func projectFolderID(user, project string) string {
	return uuid.NewSHA1(uuid.NameSpaceOID, []byte("creation-project-assets:"+user+":"+project)).String()
}
func (h *CreationHandler) projectAssetFolder(user, projectID string) (models.DriveItem, error) {
	var project models.CreationProject
	if err := h.db.Select("id", "name").Where("user_id = ? AND id = ?", user, projectID).First(&project).Error; err != nil {
		return models.DriveItem{}, err
	}
	root, err := h.assetFolder(user)
	if err != nil {
		return root, err
	}
	folder := models.DriveItem{ID: projectFolderID(user, projectID), UserID: user, ParentID: root.ID, Type: "folder", Name: cleanDriveName(project.Name)}
	err = h.db.Clauses(clause.OnConflict{DoNothing: true}).Create(&folder).Error
	return folder, err
}

// Only the library entry point reconciles Drive metadata. Project polling never
// scans all Drive files, and no discovery query selects file content.
func (h *CreationHandler) discoverDriveAssets(user string) error {
	root, err := h.assetFolder(user)
	if err != nil {
		return err
	}
	ids, err := h.assetDescendants(root.ID, user)
	if err != nil || len(ids) == 0 {
		return err
	}
	var items []models.DriveItem
	if err = h.db.Select("id", "parent_id").Where("user_id = ? AND id IN ? AND type = ? AND (mime_type LIKE ? OR mime_type LIKE ?)", user, ids, "file", "image/%", "video/%").Where("NOT EXISTS (SELECT 1 FROM creation_assets a WHERE a.user_id = drive_items.user_id AND a.drive_item_id = drive_items.id)").Find(&items).Error; err != nil {
		return err
	}
	if len(items) == 0 {
		return nil
	}
	var projects []models.CreationProject
	if err = h.db.Select("id").Where("user_id = ?", user).Find(&projects).Error; err != nil {
		return err
	}
	parents := map[string]string{}
	var folders []models.DriveItem
	if err = h.db.Select("id", "parent_id").Where("user_id = ? AND type = ?", user, "folder").Find(&folders).Error; err != nil {
		return err
	}
	for _, f := range folders {
		parents[f.ID] = f.ParentID
	}
	owners := map[string]string{}
	for _, p := range projects {
		owners[projectFolderID(user, p.ID)] = p.ID
	}
	for _, item := range items {
		projectID := ""
		seen := map[string]bool{}
		for parent := item.ParentID; parent != "" && !seen[parent]; parent = parents[parent] {
			seen[parent] = true
			if owners[parent] != "" {
				projectID = owners[parent]
				break
			}
		}
		a := models.CreationAsset{ID: uuid.NewString(), UserID: user, DriveItemID: item.ID, Source: "drive", ProjectID: projectID}
		if err = h.db.Clauses(clause.OnConflict{DoNothing: true}).Create(&a).Error; err != nil {
			return err
		}
	}
	return nil
}

// Backfill ownership from original runs, then from the first project that used an
// unassigned upload. Cross-project references continue to point to the same asset.
func (h *CreationHandler) organizeAssets(user string) error {
	h.libraryMu.Lock()
	defer h.libraryMu.Unlock()
	if h.libraryReady[user] {
		return nil
	}
	if err := h.discoverDriveAssets(user); err != nil {
		return err
	}
	var projects []models.CreationProject
	if err := h.db.Where("user_id = ?", user).Order("created_at, id").Find(&projects).Error; err != nil {
		return err
	}
	for _, p := range projects {
		folder, err := h.projectAssetFolder(user, p.ID)
		if err != nil {
			return err
		}
		doc, err := projectDocument(p)
		if err != nil {
			return err
		}
		err = h.db.Transaction(func(tx *gorm.DB) error {
			if err := tx.Model(&models.CreationAsset{}).Where("user_id = ? AND (project_id = '' OR project_id IS NULL) AND run_id IN (?)", user, tx.Model(&models.CreationRun{}).Select("id").Where("user_id = ? AND project_id = ?", user, p.ID)).Update("project_id", p.ID).Error; err != nil {
				return err
			}
			if len(doc.AssetIDs) > 0 {
				if err := tx.Model(&models.CreationAsset{}).Where("user_id = ? AND (project_id = '' OR project_id IS NULL) AND id IN ? AND (run_id = '' OR run_id IS NULL)", user, doc.AssetIDs).Update("project_id", p.ID).Error; err != nil {
					return err
				}
			}
			return tx.Model(&models.DriveItem{}).Where("user_id = ? AND parent_id != ? AND id IN (?)", user, folder.ID, tx.Model(&models.CreationAsset{}).Select("drive_item_id").Where("user_id = ? AND project_id = ?", user, p.ID)).Update("parent_id", folder.ID).Error
		})
		if err != nil {
			return err
		}
	}
	if h.libraryReady == nil {
		h.libraryReady = map[string]bool{}
	}
	h.libraryReady[user] = true
	return nil
}
func (h *CreationHandler) AssetFolders(c *gin.Context) {
	user := c.GetString("creation_user_id")
	if err := h.organizeAssets(user); err != nil {
		creationError(c, 500, "无法整理项目资产")
		return
	}
	if err := h.discoverDriveAssets(user); err != nil {
		creationError(c, 500, "无法读取网盘资产")
		return
	}
	root, err := h.assetFolder(user)
	if err != nil {
		creationError(c, 500, "无法读取资产文件夹")
		return
	}
	var projects []models.CreationProject
	if err = h.db.Select("id", "name", "updated_at").Where("user_id = ?", user).Order("updated_at DESC").Find(&projects).Error; err != nil {
		creationError(c, 500, "无法读取项目")
		return
	}
	var counts []struct {
		ProjectID string
		Count     int64
	}
	if err = h.db.Table("creation_assets").Select("creation_assets.project_id, COUNT(*) AS count").Joins("JOIN drive_items ON drive_items.id = creation_assets.drive_item_id AND drive_items.user_id = creation_assets.user_id").Where("creation_assets.user_id = ?", user).Group("creation_assets.project_id").Scan(&counts).Error; err != nil {
		creationError(c, 500, "无法读取资产数量")
		return
	}
	byProject := map[string]int64{}
	for _, row := range counts {
		byProject[row.ProjectID] = row.Count
	}
	folders := []gin.H{}
	for _, p := range projects {
		folders = append(folders, gin.H{"project_id": p.ID, "name": p.Name, "folder_id": projectFolderID(user, p.ID), "count": byProject[p.ID]})
	}
	folders = append(folders, gin.H{"project_id": "", "name": "未归属资产", "folder_id": root.ID, "count": byProject[""]})
	c.JSON(200, gin.H{"folders": folders, "folder_id": root.ID})
}
func (h *CreationHandler) projectHasWork(user, id string) bool {
	var n int64
	h.db.Model(&models.CreationRun{}).Where("user_id = ? AND project_id = ? AND status IN ?", user, id, []string{"queued", "running", "stopping"}).Count(&n)
	return n > 0
}
func (h *CreationHandler) RenameProject(c *gin.Context) {
	var req struct {
		Name     string `json:"name"`
		Revision int    `json:"revision"`
	}
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 16<<10)
	if c.ShouldBindJSON(&req) != nil || strings.TrimSpace(req.Name) == "" || len([]rune(strings.TrimSpace(req.Name))) > 100 {
		creationError(c, 400, "项目名称需为 1–100 个字符")
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	row, _, ok := h.loadProject(c)
	if !ok {
		return
	}
	if !checkProjectRevision(c, row, req.Revision) {
		return
	}
	name := strings.TrimSpace(req.Name)
	err := h.db.Transaction(func(tx *gorm.DB) error {
		result := tx.Model(&models.CreationProject{}).Where("user_id = ? AND id = ? AND revision = ?", row.UserID, row.ID, row.Revision).Updates(map[string]interface{}{"name": name, "name_locked": true, "revision": row.Revision + 1})
		if result.Error != nil {
			return result.Error
		}
		if result.RowsAffected != 1 {
			return errors.New("项目已更新")
		}
		return tx.Model(&models.DriveItem{}).Where("user_id = ? AND id = ?", row.UserID, projectFolderID(row.UserID, row.ID)).Update("name", cleanDriveName(name)).Error
	})
	if err != nil {
		creationError(c, 500, "重命名失败")
		return
	}
	h.db.Where("id = ?", row.ID).First(&row)
	c.JSON(200, gin.H{"project": row})
}
func (h *CreationHandler) DeleteProject(c *gin.Context) {
	h.mu.Lock()
	defer h.mu.Unlock()
	row, _, ok := h.loadProject(c)
	if !ok {
		return
	}
	revision, _ := strconv.Atoi(c.Query("revision"))
	if !checkProjectRevision(c, row, revision) {
		return
	}
	if h.projectHasWork(row.UserID, row.ID) {
		creationError(c, 409, "项目仍在生成，请先停止并等待当前生成完成")
		return
	}
	if err := h.organizeAssets(row.UserID); err != nil {
		creationError(c, 500, "无法整理项目资产")
		return
	}
	root, err := h.assetFolder(row.UserID)
	if err != nil {
		creationError(c, 500, "无法保留资产")
		return
	}
	err = h.db.Transaction(func(tx *gorm.DB) error {
		folderID := projectFolderID(row.UserID, row.ID)
		// Keep every file, including files manually placed in the project's Drive folder.
		if err := tx.Model(&models.DriveItem{}).Where("user_id = ? AND parent_id = ?", row.UserID, folderID).Update("parent_id", root.ID).Error; err != nil {
			return err
		}
		if err := tx.Model(&models.CreationAsset{}).Where("user_id = ? AND project_id = ?", row.UserID, row.ID).Update("project_id", "").Error; err != nil {
			return err
		}
		for _, model := range []interface{}{&models.CreationProjectVersion{}, &models.CreationRun{}} {
			if err := tx.Where("user_id = ? AND project_id = ?", row.UserID, row.ID).Delete(model).Error; err != nil {
				return err
			}
		}
		if err := tx.Where("user_id = ? AND id = ?", row.UserID, folderID).Delete(&models.DriveItem{}).Error; err != nil {
			return err
		}
		return tx.Where("user_id = ? AND id = ?", row.UserID, row.ID).Delete(&models.CreationProject{}).Error
	})
	if err != nil {
		creationError(c, 500, "删除项目失败")
		return
	}
	c.JSON(200, gin.H{"status": "deleted", "assets_preserved": true})
}
func documentUsesAsset(doc creativeDocument, ids map[string]bool) bool {
	for _, id := range doc.AssetIDs {
		if ids[id] {
			return true
		}
	}
	for _, n := range doc.Plan.Nodes {
		if ids[n.AssetID] || ids[n.EditSourceAssetID] {
			return true
		}
		for _, r := range n.References {
			if ids[r.AssetID] {
				return true
			}
		}
	}
	for _, s := range doc.States {
		if ids[s.SelectedAssetID] {
			return true
		}
	}
	return false
}
func (h *CreationHandler) DeleteAssets(c *gin.Context) {
	var req struct {
		IDs []string `json:"ids"`
	}
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 64<<10)
	if c.ShouldBindJSON(&req) != nil || len(req.IDs) == 0 || len(req.IDs) > 100 {
		creationError(c, 400, "每次请选择 1–100 个资产")
		return
	}
	ids := map[string]bool{}
	for _, id := range req.IDs {
		if id == "" || ids[id] {
			creationError(c, 400, "资产选择无效")
			return
		}
		ids[id] = true
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	user := c.GetString("creation_user_id")
	var assets []models.CreationAsset
	if err := h.db.Where("user_id = ? AND id IN ?", user, req.IDs).Find(&assets).Error; err != nil {
		creationError(c, 500, "无法读取资产")
		return
	}
	if len(assets) != len(ids) {
		creationError(c, 404, "部分资产不存在，未删除任何文件")
		return
	}
	var projects []models.CreationProject
	if err := h.db.Where("user_id = ?", user).Find(&projects).Error; err != nil {
		creationError(c, 500, "无法检查资产引用")
		return
	}
	var active int64
	if err := h.db.Model(&models.CreationRun{}).Where("user_id = ? AND status IN ?", user, []string{"queued", "running", "stopping"}).Count(&active).Error; err != nil {
		creationError(c, 500, "无法检查生成状态")
		return
	}
	if active > 0 {
		creationError(c, 409, "正在生成，请等待完成后再删除资产")
		return
	}
	docs := map[string]creativeDocument{}
	for _, p := range projects {
		if p.Planning || automaticActive(p.AutomaticStatus) {
			creationError(c, 409, "创作助手正在处理，请稍后删除资产")
			return
		}
		doc, err := projectDocument(p)
		if err != nil {
			creationError(c, 500, "无法检查项目引用")
			return
		}
		if documentUsesAsset(doc, ids) {
			creationError(c, 409, fmt.Sprintf("资产仍被项目「%s」引用，请先移除引用或删除项目；本次未删除任何文件", p.Name))
			return
		}
		docs[p.ID] = doc
	}
	var definitions []models.CreationDefinition
	if err := h.db.Where("user_id = ?", user).Find(&definitions).Error; err != nil {
		creationError(c, 500, "无法检查工作流引用")
		return
	}
	for _, d := range definitions {
		var graph creationGraph
		_ = json.Unmarshal([]byte(d.Definition), &graph)
		for _, n := range graph.Nodes {
			for _, id := range n.AssetIDs {
				if ids[id] {
					creationError(c, 409, "资产仍被工作流「"+d.Name+"」引用，请先移除引用")
					return
				}
			}
		}
	}
	err := h.db.Transaction(func(tx *gorm.DB) error {
		for _, p := range projects {
			doc := docs[p.ID]
			changed := false
			for id, state := range doc.States {
				kept := []string{}
				for _, a := range state.Candidates {
					if ids[a] {
						changed = true
					} else {
						kept = append(kept, a)
					}
				}
				state.Candidates = kept
				doc.States[id] = state
			}
			if changed {
				if err := tx.Model(&p).Updates(map[string]interface{}{"document": creationJSON(doc), "revision": p.Revision + 1}).Error; err != nil {
					return err
				}
			}
		}
		files := []string{}
		for _, a := range assets {
			files = append(files, a.DriveItemID)
		}
		if err := tx.Where("drive_item_id IN ?", files).Delete(&models.CreationThumbnail{}).Error; err != nil {
			return err
		}
		if err := tx.Where("user_id = ? AND id IN ?", user, files).Delete(&models.DriveItem{}).Error; err != nil {
			return err
		}
		return tx.Where("user_id = ? AND id IN ?", user, req.IDs).Delete(&models.CreationAsset{}).Error
	})
	if err != nil {
		creationError(c, 500, "删除资产失败")
		return
	}
	c.JSON(200, gin.H{"deleted": req.IDs})
}

func (h *CreationHandler) AssetThumbnail(c *gin.Context) {
	user, id := c.GetString("creation_user_id"), c.Param("id")
	// Authenticate before returning a cached preview or 304, and avoid reading the original on cache hits.
	var item models.DriveItem
	if h.db.Table("drive_items").Select("drive_items.id, drive_items.mime_type, drive_items.updated_at").Joins("JOIN creation_assets ON creation_assets.drive_item_id = drive_items.id AND creation_assets.user_id = drive_items.user_id").Where("creation_assets.user_id = ? AND creation_assets.id = ?", user, id).First(&item).Error != nil {
		creationError(c, 404, "资产不存在")
		return
	}
	if !strings.HasPrefix(item.MimeType, "image/") {
		creationError(c, 400, "此资产不是图片")
		return
	}
	etag := fmt.Sprintf(`"%s-%d-thumb1"`, item.ID, item.UpdatedAt.UnixNano())
	c.Header("Cache-Control", "private, no-cache")
	c.Header("ETag", etag)
	c.Header("X-Content-Type-Options", "nosniff")
	if c.GetHeader("If-None-Match") == etag {
		c.Status(304)
		return
	}
	h.thumbnailMu.Lock()
	defer h.thumbnailMu.Unlock() // bound peak decode memory on the small production host
	var cached models.CreationThumbnail
	err := h.db.Where("drive_item_id = ? AND source_updated_at = ?", item.ID, item.UpdatedAt).First(&cached).Error
	if err != nil {
		original, e := h.assetItem(user, id)
		if e != nil {
			creationError(c, 404, "资产不存在")
			return
		}
		data, e := base64.StdEncoding.DecodeString(original.Content)
		if e != nil {
			creationError(c, 422, "无法读取图片")
			return
		}
		config, _, e := image.DecodeConfig(bytes.NewReader(data))
		if e != nil || config.Width < 1 || config.Height < 1 || int64(config.Width)*int64(config.Height) > 20000000 {
			creationError(c, 422, "图片过大或格式异常，请打开原图查看")
			return
		}
		source, _, e := image.Decode(bytes.NewReader(data))
		if e != nil {
			creationError(c, 422, "无法生成缩略图，请打开原图查看")
			return
		}
		w, height := config.Width, config.Height
		const size = 384
		if w > size || height > size {
			if w >= height {
				height = max(1, height*size/w)
				w = size
			} else {
				w = max(1, w*size/height)
				height = size
			}
		}
		thumb := image.NewRGBA(image.Rect(0, 0, w, height))
		draw.Draw(thumb, thumb.Bounds(), &image.Uniform{C: color.White}, image.Point{}, draw.Src)
		draw.ApproxBiLinear.Scale(thumb, thumb.Bounds(), source, source.Bounds(), draw.Over, nil)
		var out bytes.Buffer
		if jpeg.Encode(&out, thumb, &jpeg.Options{Quality: 76}) != nil {
			creationError(c, 500, "无法生成缩略图")
			return
		}
		cached = models.CreationThumbnail{DriveItemID: item.ID, SourceUpdatedAt: original.UpdatedAt, Content: out.Bytes()}
		if err = h.db.Clauses(clause.OnConflict{UpdateAll: true}).Create(&cached).Error; err != nil {
			creationError(c, 500, "无法保存缩略图")
			return
		}
	}
	c.Data(200, "image/jpeg", cached.Content)
}
