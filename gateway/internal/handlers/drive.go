package handlers

import (
	"crypto/rand"
	"encoding/base64"
	"errors"
	"fmt"
	"html"
	"net/http"
	"sort"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"gorm.io/gorm"
)

const (
	driveItemTypeFolder = "folder"
	driveItemTypeFile   = "file"
	driveLegacyRootID   = ""
	driveContextLimit   = 10
	driveMaxContent     = knowledgeMaxContentRunes
	driveEncodingBase64 = "base64"
	driveMaxBase64Bytes = 3 * 1024 * 1024
)

type DriveHandler struct{}

func NewDriveHandler() *DriveHandler {
	return &DriveHandler{}
}

type driveFolderRequest struct {
	UserID   string `json:"user_id,omitempty"`
	ParentID string `json:"parent_id,omitempty"`
	Name     string `json:"name"`
}

type driveFileRequest struct {
	UserID   string   `json:"user_id,omitempty"`
	ParentID string   `json:"parent_id,omitempty"`
	Name     string   `json:"name"`
	MimeType string   `json:"mime_type,omitempty"`
	Encoding string   `json:"encoding,omitempty"`
	Content  string   `json:"content"`
	Summary  string   `json:"summary,omitempty"`
	Tags     []string `json:"tags,omitempty"`
}

type driveUpdateRequest struct {
	UserID   string  `json:"user_id,omitempty"`
	ParentID *string `json:"parent_id,omitempty"`
	Name     string  `json:"name,omitempty"`
}

type driveShareRequest struct {
	UserID  string `json:"user_id,omitempty"`
	Enabled bool   `json:"enabled"`
}

type driveContextRequest struct {
	UserID  string   `json:"user_id,omitempty"`
	Query   string   `json:"query,omitempty"`
	ItemIDs []string `json:"item_ids,omitempty"`
}

type driveItemResponse struct {
	ID           string              `json:"id"`
	UserID       string              `json:"user_id"`
	ParentID     string              `json:"parent_id,omitempty"`
	Type         string              `json:"type"`
	Name         string              `json:"name"`
	MimeType     string              `json:"mime_type,omitempty"`
	Encoding     string              `json:"encoding,omitempty"`
	Size         int64               `json:"size"`
	Summary      string              `json:"summary,omitempty"`
	Tags         []string            `json:"tags,omitempty"`
	Content      string              `json:"content,omitempty"`
	ShareEnabled bool                `json:"share_enabled"`
	ShareToken   string              `json:"share_token,omitempty"`
	Children     []driveItemResponse `json:"children,omitempty"`
	CreatedAt    time.Time           `json:"created_at"`
	UpdatedAt    time.Time           `json:"updated_at"`
}

type driveSearchResult struct {
	Item    driveItemResponse `json:"item"`
	Score   int               `json:"score"`
	Snippet string            `json:"snippet"`
}

func (h *DriveHandler) Tree(c *gin.Context) {
	userID := requestUserID(c)
	items, err := loadDriveItems(userID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load drive"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"items": buildDriveTree(items), "flat_items": driveItemResponses(items, false)})
}

func (h *DriveHandler) List(c *gin.Context) {
	userID := requestUserID(c)
	root, err := ensureDriveRoot(userID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to initialize drive"})
		return
	}
	parentID := strings.TrimSpace(c.Query("parent_id"))
	if parentID == "" {
		parentID = root.ID
	}
	if parentID != "" {
		if _, ok := h.loadFolder(c, userID, parentID); !ok {
			return
		}
	}
	var items []models.DriveItem
	if err := database.DB.Where("user_id = ? AND parent_id = ?", userID, parentID).
		Order(driveItemOrder).
		Find(&items).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load drive items"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"items": driveItemResponses(items, false)})
}

func (h *DriveHandler) CreateFolder(c *gin.Context) {
	var req driveFolderRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}
	userID := requestUserIDWithBody(c, req.UserID)
	root, err := ensureDriveRoot(userID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to initialize drive"})
		return
	}
	parentID := strings.TrimSpace(req.ParentID)
	if parentID == "" {
		parentID = root.ID
	}
	if parentID != "" {
		if _, ok := h.loadFolder(c, userID, parentID); !ok {
			return
		}
	}
	name := cleanDriveName(req.Name)
	if name == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "folder name is required"})
		return
	}
	now := time.Now()
	item := models.DriveItem{
		ID:        uuid.New().String(),
		UserID:    userID,
		ParentID:  parentID,
		Type:      driveItemTypeFolder,
		Name:      name,
		CreatedAt: now,
		UpdatedAt: now,
	}
	if err := database.DB.Create(&item).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to create folder"})
		return
	}
	c.JSON(http.StatusCreated, gin.H{"item": driveItemFromModel(item, false)})
}

