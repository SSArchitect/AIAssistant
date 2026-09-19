package handlers

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

const creationMaxBytes = 64 << 20

type creationNode struct {
	ImagePurpose    string                         `json:"image_purpose,omitempty"`
	ImageReferences []bridge.ImageReferenceContext `json:"image_references,omitempty"`
	ID              string                         `json:"id"`
	Kind            string                         `json:"kind"`
	Name            string                         `json:"name"`
	Prompt          string                         `json:"prompt"`
	Count           int                            `json:"count"`
	AspectRatio     string                         `json:"aspect_ratio"`
	DurationSeconds int                            `json:"duration_seconds"`
	CharacterStyle  string                         `json:"character_style"`
	Inputs          []string                       `json:"inputs"`
	AssetIDs        []string                       `json:"asset_ids"`
	InputHashes     map[string]string              `json:"input_hashes,omitempty"`
	VideoMode       string                         `json:"video_mode,omitempty"`
	Storyboard      json.RawMessage                `json:"storyboard,omitempty"`
}
type creationGraph struct {
	Nodes []creationNode `json:"nodes"`
}
type creationProgress struct {
	ErrorCode      string   `json:"error_code,omitempty"`
	ProviderTaskID string   `json:"provider_task_id,omitempty"`
	Retryable      bool     `json:"retryable,omitempty"`
	NodeID         string   `json:"node_id"`
	Status         string   `json:"status"`
	AssetIDs       []string `json:"asset_ids"`
	Error          string   `json:"error,omitempty"`
}
type creationGenerator interface {
	CreateMedia(context.Context, bridge.CreationNodeRequest) (*bridge.CreationNodeResponse, error)
}
type CreationHandler struct {
	generator        creationGenerator
	db               *gorm.DB
	mu               sync.Mutex
	automaticCancels map[string]context.CancelFunc
	retryWait        func(context.Context, time.Duration) error
	libraryMu        sync.Mutex
	libraryReady     map[string]bool
	thumbnailMu      sync.Mutex
}

func NewCreationHandler(generator creationGenerator) *CreationHandler {
	if client, ok := generator.(*bridge.AgentClient); ok {
		generator = &configuredCreationAgent{AgentClient: client, syncer: NewConfigSyncer(client)}
	}
	return &CreationHandler{generator: generator, db: database.DB}
}

