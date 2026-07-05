package handlers

import (
	"encoding/base64"
	"errors"
	"fmt"
	"net/http"
	"sort"
	"strings"
	"time"

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

type driveContextRequest struct {
	UserID  string   `json:"user_id,omitempty"`
	Query   string   `json:"query,omitempty"`
	ItemIDs []string `json:"item_ids,omitempty"`
}

type driveItemResponse struct {
	ID        string              `json:"id"`
	UserID    string              `json:"user_id"`
	ParentID  string              `json:"parent_id,omitempty"`
	Type      string              `json:"type"`
	Name      string              `json:"name"`
	MimeType  string              `json:"mime_type,omitempty"`
	Encoding  string              `json:"encoding,omitempty"`
	Size      int64               `json:"size"`
	Summary   string              `json:"summary,omitempty"`
	Tags      []string            `json:"tags,omitempty"`
	Content   string              `json:"content,omitempty"`
	Children  []driveItemResponse `json:"children,omitempty"`
	CreatedAt time.Time           `json:"created_at"`
	UpdatedAt time.Time           `json:"updated_at"`
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
		ID:        item.ID,
		UserID:    item.UserID,
		ParentID:  item.ParentID,
		Type:      item.Type,
		Name:      item.Name,
		MimeType:  item.MimeType,
		Encoding:  item.Encoding,
		Size:      item.Size,
		Summary:   item.Summary,
		Tags:      decodeKnowledgeTags(item.TagsJSON),
		CreatedAt: item.CreatedAt,
		UpdatedAt: item.UpdatedAt,
	}
	if includeContent {
		response.Content = item.Content
	}
	return response
}

func driveItemFromResponse(response driveItemResponse) models.DriveItem {
	return models.DriveItem{
		ID:        response.ID,
		UserID:    response.UserID,
		ParentID:  response.ParentID,
		Type:      response.Type,
		Name:      response.Name,
		MimeType:  response.MimeType,
		Encoding:  response.Encoding,
		Size:      response.Size,
		Summary:   response.Summary,
		TagsJSON:  knowledgeJSON(response.Tags),
		Content:   response.Content,
		CreatedAt: response.CreatedAt,
		UpdatedAt: response.UpdatedAt,
	}
}

func driveItemResponses(items []models.DriveItem, includeContent bool) []driveItemResponse {
	responses := make([]driveItemResponse, 0, len(items))
	for _, item := range items {
		responses = append(responses, driveItemFromModel(item, includeContent))
	}
	return responses
}