func (h *DriveHandler) CreateFile(c *gin.Context) {
	var req driveFileRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}
	userID := requestUserIDWithBody(c, req.UserID)
	root, err := ensureDriveRoot(userID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to initialize drive"})
		return
	}
	parentID := strings.TrimSpace(req.ParentID)
	if parentID == "" {
		parentID = root.ID
	}
	if parentID != "" {
		if _, ok := h.loadFolder(c, userID, parentID); !ok {
			return
		}
	}
	encoding := cleanDriveEncoding(req.Encoding)
	content := strings.TrimSpace(req.Content)
	size := int64(0)
	if encoding == driveEncodingBase64 {
		if content == "" {
			c.JSON(http.StatusBadRequest, gin.H{"error": "file content is required"})
			return
		}
		if len(content) > driveMaxBase64Bytes {
			c.JSON(http.StatusBadRequest, gin.H{"error": "file is too large"})
			return
		}
		decoded, err := base64.StdEncoding.DecodeString(content)
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "invalid base64 file content"})
			return
		}
		size = int64(len(decoded))
	} else {
		content = trimKnowledgeContent(req.Content)
		size = int64(len([]byte(content)))
	}
	if content == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "file content is required"})
		return
	}
	name := cleanDriveName(req.Name)
	if name == "" {
		name = titleFromKnowledgeContent(content, "Untitled.txt")
	}
	summary := strings.TrimSpace(req.Summary)
	if summary == "" {
		if encoding == driveEncodingBase64 {
			summary = summarizeDriveBinaryFile(name, req.MimeType, size)
		} else {
			summary = summarizeKnowledgeContent(content)
		}
	}
	tags := normalizeKnowledgeTags(req.Tags)
	now := time.Now()
	item := models.DriveItem{
		ID:        uuid.New().String(),
		UserID:    userID,
		ParentID:  parentID,
		Type:      driveItemTypeFile,
		Name:      name,
		MimeType:  cleanDriveMimeType(req.MimeType),
		Encoding:  encoding,
		Size:      size,
		Summary:   summary,
		TagsJSON:  knowledgeJSON(tags),
		Content:   content,
		CreatedAt: now,
		UpdatedAt: now,
	}
	if err := database.DB.Create(&item).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to create file"})
		return
	}
	c.JSON(http.StatusCreated, gin.H{"item": driveItemFromModel(item, true)})
}

func (h *DriveHandler) Get(c *gin.Context) {
	userID := requestUserID(c)
	item, ok := h.loadItem(c, userID)
	if !ok {
		return
	}
	c.JSON(http.StatusOK, gin.H{"item": driveItemFromModel(item, true), "breadcrumbs": driveBreadcrumbs(item, userID)})
}

func (h *DriveHandler) Update(c *gin.Context) {
	var req driveUpdateRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}
	userID := requestUserIDWithBody(c, req.UserID)
	item, ok := h.loadItem(c, userID)
	if !ok {
		return
	}
	if name := cleanDriveName(req.Name); name != "" {
		item.Name = name
	}
	if req.ParentID != nil {
		if isDriveRootItem(item, userID) {
			c.JSON(http.StatusBadRequest, gin.H{"error": "root folder cannot be moved"})
			return
		}
		parentID := strings.TrimSpace(*req.ParentID)
		if parentID != "" {
			parent, ok := h.loadFolder(c, userID, parentID)
			if !ok {
				return
			}
			if item.Type == driveItemTypeFolder && driveFolderContains(item.ID, parent.ID, userID) {
				c.JSON(http.StatusBadRequest, gin.H{"error": "cannot move a folder into itself"})
				return
			}
		}
		item.ParentID = parentID
	}
	item.UpdatedAt = time.Now()
	if err := database.DB.Save(&item).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to update drive item"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"item": driveItemFromModel(item, true)})
}

func (h *DriveHandler) Share(c *gin.Context) {
	var req driveShareRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}
	userID := requestUserIDWithBody(c, req.UserID)
	item, ok := h.loadItem(c, userID)
	if !ok {
		return
	}
	if item.Type != driveItemTypeFile {
		c.JSON(http.StatusBadRequest, gin.H{"error": "folders cannot be shared"})
		return
	}
	if req.Enabled && strings.TrimSpace(item.ShareToken) == "" {
		token, err := generateUniqueDriveShareToken()
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to create share link"})
			return
		}
		item.ShareToken = token
	}
	item.ShareEnabled = req.Enabled
	item.UpdatedAt = time.Now()
	if err := database.DB.Save(&item).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to update share permission"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"item": driveItemFromModel(item, true)})
}

func (h *DriveHandler) Delete(c *gin.Context) {
	userID := requestUserID(c)
	item, ok := h.loadItem(c, userID)
	if !ok {
		return
	}
	if isDriveRootItem(item, userID) {
		c.JSON(http.StatusBadRequest, gin.H{"error": "root folder cannot be deleted"})
		return
	}
	ids, err := driveDescendantIDs(item.ID, userID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to inspect drive item"})
		return
	}
	ids = append(ids, item.ID)
	if err := database.DB.Delete(&models.DriveItem{}, "user_id = ? AND id IN ?", userID, ids).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to delete drive item"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"status": "deleted"})
}

func (h *DriveHandler) Download(c *gin.Context) {
	userID := requestUserID(c)
	item, ok := h.loadItem(c, userID)
	if !ok {
		return
	}
	if item.Type != driveItemTypeFile {
		c.JSON(http.StatusBadRequest, gin.H{"error": "folders cannot be downloaded"})
		return
	}
	mimeType := item.MimeType
	if mimeType == "" {
		mimeType = "text/plain; charset=utf-8"
	}
	c.Header("Content-Disposition", fmt.Sprintf("attachment; filename=%q", item.Name))
	if item.Encoding == driveEncodingBase64 {
		decoded, err := base64.StdEncoding.DecodeString(strings.TrimSpace(item.Content))
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to decode file content"})
			return
		}
		c.Data(http.StatusOK, mimeType, decoded)
		return
	}
	c.Data(http.StatusOK, mimeType, []byte(item.Content))
}

func (h *DriveHandler) PublicShare(c *gin.Context) {
	token := strings.TrimSpace(c.Param("token"))
	if token == "" {
		c.Data(http.StatusNotFound, "text/html; charset=utf-8", []byte(renderDriveShareNotFoundHTML()))
		return
	}
	var item models.DriveItem
	if err := database.DB.First(&item, "share_token = ? AND share_enabled = ? AND type = ?", token, true, driveItemTypeFile).Error; err != nil {
		c.Data(http.StatusNotFound, "text/html; charset=utf-8", []byte(renderDriveShareNotFoundHTML()))
		return
	}
	c.Header("X-Content-Type-Options", "nosniff")
	c.Data(http.StatusOK, "text/html; charset=utf-8", []byte(renderDriveShareHTML(item)))
}