// Call once at process startup. Interrupted submissions are never automatically replayed.
func (h *CreationHandler) Recover() error {
	var automaticProjects []models.CreationProject
	if err := h.db.Where("automatic_status IN ?", []string{"running", "stopping"}).Find(&automaticProjects).Error; err != nil {
		return err
	}
	for _, row := range automaticProjects {
		h.finishAutomatic(row.ID, row.AutomaticRequestID, "interrupted", "服务已重启，一键生成已中断；已完成结果保留，请点击继续，不会自动重复提交。")
	}
	var planningProjects []models.CreationProject
	if err := h.db.Where("planning = ?", true).Find(&planningProjects).Error; err != nil {
		return err
	}
	for _, row := range planningProjects {
		doc, err := projectDocument(row)
		if err != nil {
			return err
		}
		row.Planning = false
		row.Error = "服务已重启，规划已中断；原有方案保留，请重试"
		finishPlanningActivity(&doc, "interrupted", row.Error)
		doc.Messages = append(doc.Messages, bridge.CreativeMessage{Role: "assistant", Content: row.Error, Planning: doc.Planning})
		doc.Planning = nil
		if err := h.updateProject(&row, doc, false); err != nil {
			return err
		}
	}
	var interrupted []models.CreationRun
	if err := h.db.Where("project_id != ? AND status IN ?", "", []string{"queued", "running", "stopping"}).Find(&interrupted).Error; err != nil {
		return err
	}
	if err := h.db.Model(&models.CreationRun{}).Where("status IN ?", []string{"queued", "running", "stopping"}).Updates(map[string]interface{}{
		"status": "interrupted", "error": "服务已重启；已归档的结果保留，可手动重新运行", "updated_at": time.Now()}).Error; err != nil {
		return err
	}
	for _, run := range interrupted {
		var progress []creationProgress
		if json.Unmarshal([]byte(run.Progress), &progress) == nil {
			h.finishProjectRun(run, progress)
		}
	}
	return nil
}
func (h *CreationHandler) Register(api *gin.RouterGroup) {
	group := api.Group("/creation")
	group.Use(func(c *gin.Context) {
		if user, ok := requireAccountSessionUserID(c); ok {
			c.Set("creation_user_id", user)
			c.Next()
		}
	})
	group.GET("/definitions", h.Definitions)
	group.POST("/definitions", h.SaveDefinition)
	group.PUT("/definitions/:id", h.SaveDefinition)
	group.DELETE("/definitions/:id", h.DeleteDefinition)
	group.GET("/assets", h.Assets)
	group.GET("/asset-folders", h.AssetFolders)
	group.POST("/assets/delete", h.DeleteAssets)
	group.GET("/assets/:id/thumbnail", h.AssetThumbnail)
	group.POST("/assets", h.UploadAsset)
	group.POST("/assets/import", h.ImportAsset)
	group.GET("/assets/:id/content", h.AssetContent)
	group.GET("/runs", h.Runs)
	group.POST("/runs", h.StartRun)
	group.POST("/runs/:id/cancel", h.CancelRun)
	h.registerProjects(group)
}
func creationJSON(value interface{}) string { data, _ := json.Marshal(value); return string(data) }
func creationError(c *gin.Context, status int, err interface{}) {
	c.JSON(status, gin.H{"error": fmt.Sprint(err)})
}
func validateCreationGraph(graph creationGraph, runnable bool) error {
	if len(graph.Nodes) < 1 || len(graph.Nodes) > maxCreativeNodes {
		return errors.New("工作流需要 1–64 个节点")
	}
	seen := map[string]creationNode{}
	for _, n := range graph.Nodes {
		if n.ID == "" || len(n.ID) > 80 {
			return errors.New("节点 ID 无效")
		}
		if _, ok := seen[n.ID]; ok {
			return errors.New("节点 ID 重复")
		}
		if n.Kind != "image" && n.Kind != "video" {
			return errors.New("节点类型必须是图片或视频")
		}
		if len([]rune(n.Prompt)) > 4000 || (runnable && strings.TrimSpace(n.Prompt) == "") {
			return errors.New("每个节点需要 1–4000 字提示词")
		}
		if n.Count < 1 || n.Count > 9 || (n.Kind == "video" && n.Count != 1) {
			return errors.New("图片数量为 1–9；视频数量为 1")
		}
		if n.AspectRatio != "1:1" && n.AspectRatio != "16:9" && n.AspectRatio != "9:16" {
			return errors.New("不支持的画幅")
		}
		if n.DurationSeconds < 1 || n.DurationSeconds > 15 {
			return errors.New("视频时长为 1–15 秒")
		}
		if n.CharacterStyle != "" && n.CharacterStyle != "anime" && n.CharacterStyle != "chibi" {
			return errors.New("无效的人物风格")
		}
		inputCount := len(n.AssetIDs)
		unique := map[string]bool{}
		for _, id := range n.AssetIDs {
			if id == "" || unique[id] {
				return errors.New("资产引用重复或为空")
			}
			unique[id] = true
		}
		for _, id := range n.Inputs {
			source, ok := seen[id]
			if !ok || source.Kind != "image" || unique[id] {
				return errors.New("只能引用前面图片节点的结果，且不能重复引用")
			}
			unique[id] = true
			inputCount += source.Count
		}
		if inputCount > 9 || (n.Kind == "image" && inputCount > 1) {
			return errors.New("生图节点最多输入 1 张图片；视频节点最多输入 9 张图片")
		}
		if n.ImagePurpose != "" && (n.Kind != "image" || (n.ImagePurpose != "key_visual" && n.ImagePurpose != "scene" && n.ImagePurpose != "shot_reference" && n.ImagePurpose != "output")) {
			return errors.New("invalid image purpose")
		}
		if len(n.ImageReferences) > 0 {
			if n.Kind != "image" || len(n.ImageReferences) != inputCount {
				return errors.New("图片参考职责与输入不匹配")
			}
			for _, ref := range n.ImageReferences {
				if (ref.Role != "identity" && ref.Role != "style" && ref.Role != "reference") || len([]rune(ref.Note)) > 500 {
					return errors.New("图片参考职责无效")
				}
			}
		}
		if n.CharacterStyle != "" && (n.Kind != "image" || (runnable && inputCount != 1)) {
			return errors.New("人物风格模板需要一张输入图片")
		}
		seen[n.ID] = n
	}
	return nil
}
func (h *CreationHandler) Definitions(c *gin.Context) {
	var rows []models.CreationDefinition
	if err := h.db.Where("user_id = ?", c.GetString("creation_user_id")).Order("updated_at DESC").Find(&rows).Error; err != nil {
		creationError(c, 500, "无法读取工作流")
		return
	}
	c.JSON(200, gin.H{"definitions": rows})
}
func (h *CreationHandler) SaveDefinition(c *gin.Context) {
	var req struct {
		Name  string        `json:"name"`
		Kind  string        `json:"kind"`
		Graph creationGraph `json:"graph"`
	}
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 256<<10)
	if err := c.ShouldBindJSON(&req); err != nil {
		creationError(c, 400, "无效的工作流")
		return
	}
	req.Name = strings.TrimSpace(req.Name)
	if req.Name == "" || len([]rune(req.Name)) > 100 {
		creationError(c, 400, "名称需要 1–100 字")
		return
	}
	if req.Kind != "workflow" && req.Kind != "workflow_template" && req.Kind != "image_template" && req.Kind != "video_template" {
		creationError(c, 400, "无效的模板类型")
		return
	}
	if req.Kind != "workflow" {
		for i := range req.Graph.Nodes {
			req.Graph.Nodes[i].AssetIDs = []string{}
		}
	}
	if strings.HasSuffix(req.Kind, "_template") && req.Kind != "workflow_template" {
		if len(req.Graph.Nodes) != 1 || req.Graph.Nodes[0].Kind+"_template" != req.Kind {
			creationError(c, 400, "节点模板类型不匹配")
			return
		}
		req.Graph.Nodes[0].Inputs = []string{}
	}
	if err := validateCreationGraph(req.Graph, false); err != nil {
		creationError(c, 400, err)
		return
	}
	row := models.CreationDefinition{UserID: c.GetString("creation_user_id")}
	if id := c.Param("id"); id != "" {
		if h.db.Where("id = ? AND user_id = ?", id, row.UserID).First(&row).Error != nil {
			creationError(c, 404, "工作流不存在")
			return
		}
	}
	if row.ID == "" {
		row.ID = uuid.NewString()
	}
	row.Name = req.Name
	row.Kind = req.Kind
	row.Definition = creationJSON(req.Graph)
	if err := h.db.Save(&row).Error; err != nil {
		creationError(c, 500, "保存失败")
		return
	}
	c.JSON(200, gin.H{"definition": row})
}
func (h *CreationHandler) DeleteDefinition(c *gin.Context) {
	result := h.db.Where("id = ? AND user_id = ?", c.Param("id"), c.GetString("creation_user_id")).Delete(&models.CreationDefinition{})
	if result.Error != nil {
		creationError(c, 500, "删除失败")
		return
	}
	if result.RowsAffected == 0 {
		creationError(c, 404, "工作流不存在")
		return
	}
	c.JSON(200, gin.H{"status": "deleted"})
}
func (h *CreationHandler) assetFolder(user string) (models.DriveItem, error) {
	root, err := ensureDriveRoot(user)
	if err != nil {
		return root, err
	}
	var folder models.DriveItem
	err = h.db.Where("user_id = ? AND parent_id = ? AND name = ? AND type = ?", user, root.ID, "资产", "folder").Order("created_at").First(&folder).Error
	if err == nil {
		return folder, nil
	}
	if !errors.Is(err, gorm.ErrRecordNotFound) {
		return folder, err
	}
	folder = models.DriveItem{ID: uuid.NewSHA1(uuid.NameSpaceOID, []byte("creation-assets:"+user)).String(), UserID: user, ParentID: root.ID, Name: "资产", Type: "folder"}
	err = h.db.Where("id = ?", folder.ID).FirstOrCreate(&folder).Error
	return folder, err
}