func (h *DriveHandler) Search(c *gin.Context) {
	userID := requestUserID(c)
	query := strings.TrimSpace(c.Query("q"))
	files, err := loadDriveFiles(userID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to search drive"})
		return
	}
	results := rankedDriveFiles(files, query)
	c.JSON(http.StatusOK, gin.H{"results": results})
}

func (h *DriveHandler) Context(c *gin.Context) {
	var req driveContextRequest
	_ = c.ShouldBindJSON(&req)
	userID := requestUserIDWithBody(c, req.UserID)
	files, err := selectDriveContextFiles(userID, req.ItemIDs, req.Query)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to build drive context"})
		return
	}
	if len(files) == 0 {
		c.JSON(http.StatusOK, gin.H{"context_blocks": []string{}, "items": []driveItemResponse{}})
		return
	}
	contextBlock := buildDriveContextBlock(files, req.Query)
	c.JSON(http.StatusOK, gin.H{
		"context_blocks": []string{contextBlock},
		"items":          driveItemResponses(files, true),
	})
}

func (h *DriveHandler) loadItem(c *gin.Context, userID string) (models.DriveItem, bool) {
	id := strings.TrimSpace(c.Param("id"))
	var item models.DriveItem
	if id == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "drive item id is required"})
		return item, false
	}
	if err := database.DB.First(&item, "id = ? AND user_id = ?", id, userID).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "drive item not found"})
		return item, false
	}
	return item, true
}

func (h *DriveHandler) loadFolder(c *gin.Context, userID string, id string) (models.DriveItem, bool) {
	var item models.DriveItem
	if err := database.DB.First(&item, "id = ? AND user_id = ? AND type = ?", id, userID, driveItemTypeFolder).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "folder not found"})
		return item, false
	}
	return item, true
}

func loadDriveItems(userID string) ([]models.DriveItem, error) {
	if _, err := ensureDriveRoot(userID); err != nil {
		return nil, err
	}
	var items []models.DriveItem
	err := database.DB.Where("user_id = ?", userID).Order(driveItemOrder).Find(&items).Error
	return items, err
}

func loadDriveFiles(userID string) ([]models.DriveItem, error) {
	if _, err := ensureDriveRoot(userID); err != nil {
		return nil, err
	}
	var files []models.DriveItem
	err := database.DB.Where("user_id = ? AND type = ?", userID, driveItemTypeFile).
		Order("updated_at desc, created_at desc").
		Find(&files).Error
	return files, err
}

const driveItemOrder = "CASE WHEN type = 'folder' THEN 0 ELSE 1 END, lower(name) asc, updated_at desc"

func ensureDriveRoot(userID string) (models.DriveItem, error) {
	userID = normalizedUserID(userID)
	rootID := driveRootItemID(userID)
	now := time.Now()
	root := models.DriveItem{ID: rootID}
	defaultRoot := models.DriveItem{
		ID:        rootID,
		UserID:    userID,
		ParentID:  driveLegacyRootID,
		Type:      driveItemTypeFolder,
		Name:      "我的网盘",
		CreatedAt: now,
		UpdatedAt: now,
	}
	if err := database.DB.Where("id = ? AND user_id = ?", rootID, userID).
		Attrs(defaultRoot).
		FirstOrCreate(&root).Error; err != nil {
		return root, err
	}
	if root.Type != driveItemTypeFolder || root.ParentID != driveLegacyRootID || root.Name == "" {
		root.Type = driveItemTypeFolder
		root.ParentID = driveLegacyRootID
		if root.Name == "" {
			root.Name = "我的网盘"
		}
		root.UpdatedAt = now
		if err := database.DB.Save(&root).Error; err != nil {
			return root, err
		}
	}
	var legacyCount int64
	if err := database.DB.Model(&models.DriveItem{}).
		Where("user_id = ? AND parent_id = ? AND id <> ?", userID, driveLegacyRootID, rootID).
		Count(&legacyCount).Error; err != nil {
		return root, err
	}
	if legacyCount > 0 {
		if err := database.DB.Model(&models.DriveItem{}).
			Where("user_id = ? AND parent_id = ? AND id <> ?", userID, driveLegacyRootID, rootID).
			Update("parent_id", rootID).Error; err != nil {
			return root, err
		}
	}
	return root, nil
}

func driveRootItemID(userID string) string {
	return uuid.NewSHA1(uuid.NameSpaceOID, []byte("drive-root:"+normalizedUserID(userID))).String()
}

func isDriveRootItem(item models.DriveItem, userID string) bool {
	return item.ID == driveRootItemID(userID)
}

func buildDriveTree(items []models.DriveItem) []driveItemResponse {
	children := make(map[string][]models.DriveItem)
	for _, item := range items {
		children[item.ParentID] = append(children[item.ParentID], item)
	}
	var build func(parentID string) []driveItemResponse
	build = func(parentID string) []driveItemResponse {
		group := children[parentID]
		responses := make([]driveItemResponse, 0, len(group))
		for _, item := range group {
			response := driveItemFromModel(item, false)
			if item.Type == driveItemTypeFolder {
				response.Children = build(item.ID)
			}
			responses = append(responses, response)
		}
		return responses
	}
	return build(driveLegacyRootID)
}

func driveDescendantIDs(rootID, userID string) ([]string, error) {
	var children []models.DriveItem
	if err := database.DB.Where("user_id = ? AND parent_id = ?", userID, rootID).Find(&children).Error; err != nil {
		return nil, err
	}
	ids := make([]string, 0, len(children))
	for _, child := range children {
		ids = append(ids, child.ID)
		if child.Type == driveItemTypeFolder {
			nested, err := driveDescendantIDs(child.ID, userID)
			if err != nil {
				return nil, err
			}
			ids = append(ids, nested...)
		}
	}
	return ids, nil
}

func driveFolderContains(rootID, candidateID, userID string) bool {
	if rootID == "" || candidateID == "" {
		return false
	}
	ids, err := driveDescendantIDs(rootID, userID)
	if err != nil {
		return false
	}
	for _, id := range ids {
		if id == candidateID {
			return true
		}
	}
	return false
}

func selectDriveContextFiles(userID string, itemIDs []string, query string) ([]models.DriveItem, error) {
	selectedIDs := uniqueNonEmptyStrings(itemIDs)
	if len(selectedIDs) == 0 || (len(selectedIDs) == 1 && selectedIDs[0] == driveRootItemID(userID)) {
		files, err := loadDriveFiles(userID)
		if err != nil {
			return nil, err
		}
		results := rankedDriveFiles(files, query)
		fileByID := make(map[string]models.DriveItem, len(files))
		for _, file := range files {
			fileByID[file.ID] = file
		}
		selected := make([]models.DriveItem, 0, driveContextLimit)
		for _, result := range results {
			if len(selected) >= driveContextLimit {
				break
			}
			if file, ok := fileByID[result.Item.ID]; ok {
				selected = append(selected, file)
			}
		}
		return selected, nil
	}

	collected := make([]models.DriveItem, 0)
	seen := make(map[string]bool)
	for _, id := range selectedIDs {
		var item models.DriveItem
		err := database.DB.First(&item, "id = ? AND user_id = ?", id, userID).Error
		if errors.Is(err, gorm.ErrRecordNotFound) {
			continue
		}
		if err != nil {
			return nil, err
		}
		if item.Type == driveItemTypeFile {
			if !seen[item.ID] {
				seen[item.ID] = true
				collected = append(collected, item)
			}
			continue
		}
		var files []models.DriveItem
		descendantIDs, err := driveDescendantIDs(item.ID, userID)
		if err != nil {
			return nil, err
		}
		if len(descendantIDs) == 0 {
			continue
		}
		if err := database.DB.Where("user_id = ? AND type = ? AND id IN ?", userID, driveItemTypeFile, descendantIDs).
			Order("updated_at desc").
			Find(&files).Error; err != nil {
			return nil, err
		}
		for _, file := range files {
			if seen[file.ID] {
				continue
			}
			seen[file.ID] = true
			collected = append(collected, file)
		}
	}
	if len(collected) > driveContextLimit {
		return collected[:driveContextLimit], nil
	}
	return collected, nil
}

func rankedDriveFiles(files []models.DriveItem, query string) []driveSearchResult {
	terms := uniqueNonEmptyStrings(knowledgeTextTerms(query))
	results := make([]driveSearchResult, 0, len(files))
	for _, file := range files {
		score := driveFileSearchScore(file, query, terms)
		if strings.TrimSpace(query) != "" && score <= 0 {
			continue
		}
		results = append(results, driveSearchResult{
			Item:    driveItemFromModel(file, false),
			Score:   score,
			Snippet: driveFileSnippet(file, query, 260),
		})
	}
	sort.SliceStable(results, func(i, j int) bool {
		if results[i].Score != results[j].Score {
			return results[i].Score > results[j].Score
		}
		return results[i].Item.UpdatedAt.After(results[j].Item.UpdatedAt)
	})
	if len(results) > 40 {
		return results[:40]
	}
	return results
}

func driveFileSearchScore(file models.DriveItem, query string, terms []string) int {
	query = strings.ToLower(strings.TrimSpace(query))
	if query == "" {
		return 1
	}
	score := 0
	name := strings.ToLower(file.Name)
	summary := strings.ToLower(file.Summary)
	content := strings.ToLower(driveSearchableContent(file))
	if strings.Contains(name, query) {
		score += 90
	}
	if strings.Contains(summary, query) {
		score += 45
	}
	if strings.Contains(content, query) {
		score += 24
	}
	for _, term := range terms {
		if strings.Contains(name, term) {
			score += 18
		}
		if strings.Contains(summary, term) {
			score += 10
		}
		if strings.Contains(content, term) {
			score += 4
		}
	}
	return score
}

func buildDriveContextBlock(files []models.DriveItem, query string) string {
	lines := []string{
		"[Drive Context]",
		"Use these user drive files as grounded reference material. Prefer citing file names when answering.",
	}
	if strings.TrimSpace(query) != "" {
		lines = append(lines, fmt.Sprintf("User focus: %s", strings.TrimSpace(query)))
	}
	lines = append(lines, "", "Files:")
	for index, file := range files {
		lines = append(lines,
			fmt.Sprintf("## %d. %s", index+1, file.Name),
			fmt.Sprintf("ID: %s", file.ID),
		)
		if file.Summary != "" {
			lines = append(lines, fmt.Sprintf("Summary: %s", file.Summary))
		}
		if file.Encoding == driveEncodingBase64 {
			lines = append(lines, "Content: binary file; use only the filename, MIME type, tags, and summary as context.")
		} else if excerpt := knowledgeExcerpt(file.Content, query, 1000); excerpt != "" {
			lines = append(lines, "Excerpt:", excerpt)
		}
		lines = append(lines, "")
	}
	return strings.TrimSpace(strings.Join(lines, "\n"))
}

func driveBreadcrumbs(item models.DriveItem, userID string) []driveItemResponse {
	breadcrumbs := []driveItemResponse{driveItemFromModel(item, false)}
	parentID := item.ParentID
	for parentID != "" {
		var parent models.DriveItem
		if err := database.DB.First(&parent, "id = ? AND user_id = ?", parentID, userID).Error; err != nil {
			break
		}
		breadcrumbs = append([]driveItemResponse{driveItemFromModel(parent, false)}, breadcrumbs...)
		parentID = parent.ParentID
	}
	return breadcrumbs
}

func cleanDriveName(value string) string {
	value = strings.TrimSpace(strings.ReplaceAll(value, "/", "-"))
	value = strings.Join(strings.Fields(value), " ")
	return limitRunes(value, 120)
}