// Traverse metadata only; polling must never read all binary asset bodies.
func (h *CreationHandler) assetDescendants(root, user string) ([]string, error) {
	var rows []models.DriveItem
	if err := h.db.Select("id", "parent_id", "type").Where("user_id = ?", user).Find(&rows).Error; err != nil {
		return nil, err
	}
	children := map[string][]models.DriveItem{}
	for _, row := range rows {
		children[row.ParentID] = append(children[row.ParentID], row)
	}
	ids := []string{}
	queue := []string{root}
	visited := map[string]bool{root: true}
	for len(queue) > 0 {
		id := queue[0]
		queue = queue[1:]
		for _, row := range children[id] {
			if visited[row.ID] {
				continue
			}
			visited[row.ID] = true
			ids = append(ids, row.ID)
			if row.Type == "folder" {
				queue = append(queue, row.ID)
			}
		}
	}
	return ids, nil
}

type creationAssetView struct {
	models.CreationAsset
	Name     string `json:"name"`
	MimeType string `json:"mime_type"`
	Size     int64  `json:"size"`
}

func (h *CreationHandler) Assets(c *gin.Context) {
	user := c.GetString("creation_user_id")
	if err := h.organizeAssets(user); err != nil {
		creationError(c, 500, "无法整理资产文件夹")
		return
	}
	query := h.db.Table("creation_assets").Select("creation_assets.*, drive_items.name, drive_items.mime_type, drive_items.size").Joins("JOIN drive_items ON drive_items.id = creation_assets.drive_item_id AND drive_items.user_id = creation_assets.user_id").Where("creation_assets.user_id = ?", user)
	folder, err := h.assetFolder(user)
	if err != nil {
		creationError(c, 500, "无法打开资产文件夹")
		return
	}
	if _, present := c.Request.URL.Query()["project_id"]; present {
		projectID := c.Query("project_id")
		if projectID != "" {
			folder, err = h.projectAssetFolder(user, projectID)
			if err != nil {
				creationError(c, 404, "项目不存在")
				return
			}
		}
		query = query.Where("creation_assets.project_id = ?", projectID)
	}
	if raw := c.Query("ids"); raw != "" {
		ids := strings.Split(raw, ",")
		if len(ids) > 500 {
			creationError(c, 400, "引用过多")
			return
		}
		query = query.Where("creation_assets.id IN ?", ids)
	}
	if q := c.Query("q"); q != "" {
		query = query.Where("instr(lower(drive_items.name), lower(?)) > 0", q)
	}
	if kind := c.Query("media"); kind == "image/" || kind == "video/" {
		query = query.Where("drive_items.mime_type LIKE ?", kind+"%")
	}
	if source := c.Query("source"); source != "" {
		query = query.Where("creation_assets.source = ?", source)
	}
	var total int64
	if err = query.Count(&total).Error; err != nil {
		creationError(c, 500, "无法读取资产")
		return
	}
	if c.Query("limit") != "" {
		query = query.Limit(libraryLimit(c, 48)).Offset(libraryOffset(c))
	}
	var assets []creationAssetView
	err = query.Order("creation_assets.created_at DESC, creation_assets.id DESC").Scan(&assets).Error
	if err != nil {
		creationError(c, 500, "无法读取资产")
		return
	}
	c.JSON(200, gin.H{"assets": assets, "folder_id": folder.ID, "total": total})
}