func cleanDriveMimeType(value string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return "text/plain; charset=utf-8"
	}
	return limitRunes(value, 80)
}

func cleanDriveEncoding(value string) string {
	value = strings.ToLower(strings.TrimSpace(value))
	if value == driveEncodingBase64 {
		return driveEncodingBase64
	}
	return ""
}

func generateDriveShareToken() (string, error) {
	tokenBytes := make([]byte, 24)
	if _, err := rand.Read(tokenBytes); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(tokenBytes), nil
}

func generateUniqueDriveShareToken() (string, error) {
	for attempt := 0; attempt < 5; attempt++ {
		token, err := generateDriveShareToken()
		if err != nil {
			return "", err
		}
		var count int64
		if err := database.DB.Model(&models.DriveItem{}).Where("share_token = ?", token).Count(&count).Error; err != nil {
			return "", err
		}
		if count == 0 {
			return token, nil
		}
	}
	return "", errors.New("failed to create unique drive share token")
}

func renderDriveShareHTML(item models.DriveItem) string {
	title := strings.TrimSpace(item.Name)
	if title == "" {
		title = "Shared document"
	}
	metaParts := []string{}
	if item.MimeType != "" {
		metaParts = append(metaParts, item.MimeType)
	}
	if item.Size > 0 {
		metaParts = append(metaParts, fmt.Sprintf("%d bytes", item.Size))
	}
	body := renderDriveShareBody(item)
	return fmt.Sprintf(`<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%s</title>
<style>
:root { color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #172033; background: #f6f8fc; }
body { margin: 0; padding: 32px 16px; }
main { max-width: 960px; margin: 0 auto; border: 1px solid #d8e0ee; border-radius: 8px; background: #fff; box-shadow: 0 18px 50px rgba(23, 32, 51, 0.08); overflow: hidden; }
header { padding: 20px 22px; border-bottom: 1px solid #e4e9f2; }
h1 { margin: 0; font-size: 22px; line-height: 1.3; overflow-wrap: anywhere; }
	p { margin: 8px 0 0; color: #637089; font-size: 13px; }
	.content { padding: 22px; }
	pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font: 14px/1.65 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
	.markdown-body { color: #172033; font-size: 15px; line-height: 1.72; overflow-wrap: anywhere; }
	.markdown-body > *:first-child { margin-top: 0; }
	.markdown-body > *:last-child { margin-bottom: 0; }
	.markdown-body h1, .markdown-body h2, .markdown-body h3, .markdown-body h4, .markdown-body h5, .markdown-body h6 { margin: 22px 0 10px; color: #172033; font-weight: 800; line-height: 1.28; }
	.markdown-body h1 { padding-bottom: 10px; border-bottom: 1px solid #e4e9f2; font-size: 28px; }
	.markdown-body h2 { padding-bottom: 8px; border-bottom: 1px solid #e4e9f2; font-size: 22px; }
	.markdown-body h3 { font-size: 18px; }
	.markdown-body h4, .markdown-body h5, .markdown-body h6 { font-size: 16px; }
	.markdown-body p { margin: 10px 0; color: #253044; font-size: 15px; line-height: 1.72; }
	.markdown-body ul, .markdown-body ol { margin: 10px 0 14px; padding-left: 24px; }
	.markdown-body li { margin: 5px 0; }
	.markdown-body blockquote { margin: 14px 0; padding: 8px 14px; border-left: 4px solid #c6d8ff; background: #f8fbff; color: #4b5871; }
	.markdown-body hr { margin: 22px 0; border: 0; border-top: 1px solid #e4e9f2; }
	.markdown-body code { padding: 2px 5px; border-radius: 5px; background: #eef2f8; color: #172033; font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
	.markdown-body pre { margin: 14px 0; padding: 14px; border: 1px solid #d8e0ee; border-radius: 6px; background: #111827; color: #f8fafc; overflow: auto; }
	.markdown-body pre code { padding: 0; background: transparent; color: inherit; }
	.markdown-table-wrap { width: 100%%; margin: 14px 0; overflow: auto; border: 1px solid #d8e0ee; border-radius: 6px; }
	.markdown-body table { width: 100%%; border-collapse: collapse; font-size: 14px; }
	.markdown-body th, .markdown-body td { padding: 9px 10px; border-bottom: 1px solid #e4e9f2; text-align: left; vertical-align: top; }
	.markdown-body th { background: #f8fbff; color: #172033; font-weight: 800; }
	.markdown-body tr:last-child td { border-bottom: 0; }
	figure { margin: 0; display: grid; gap: 12px; }
img, video, iframe { max-width: 100%%; border: 1px solid #e4e9f2; border-radius: 6px; background: #f8fafc; }
audio { width: 100%%; }
iframe { width: 100%%; height: 70vh; }
a { color: #3157d5; font-weight: 700; }
</style>
</head>
<body>
<main>
<header>
<h1>%s</h1>
%s
</header>
<section class="content">%s</section>
</main>
</body>
</html>`,
		html.EscapeString(title),
		html.EscapeString(title),
		renderDriveShareMeta(metaParts),
		body,
	)
}

func renderDriveShareMeta(parts []string) string {
	if len(parts) == 0 {
		return ""
	}
	return fmt.Sprintf("<p>%s</p>", html.EscapeString(strings.Join(parts, " · ")))
}

func renderDriveShareBody(item models.DriveItem) string {
	if item.Encoding != driveEncodingBase64 {
		content := item.Content
		if strings.TrimSpace(content) == "" {
			content = item.Summary
		}
		if driveShareItemIsMarkdown(item) {
			return fmt.Sprintf(`<article class="markdown-body">%s</article>`, renderDriveShareMarkdown(content))
		}
		return fmt.Sprintf("<pre>%s</pre>", html.EscapeString(content))
	}

	message := html.EscapeString(item.Summary)
	dataURL := driveShareDataURL(item)
	mimeType := strings.ToLower(strings.TrimSpace(item.MimeType))
	name := html.EscapeString(item.Name)
	switch {
	case dataURL != "" && strings.HasPrefix(mimeType, "image/"):
		return fmt.Sprintf(`<figure><img src="%s" alt="%s"><figcaption><p>%s</p></figcaption></figure>`, dataURL, name, message)
	case dataURL != "" && strings.HasPrefix(mimeType, "audio/"):
		return fmt.Sprintf(`<figure><audio controls src="%s"></audio><figcaption><p>%s</p></figcaption></figure>`, dataURL, message)
	case dataURL != "" && strings.HasPrefix(mimeType, "video/"):
		return fmt.Sprintf(`<figure><video controls src="%s"></video><figcaption><p>%s</p></figcaption></figure>`, dataURL, message)
	case dataURL != "" && mimeType == "application/pdf":
		return fmt.Sprintf(`<figure><iframe src="%s" title="%s"></iframe><figcaption><p>%s</p></figcaption></figure>`, dataURL, name, message)
	case dataURL != "":
		return fmt.Sprintf(`<p>%s</p><p><a href="%s" download="%s">下载原文件</a></p>`, message, dataURL, name)
	default:
		return fmt.Sprintf("<p>%s</p>", message)
	}
}

func driveShareItemIsMarkdown(item models.DriveItem) bool {
	mimeType := strings.ToLower(strings.TrimSpace(item.MimeType))
	if strings.Contains(mimeType, "markdown") {
		return true
	}
	extension := driveShareFileExtension(item.Name)
	return extension == "md" || extension == "mdx" || extension == "markdown"
}

func driveShareFileExtension(name string) string {
	name = strings.ToLower(strings.TrimSpace(name))
	if index := strings.LastIndex(name, "."); index >= 0 && index < len(name)-1 {
		return name[index+1:]
	}
	return ""
}

func renderDriveShareMarkdown(content string) string {
	content = strings.ReplaceAll(content, "\r\n", "\n")
	content = strings.ReplaceAll(content, "\r", "\n")
	lines := strings.Split(content, "\n")
	var out strings.Builder
	paragraph := []string{}
	listType := ""
	listItems := []string{}
	quoteLines := []string{}
	inCodeBlock := false
	codeLanguage := ""
	codeLines := []string{}

	flushParagraph := func() {
		if len(paragraph) == 0 {
			return
		}
		out.WriteString("<p>")
		out.WriteString(renderDriveShareInlineMarkdown(strings.Join(paragraph, " ")))
		out.WriteString("</p>")
		paragraph = []string{}
	}
	flushList := func() {
		if listType == "" {
			return
		}
		out.WriteString("<")
		out.WriteString(listType)
		out.WriteString(">")
		for _, item := range listItems {
			out.WriteString("<li>")
			out.WriteString(item)
			out.WriteString("</li>")
		}
		out.WriteString("</")
		out.WriteString(listType)
		out.WriteString(">")
		listType = ""
		listItems = []string{}
	}
	flushQuote := func() {
		if len(quoteLines) == 0 {
			return
		}
		out.WriteString("<blockquote>")
		for _, line := range quoteLines {
			out.WriteString("<p>")
			out.WriteString(renderDriveShareInlineMarkdown(line))
			out.WriteString("</p>")
		}
		out.WriteString("</blockquote>")
		quoteLines = []string{}
	}
	flushAll := func() {
		flushParagraph()
		flushList()
		flushQuote()
	}
	flushCodeBlock := func() {
		languageAttr := ""
		if codeLanguage != "" {
			languageAttr = fmt.Sprintf(` data-language="%s"`, html.EscapeString(codeLanguage))
		}
		out.WriteString("<pre")
		out.WriteString(languageAttr)
		out.WriteString("><code>")
		out.WriteString(html.EscapeString(strings.TrimRight(strings.Join(codeLines, "\n"), "\n")))
		out.WriteString("</code></pre>")
		inCodeBlock = false
		codeLanguage = ""
		codeLines = []string{}
	}

	for index := 0; index < len(lines); index++ {
		rawLine := lines[index]
		line := strings.TrimRight(rawLine, " \t")
		trimmed := strings.TrimSpace(line)

		if inCodeBlock {
			if strings.HasPrefix(trimmed, "```") {
				flushCodeBlock()
				continue
			}
			codeLines = append(codeLines, rawLine)
			continue
		}

		if strings.HasPrefix(trimmed, "```") {
			flushAll()
			inCodeBlock = true
			codeLanguage = strings.TrimSpace(strings.TrimPrefix(trimmed, "```"))
			codeLines = []string{}
			continue
		}

		if trimmed == "" {
			flushAll()
			continue
		}

		if isDriveShareMarkdownTableStart(lines, index) {
			flushAll()
			tableLines := []string{}
			for index < len(lines) && isDriveShareMarkdownTableRow(lines[index]) {
				tableLines = append(tableLines, lines[index])
				index++
			}
			index--
			out.WriteString(renderDriveShareMarkdownTable(tableLines))
			continue
		}

		if level, text, ok := parseDriveShareMarkdownHeading(trimmed); ok {
			flushAll()
			out.WriteString(fmt.Sprintf("<h%d>%s</h%d>", level, renderDriveShareInlineMarkdown(text), level))
			continue
		}

		if isDriveShareMarkdownRule(trimmed) {
			flushAll()
			out.WriteString("<hr>")
			continue
		}

		if text, ok := parseDriveShareMarkdownListItem(trimmed, true); ok {
			flushParagraph()
			flushQuote()
			if listType != "" && listType != "ol" {
				flushList()
			}
			listType = "ol"
			listItems = append(listItems, renderDriveShareInlineMarkdown(text))
			continue
		}

		if text, ok := parseDriveShareMarkdownListItem(trimmed, false); ok {
			flushParagraph()
			flushQuote()
			if listType != "" && listType != "ul" {
				flushList()
			}
			listType = "ul"
			listItems = append(listItems, renderDriveShareInlineMarkdown(text))
			continue
		}

		if strings.HasPrefix(trimmed, ">") {
			flushParagraph()
			flushList()
			quoteLines = append(quoteLines, strings.TrimSpace(strings.TrimPrefix(trimmed, ">")))
			continue
		}

		flushList()
		flushQuote()
		paragraph = append(paragraph, trimmed)
	}

	if inCodeBlock {
		flushCodeBlock()
	}
	flushAll()
	if strings.TrimSpace(out.String()) == "" {
		return "<p></p>"
	}
	return out.String()
}