func creationMediaType(content []byte) string {
	kind := http.DetectContentType(content)
	switch kind {
	case "image/png", "image/jpeg", "image/webp", "video/mp4", "video/webm":
		return kind
	}
	return ""
}
func (h *CreationHandler) saveAsset(user, name, content, mime, source, run, node, task string, projectIDs ...string) (models.CreationAsset, error) {
	asset := models.CreationAsset{}
	if len(content) > ((creationMaxBytes+2)/3)*4 {
		return asset, errors.New("资产超过 64 MiB")
	}
	decoded, err := base64.StdEncoding.DecodeString(content)
	if err != nil || len(decoded) == 0 || len(decoded) > creationMaxBytes {
		return asset, errors.New("无效的媒体文件")
	}
	if creationMediaType(decoded) != mime || mime == "" {
		return asset, errors.New("文件内容与媒体类型不匹配，请使用 PNG、JPEG、WebP、MP4 或 WebM")
	}
	projectID := ""
	if len(projectIDs) > 0 {
		projectID = projectIDs[0]
	}
	if run != "" {
		var row models.CreationRun
		if h.db.Select("project_id").Where("id = ? AND user_id = ?", run, user).First(&row).Error == nil {
			projectID = row.ProjectID
		}
	}
	folder, err := h.assetFolder(user)
	if projectID != "" {
		folder, err = h.projectAssetFolder(user, projectID)
	}
	if err != nil {
		return asset, err
	}
	item := models.DriveItem{ID: uuid.NewString(), UserID: user, ParentID: folder.ID, Type: "file", Name: cleanDriveName(name), MimeType: mime, Encoding: "base64", Content: content, Size: int64(len(decoded))}
	if item.Name == "" {
		item.Name = "创作资产"
	}
	asset = models.CreationAsset{ID: uuid.NewString(), UserID: user, DriveItemID: item.ID, Source: source, ProjectID: projectID, RunID: run, NodeID: node, ProviderTaskID: task}
	err = h.db.Transaction(func(tx *gorm.DB) error {
		if err := tx.Create(&item).Error; err != nil {
			return err
		}
		return tx.Create(&asset).Error
	})
	return asset, err
}
func (h *CreationHandler) UploadAsset(c *gin.Context) {
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 90<<20)
	var req struct {
		Name      string `json:"name"`
		Content   string `json:"content"`
		MimeType  string `json:"mime_type"`
		ProjectID string `json:"project_id"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		creationError(c, 400, "文件上传失败，最大 64 MiB")
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	asset, err := h.saveAsset(c.GetString("creation_user_id"), req.Name, req.Content, req.MimeType, "upload", "", "", "", req.ProjectID)
	if err != nil {
		creationError(c, 400, err)
		return
	}
	c.JSON(201, gin.H{"asset": asset})
}
func (h *CreationHandler) ImportAsset(c *gin.Context) {
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 16<<10)
	var req struct {
		ID        string `json:"drive_item_id"`
		ProjectID string `json:"project_id"`
	}
	if c.ShouldBindJSON(&req) != nil {
		creationError(c, 400, "请选择网盘文件")
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	user := c.GetString("creation_user_id")
	var item models.DriveItem
	if h.db.Where("id = ? AND user_id = ? AND type = ?", req.ID, user, "file").First(&item).Error != nil {
		creationError(c, 404, "文件不存在")
		return
	}
	if item.Encoding != "base64" || (!strings.HasPrefix(item.MimeType, "image/") && !strings.HasPrefix(item.MimeType, "video/")) {
		creationError(c, 400, "请选择图片或视频文件")
		return
	}
	var existing models.CreationAsset
	if h.db.Where("user_id = ? AND drive_item_id = ?", user, item.ID).First(&existing).Error == nil && existing.ProjectID == req.ProjectID {
		c.JSON(200, gin.H{"asset": existing})
		return
	}
	folder, err := h.assetFolder(user)
	if req.ProjectID != "" {
		folder, err = h.projectAssetFolder(user, req.ProjectID)
	}
	if err != nil {
		creationError(c, 404, "项目资产文件夹不存在")
		return
	}
	asset := models.CreationAsset{ID: uuid.NewString(), UserID: user, DriveItemID: item.ID, Source: "drive", ProjectID: req.ProjectID}
	if existing.ID != "" {
		asset = existing
		asset.ProjectID = req.ProjectID
	}
	err = h.db.Transaction(func(tx *gorm.DB) error {
		if err := tx.Model(&item).Update("parent_id", folder.ID).Error; err != nil {
			return err
		}
		if err := tx.Clauses(clause.OnConflict{Columns: []clause.Column{{Name: "user_id"}, {Name: "drive_item_id"}}, DoUpdates: clause.AssignmentColumns([]string{"project_id"})}).Create(&asset).Error; err != nil {
			return err
		}
		asset = models.CreationAsset{}
		return tx.Where("user_id = ? AND drive_item_id = ?", user, item.ID).First(&asset).Error
	})
	if err != nil {
		creationError(c, 500, "归入资产失败")
		return
	}
	c.JSON(200, gin.H{"asset": asset})
}
func (h *CreationHandler) assetItem(user, id string) (models.DriveItem, error) {
	var item models.DriveItem
	err := h.db.Table("drive_items").Select("drive_items.*").Joins("JOIN creation_assets ON creation_assets.drive_item_id = drive_items.id AND creation_assets.user_id = drive_items.user_id").Where("creation_assets.user_id = ? AND creation_assets.id = ?", user, id).First(&item).Error
	return item, err
}
func (h *CreationHandler) AssetContent(c *gin.Context) {
	item, err := h.assetItem(c.GetString("creation_user_id"), c.Param("id"))
	if err != nil {
		creationError(c, 404, "资产不存在或已从网盘删除")
		return
	}
	data, err := base64.StdEncoding.DecodeString(item.Content)
	if err != nil || creationMediaType(data) == "" {
		creationError(c, 400, "不支持预览此文件")
		return
	}
	c.Header("X-Content-Type-Options", "nosniff")
	c.Header("Cache-Control", "private, no-store")
	c.Header("Content-Type", creationMediaType(data))
	http.ServeContent(c.Writer, c.Request, item.Name, item.UpdatedAt, bytes.NewReader(data))
}
func (h *CreationHandler) Runs(c *gin.Context) {
	var rows []models.CreationRun
	query := h.db.Where("user_id = ?", c.GetString("creation_user_id"))
	if id := c.Query("project_id"); id != "" {
		query = query.Where("project_id = ?", id)
	}
	if id := c.Query("workflow_id"); id != "" {
		query = query.Where("workflow_id = ?", id)
	}
	if err := query.Order("created_at DESC").Limit(30).Find(&rows).Error; err != nil {
		creationError(c, 500, "无法读取运行记录")
		return
	}
	c.JSON(200, gin.H{"runs": rows})
}
func (h *CreationHandler) StartRun(c *gin.Context) {
	var req struct {
		WorkflowID string `json:"workflow_id"`
	}
	if c.ShouldBindJSON(&req) != nil {
		creationError(c, 400, "请选择工作流")
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	user := c.GetString("creation_user_id")
	var row models.CreationDefinition
	if h.db.Where("id = ? AND user_id = ? AND kind = ?", req.WorkflowID, user, "workflow").First(&row).Error != nil {
		creationError(c, 404, "工作流不存在")
		return
	}
	var graph creationGraph
	if json.Unmarshal([]byte(row.Definition), &graph) != nil {
		creationError(c, 400, "无效的工作流")
		return
	}
	if err := validateCreationGraph(graph, true); err != nil {
		creationError(c, 400, err)
		return
	}
	for _, node := range graph.Nodes {
		for _, id := range node.AssetIDs {
			if _, err := h.imageInput(user, id); err != nil {
				creationError(c, 400, err)
				return
			}
		}
	}
	var active int64
	if err := h.db.Model(&models.CreationRun{}).Where("user_id = ? AND status IN ?", user, []string{"queued", "running", "stopping"}).Count(&active).Error; err != nil {
		creationError(c, 500, "无法检查运行状态")
		return
	}
	if active > 0 || h.automaticBusy(user, "") {
		creationError(c, 409, "已有工作流正在运行，请完成或停止后再试")
		return
	}
	progress := make([]creationProgress, len(graph.Nodes))
	for i, n := range graph.Nodes {
		progress[i] = creationProgress{NodeID: n.ID, Status: "pending", AssetIDs: []string{}}
	}
	run := models.CreationRun{ID: uuid.NewString(), UserID: user, WorkflowID: row.ID, Name: row.Name, Definition: row.Definition, Status: "queued", Progress: creationJSON(progress)}
	if err := h.db.Create(&run).Error; err != nil {
		creationError(c, 500, "启动失败")
		return
	}
	go h.execute(run, graph, progress)
	c.JSON(http.StatusAccepted, gin.H{"run": run})
}
func (h *CreationHandler) CancelRun(c *gin.Context) {
	// Finish any provider submission already in flight and archive its result. Never launch the next one.
	result := h.db.Model(&models.CreationRun{}).Where("id = ? AND user_id = ? AND status IN ?", c.Param("id"), c.GetString("creation_user_id"), []string{"queued", "running"}).Updates(map[string]interface{}{"status": gorm.Expr("CASE WHEN status = 'queued' THEN 'cancelled' ELSE 'stopping' END"), "updated_at": time.Now()})
	if result.Error != nil {
		creationError(c, 500, "停止失败")
		return
	}
	if result.RowsAffected == 0 {
		creationError(c, 409, "任务不存在或已结束")
		return
	}
	c.JSON(200, gin.H{"status": "stopping"})
}
func (h *CreationHandler) imageInput(user, id string) (string, error) {
	item, err := h.assetItem(user, id)
	if err != nil {
		return "", errors.New("输入资产不存在或已被删除")
	}
	if item.Encoding != "base64" || item.Size > 16<<20 || (item.MimeType != "image/png" && item.MimeType != "image/jpeg" && item.MimeType != "image/webp") {
		return "", errors.New("节点输入需为不超过 16 MiB 的 PNG、JPEG 或 WebP 图片")
	}
	return "data:" + item.MimeType + ";base64," + item.Content, nil
}
func (h *CreationHandler) runStopped(id string) bool {
	var row models.CreationRun
	return h.db.Select("status").Where("id = ?", id).First(&row).Error != nil || row.Status == "stopping" || row.Status == "cancelled"
}
func (h *CreationHandler) checkpoint(run models.CreationRun, progress []creationProgress) error {
	return h.db.Model(&models.CreationRun{}).Where("id = ?", run.ID).Updates(map[string]interface{}{"progress": creationJSON(progress), "updated_at": time.Now()}).Error
}
func (h *CreationHandler) execute(run models.CreationRun, graph creationGraph, progress []creationProgress) {
	// Only the worker that claims the submission may execute or finalize it.
	claim := h.db.Model(&models.CreationRun{}).Where("id = ? AND status = ?", run.ID, "queued").Update("status", "running")
	if claim.Error != nil || claim.RowsAffected != 1 {
		return
	}
	status := "completed"
	errorText := ""
	defer func() {
		if recover() != nil {
			status = "failed"
			errorText = "工作流执行异常，已生成的资产保留"
		}
		if status != "completed" {
			for i := range progress {
				if progress[i].Status == "pending" {
					progress[i].Status = "skipped"
				}
				if progress[i].Status == "running" {
					progress[i].Status = status
					progress[i].Error = errorText
				}
			}
		}
		h.db.Model(&models.CreationRun{}).Where("id = ?", run.ID).Updates(map[string]interface{}{"status": status, "error": errorText, "progress": creationJSON(progress), "updated_at": time.Now()})
		h.finishProjectRun(run, progress)
	}()
	outputs := map[string][]string{}
	for i, node := range graph.Nodes {
		if h.runStopped(run.ID) {
			status = "cancelled"
			return
		}
		progress[i].Status = "running"
		if err := h.checkpoint(run, progress); err != nil {
			status = "failed"
			errorText = "无法保存节点状态"
			return
		}
		inputs := []string{}
		ids := append([]string{}, node.AssetIDs...)
		for _, id := range node.Inputs {
			ids = append(ids, outputs[id]...)
		}
		for _, id := range ids {
			input, err := h.imageInput(run.UserID, id)
			if err != nil {
				status = "failed"
				errorText = err.Error()
				return
			}
			if expected := node.InputHashes[id]; expected != "" && creativeHash(input) != expected {
				status = "failed"
				errorText = "参考文件在提交后发生变化，请重新审阅后生成"
				return
			}
			inputs = append(inputs, input)
		}
		outputs[node.ID] = append([]string{}, progress[i].AssetIDs...)
		for j := len(progress[i].AssetIDs); j < node.Count; j++ {
			if h.runStopped(run.ID) {
				status = "cancelled"
				return
			}
			ctx, cancel := context.WithTimeout(context.Background(), 6*time.Hour+2*time.Minute)
			media, err := h.generator.CreateMedia(ctx, bridge.CreationNodeRequest{ResumeTaskID: progress[i].ProviderTaskID, ImagePurpose: node.ImagePurpose, Kind: node.Kind, Prompt: node.Prompt, AspectRatio: node.AspectRatio, DurationSeconds: node.DurationSeconds, CharacterStyle: node.CharacterStyle, InputImages: inputs, ImageReferences: node.ImageReferences, IdempotencyKey: fmt.Sprintf("creation-%s-%d-%d", run.ID, i, j), VideoMode: node.VideoMode, Storyboard: node.Storyboard})
			cancel()
			if err != nil {
				status = "failed"
				var detail *bridge.CreationMediaError
				if errors.As(err, &detail) {
					progress[i].ErrorCode, progress[i].Retryable = detail.Code, detail.Retryable
					if detail.ProviderTaskID != "" {
						progress[i].ProviderTaskID = detail.ProviderTaskID
					}
				}
				errorText = fmt.Sprintf("「%s」%s", node.Name, creationFailureMessage(err, "生成失败，已完成的资产保留，请检查生成服务后重试"))
				return
			}
			if media == nil || (node.Kind == "image" && !strings.HasPrefix(media.MimeType, "image/")) || (node.Kind == "video" && !strings.HasPrefix(media.MimeType, "video/")) {
				status = "failed"
				errorText = "生成服务返回了错误的媒体类型"
				return
			}
			progress[i].ProviderTaskID = media.ProviderTaskID
			ext := map[string]string{"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "video/mp4": ".mp4", "video/webm": ".webm"}[media.MimeType]
			asset, err := h.saveAsset(run.UserID, fmt.Sprintf("%s-%s-%d%s", run.Name, node.Name, j+1, ext), media.Content, media.MimeType, "generated", run.ID, node.ID, media.ProviderTaskID)
			if err != nil {
				status = "failed"
				errorText = "资产归档失败：" + err.Error()
				progress[i].Retryable, progress[i].ErrorCode = true, "media_storage_failed"
				return
			}
			progress[i].ProviderTaskID, progress[i].ErrorCode, progress[i].Error, progress[i].Retryable = "", "", "", false
			progress[i].AssetIDs = append(progress[i].AssetIDs, asset.ID)
			outputs[node.ID] = append(outputs[node.ID], asset.ID)
			if err := h.checkpoint(run, progress); err != nil {
				status = "failed"
				errorText = "无法保存进度，结果已保存在资产中"
				return
			}
		}
		progress[i].Status = "completed"
		if err := h.checkpoint(run, progress); err != nil {
			status = "failed"
			errorText = "无法保存进度"
			return
		}
	}
	if h.runStopped(run.ID) {
		status = "cancelled"
	}
}