func parseDriveShareMarkdownHeading(line string) (int, string, bool) {
	level := 0
	for level < len(line) && level < 6 && line[level] == '#' {
		level++
	}
	if level == 0 || len(line) <= level || line[level] != ' ' {
		return 0, "", false
	}
	return level, strings.TrimSpace(line[level:]), true
}

func isDriveShareMarkdownRule(line string) bool {
	if len(line) < 3 {
		return false
	}
	marker := line[0]
	if marker != '-' && marker != '*' && marker != '_' {
		return false
	}
	for _, r := range line {
		if r != rune(marker) && r != ' ' && r != '\t' {
			return false
		}
	}
	return true
}

func parseDriveShareMarkdownListItem(line string, ordered bool) (string, bool) {
	if !ordered {
		if len(line) > 2 && (line[0] == '-' || line[0] == '*' || line[0] == '+') && line[1] == ' ' {
			return strings.TrimSpace(line[2:]), true
		}
		return "", false
	}
	index := 0
	for index < len(line) && line[index] >= '0' && line[index] <= '9' {
		index++
	}
	if index == 0 || index+1 >= len(line) {
		return "", false
	}
	if (line[index] == '.' || line[index] == ')') && line[index+1] == ' ' {
		return strings.TrimSpace(line[index+2:]), true
	}
	return "", false
}

func isDriveShareMarkdownTableStart(lines []string, index int) bool {
	if index+1 >= len(lines) || !isDriveShareMarkdownTableRow(lines[index]) || !isDriveShareMarkdownTableRow(lines[index+1]) {
		return false
	}
	headerCells := splitDriveShareMarkdownTableRow(lines[index])
	separatorCells := splitDriveShareMarkdownTableRow(lines[index+1])
	if len(headerCells) <= 1 || len(separatorCells) < len(headerCells) {
		return false
	}
	for _, cell := range separatorCells[:len(headerCells)] {
		if !isDriveShareMarkdownTableSeparator(cell) {
			return false
		}
	}
	return true
}

func isDriveShareMarkdownTableRow(line string) bool {
	trimmed := strings.TrimSpace(line)
	return strings.Contains(trimmed, "|") && len(splitDriveShareMarkdownTableRow(trimmed)) > 1
}

func splitDriveShareMarkdownTableRow(line string) []string {
	value := strings.TrimSpace(line)
	value = strings.TrimPrefix(value, "|")
	value = strings.TrimSuffix(value, "|")
	parts := strings.Split(value, "|")
	cells := make([]string, 0, len(parts))
	for _, part := range parts {
		cells = append(cells, strings.TrimSpace(part))
	}
	return cells
}

func isDriveShareMarkdownTableSeparator(cell string) bool {
	cell = strings.TrimSpace(cell)
	if len(cell) < 3 {
		return false
	}
	cell = strings.Trim(cell, ":")
	if len(cell) < 3 {
		return false
	}
	for _, r := range cell {
		if r != '-' {
			return false
		}
	}
	return true
}

func renderDriveShareMarkdownTable(tableLines []string) string {
	if len(tableLines) < 2 {
		return ""
	}
	header := splitDriveShareMarkdownTableRow(tableLines[0])
	separator := splitDriveShareMarkdownTableRow(tableLines[1])
	columnCount := len(header)
	aligns := make([]string, columnCount)
	for index := 0; index < columnCount; index++ {
		if index < len(separator) {
			aligns[index] = driveShareMarkdownTableAlign(separator[index])
		}
	}
	var out strings.Builder
	out.WriteString(`<div class="markdown-table-wrap"><table><thead><tr>`)
	for index, cell := range header {
		out.WriteString(renderDriveShareMarkdownTableCell("th", cell, aligns[index]))
	}
	out.WriteString("</tr></thead><tbody>")
	for _, line := range tableLines[2:] {
		cells := splitDriveShareMarkdownTableRow(line)
		out.WriteString("<tr>")
		for index := 0; index < columnCount; index++ {
			cell := ""
			if index < len(cells) {
				cell = cells[index]
			}
			out.WriteString(renderDriveShareMarkdownTableCell("td", cell, aligns[index]))
		}
		out.WriteString("</tr>")
	}
	out.WriteString("</tbody></table></div>")
	return out.String()
}

func driveShareMarkdownTableAlign(separator string) string {
	separator = strings.TrimSpace(separator)
	left := strings.HasPrefix(separator, ":")
	right := strings.HasSuffix(separator, ":")
	switch {
	case left && right:
		return "center"
	case right:
		return "right"
	default:
		return ""
	}
}

func renderDriveShareMarkdownTableCell(tag, cell, align string) string {
	style := ""
	if align != "" {
		style = fmt.Sprintf(` style="text-align:%s"`, align)
	}
	return fmt.Sprintf("<%s%s>%s</%s>", tag, style, renderDriveShareInlineMarkdown(cell), tag)
}

func renderDriveShareInlineMarkdown(text string) string {
	var out strings.Builder
	for i := 0; i < len(text); {
		switch {
		case text[i] == '`':
			if end := strings.Index(text[i+1:], "`"); end >= 0 {
				code := text[i+1 : i+1+end]
				out.WriteString("<code>")
				out.WriteString(html.EscapeString(code))
				out.WriteString("</code>")
				i += end + 2
				continue
			}
		case strings.HasPrefix(text[i:], "**"):
			if end := strings.Index(text[i+2:], "**"); end >= 0 {
				inner := text[i+2 : i+2+end]
				out.WriteString("<strong>")
				out.WriteString(renderDriveShareInlineMarkdown(inner))
				out.WriteString("</strong>")
				i += end + 4
				continue
			}
		case text[i] == '[':
			if label, href, advance, ok := parseDriveShareMarkdownLink(text[i:]); ok {
				if safeHref := sanitizeDriveShareMarkdownHref(href); safeHref != "" {
					out.WriteString(`<a href="`)
					out.WriteString(html.EscapeString(safeHref))
					out.WriteString(`" target="_blank" rel="noopener noreferrer">`)
					out.WriteString(renderDriveShareInlineMarkdown(label))
					out.WriteString("</a>")
					i += advance
					continue
				}
			}
		}
		r, size := utf8.DecodeRuneInString(text[i:])
		out.WriteString(html.EscapeString(string(r)))
		i += size
	}
	return out.String()
}

func parseDriveShareMarkdownLink(text string) (string, string, int, bool) {
	closeLabel := strings.Index(text, "](")
	if closeLabel <= 0 {
		return "", "", 0, false
	}
	closeHref := strings.Index(text[closeLabel+2:], ")")
	if closeHref < 0 {
		return "", "", 0, false
	}
	hrefStart := closeLabel + 2
	hrefEnd := hrefStart + closeHref
	return text[1:closeLabel], text[hrefStart:hrefEnd], hrefEnd + 1, true
}

func sanitizeDriveShareMarkdownHref(href string) string {
	href = strings.TrimSpace(href)
	lower := strings.ToLower(href)
	if strings.HasPrefix(lower, "http://") || strings.HasPrefix(lower, "https://") || strings.HasPrefix(lower, "mailto:") {
		return href
	}
	return ""
}

func driveShareDataURL(item models.DriveItem) string {
	content := strings.TrimSpace(item.Content)
	if content == "" {
		return ""
	}
	mimeType := strings.TrimSpace(item.MimeType)
	if mimeType == "" {
		mimeType = "application/octet-stream"
	}
	return "data:" + html.EscapeString(mimeType) + ";base64," + html.EscapeString(content)
}

func renderDriveShareNotFoundHTML() string {
	return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>文档不可访问</title>
<style>
body { margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 24px; background: #f6f8fc; color: #172033; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
main { max-width: 520px; padding: 28px; border: 1px solid #d8e0ee; border-radius: 8px; background: #fff; box-shadow: 0 18px 50px rgba(23, 32, 51, 0.08); }
h1 { margin: 0 0 8px; font-size: 22px; }
p { margin: 0; color: #637089; line-height: 1.6; }
</style>
</head>
<body>
<main>
<h1>文档不可访问</h1>
<p>这个分享链接不存在，或分享权限已经关闭。</p>
</main>
</body>
</html>`
}

func summarizeDriveBinaryFile(name, mimeType string, size int64) string {
	parts := []string{"Binary file"}
	if strings.TrimSpace(mimeType) != "" {
		parts = append(parts, "MIME: "+strings.TrimSpace(mimeType))
	}
	if size > 0 {
		parts = append(parts, fmt.Sprintf("Size: %d bytes", size))
	}
	if strings.TrimSpace(name) != "" {
		parts = append(parts, "Name: "+strings.TrimSpace(name))
	}
	return strings.Join(parts, " · ")
}

func driveSearchableContent(file models.DriveItem) string {
	if file.Encoding == driveEncodingBase64 {
		return ""
	}
	return file.Content
}

func driveFileSnippet(file models.DriveItem, query string, maxRunes int) string {
	if file.Encoding == driveEncodingBase64 {
		return file.Summary
	}
	return knowledgeExcerpt(file.Content, query, maxRunes)
}

func driveItemFromModel(item models.DriveItem, includeContent bool) driveItemResponse {
	response := driveItemResponse{
		ID:           item.ID,
		UserID:       item.UserID,
		ParentID:     item.ParentID,
		Type:         item.Type,
		Name:         item.Name,
		MimeType:     item.MimeType,
		Encoding:     item.Encoding,
		Size:         item.Size,
		Summary:      item.Summary,
		Tags:         decodeKnowledgeTags(item.TagsJSON),
		ShareEnabled: item.ShareEnabled,
		ShareToken:   item.ShareToken,
		CreatedAt:    item.CreatedAt,
		UpdatedAt:    item.UpdatedAt,
	}
	if includeContent {
		response.Content = item.Content
	}
	return response
}

func driveItemFromResponse(response driveItemResponse) models.DriveItem {
	return models.DriveItem{
		ID:           response.ID,
		UserID:       response.UserID,
		ParentID:     response.ParentID,
		Type:         response.Type,
		Name:         response.Name,
		MimeType:     response.MimeType,
		Encoding:     response.Encoding,
		Size:         response.Size,
		Summary:      response.Summary,
		TagsJSON:     knowledgeJSON(response.Tags),
		Content:      response.Content,
		ShareEnabled: response.ShareEnabled,
		ShareToken:   response.ShareToken,
		CreatedAt:    response.CreatedAt,
		UpdatedAt:    response.UpdatedAt,
	}
}

func driveItemResponses(items []models.DriveItem, includeContent bool) []driveItemResponse {
	responses := make([]driveItemResponse, 0, len(items))
	for _, item := range items {
		responses = append(responses, driveItemFromModel(item, includeContent))
	}
	return responses
}
