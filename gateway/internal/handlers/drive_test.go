package handlers

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
)

func setupDriveTest(t *testing.T) (*gin.Engine, *DriveHandler) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}
	handler := NewDriveHandler()
	router := gin.New()
	router.GET("/api/drive/tree", handler.Tree)
	router.GET("/api/drive/items", handler.List)
	router.POST("/api/drive/folders", handler.CreateFolder)
	router.POST("/api/drive/files", handler.CreateFile)
	router.GET("/api/drive/items/:id", handler.Get)
	router.PUT("/api/drive/items/:id", handler.Update)
	router.PUT("/api/drive/items/:id/share", handler.Share)
	router.DELETE("/api/drive/items/:id", handler.Delete)
	router.GET("/api/drive/items/:id/download", handler.Download)
	router.GET("/share/drive/:token", handler.PublicShare)
	router.GET("/api/drive/search", handler.Search)
	router.POST("/api/drive/context", handler.Context)
	return router, handler
}

func TestDriveTreeIsScopedByUser(t *testing.T) {
	router, _ := setupDriveTest(t)
	now := time.Now()
	items := []models.DriveItem{
		{ID: "folder-a", UserID: "user-a", Type: driveItemTypeFolder, Name: "A", CreatedAt: now, UpdatedAt: now},
		{ID: "file-a", UserID: "user-a", ParentID: "folder-a", Type: driveItemTypeFile, Name: "A.txt", Content: "alpha", CreatedAt: now, UpdatedAt: now},
		{ID: "folder-b", UserID: "user-b", Type: driveItemTypeFolder, Name: "B", CreatedAt: now, UpdatedAt: now},
	}
	if err := database.DB.Create(&items).Error; err != nil {
		t.Fatalf("create drive items: %v", err)
	}

	req := httptest.NewRequest(http.MethodGet, "/api/drive/tree", nil)
	req.Header.Set("X-User-ID", "user-a")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	var payload struct {
		Items     []driveItemResponse `json:"items"`
		FlatItems []driveItemResponse `json:"flat_items"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if len(payload.FlatItems) != 3 || strings.Contains(recorder.Body.String(), "folder-b") {
		t.Fatalf("expected only user-a drive items, got %s", recorder.Body.String())
	}
	if len(payload.Items) != 1 || payload.Items[0].ID != driveRootItemID("user-a") || len(payload.Items[0].Children) != 1 {
		t.Fatalf("expected user-a root with nested tree, got %#v", payload.Items)
	}
}

func TestDriveTreeCreatesUserRoot(t *testing.T) {
	router, _ := setupDriveTest(t)

	req := httptest.NewRequest(http.MethodGet, "/api/drive/tree", nil)
	req.Header.Set("X-User-ID", "user-a")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	var payload struct {
		Items []driveItemResponse `json:"items"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if len(payload.Items) != 1 || payload.Items[0].ID != driveRootItemID("user-a") || payload.Items[0].Type != driveItemTypeFolder {
		t.Fatalf("expected default root folder, got %#v", payload.Items)
	}
}

func TestDriveFileSearchAndDownload(t *testing.T) {
	router, _ := setupDriveTest(t)
	folder := createDriveFolderViaAPI(t, router, "user-a", "", "Research")
	file := createDriveFileViaAPI(t, router, "user-a", folder.ID, "RAG Notes.md", "RAG embedding search needs chunking and reranking.")

	searchReq := httptest.NewRequest(http.MethodGet, "/api/drive/search?q=embedding", nil)
	searchReq.Header.Set("X-User-ID", "user-a")
	searchRecorder := httptest.NewRecorder()
	router.ServeHTTP(searchRecorder, searchReq)
	if searchRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected search status %d: %s", searchRecorder.Code, searchRecorder.Body.String())
	}
	if !strings.Contains(searchRecorder.Body.String(), file.Name) {
		t.Fatalf("expected search to find file, got %s", searchRecorder.Body.String())
	}

	downloadReq := httptest.NewRequest(http.MethodGet, "/api/drive/items/"+file.ID+"/download", nil)
	downloadReq.Header.Set("X-User-ID", "user-a")
	downloadRecorder := httptest.NewRecorder()
	router.ServeHTTP(downloadRecorder, downloadReq)
	if downloadRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected download status %d: %s", downloadRecorder.Code, downloadRecorder.Body.String())
	}
	if !strings.Contains(downloadRecorder.Header().Get("Content-Disposition"), file.Name) {
		t.Fatalf("expected attachment filename, got %q", downloadRecorder.Header().Get("Content-Disposition"))
	}
	if !strings.Contains(downloadRecorder.Body.String(), "chunking") {
		t.Fatalf("expected file content, got %s", downloadRecorder.Body.String())
	}
}

func TestDriveFileCreateDoesNotAutoGenerateTags(t *testing.T) {
	router, _ := setupDriveTest(t)
	file := createDriveFileViaAPI(t, router, "user-a", "", "Reading.txt", "paragraph passage level")

	if len(file.Tags) != 0 {
		t.Fatalf("expected no auto-generated drive tags, got %#v", file.Tags)
	}
}

func TestDriveFileUpdateChangesContentMetadataAndFolder(t *testing.T) {
	router, _ := setupDriveTest(t)
	sourceFolder := createDriveFolderViaAPI(t, router, "user-a", "", "Source")
	targetFolder := createDriveFolderViaAPI(t, router, "user-a", "", "Knowledge")
	file := createDriveFileViaAPI(t, router, "user-a", sourceFolder.ID, "Draft.md", "old content")

	payload := map[string]interface{}{
		"parent_id": targetFolder.ID,
		"name":      "Final.md",
		"mime_type": "text/markdown; charset=utf-8",
		"content":   "# Final\n\nnew searchable content",
		"summary":   "final summary",
		"tags":      []string{"问答", "知识"},
	}
	body, _ := json.Marshal(payload)
	req := httptest.NewRequest(http.MethodPut, "/api/drive/items/"+file.ID, bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-User-ID", "user-a")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected update status %d: %s", recorder.Code, recorder.Body.String())
	}
	var response struct {
		Item driveItemResponse `json:"item"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("decode update response: %v", err)
	}
	updated := response.Item
	if updated.Name != "Final.md" || updated.ParentID != targetFolder.ID {
		t.Fatalf("expected renamed and moved file, got %#v", updated)
	}
	if updated.Content != "# Final\n\nnew searchable content" || updated.Summary != "final summary" {
		t.Fatalf("expected updated content and summary, got %#v", updated)
	}
	if updated.Size != int64(len([]byte(updated.Content))) || len(updated.Tags) != 2 {
		t.Fatalf("expected updated size and tags, got %#v", updated)
	}

	searchReq := httptest.NewRequest(http.MethodGet, "/api/drive/search?q=searchable", nil)
	searchReq.Header.Set("X-User-ID", "user-a")
	searchRecorder := httptest.NewRecorder()
	router.ServeHTTP(searchRecorder, searchReq)
	if searchRecorder.Code != http.StatusOK || !strings.Contains(searchRecorder.Body.String(), "Final.md") {
		t.Fatalf("expected updated content to be searchable, got %d: %s", searchRecorder.Code, searchRecorder.Body.String())
	}
}

func TestDriveFolderRejectsContentUpdate(t *testing.T) {
	router, _ := setupDriveTest(t)
	folder := createDriveFolderViaAPI(t, router, "user-a", "", "Folder")

	body := []byte(`{"content":"not allowed"}`)
	req := httptest.NewRequest(http.MethodPut, "/api/drive/items/"+folder.ID, bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-User-ID", "user-a")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusBadRequest {
		t.Fatalf("expected folder content update to fail, got %d: %s", recorder.Code, recorder.Body.String())
	}
}

func TestDriveContextOmitsTags(t *testing.T) {
	router, _ := setupDriveTest(t)
	file := createDriveFileWithTagsViaAPI(t, router, "user-a", "", "Guide.md", "grounded body text", []string{"noise-tag"})

	body := []byte(`{"item_ids":["` + file.ID + `"],"query":"grounded"}`)
	req := httptest.NewRequest(http.MethodPost, "/api/drive/context", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-User-ID", "user-a")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	var payload struct {
		ContextBlocks []string `json:"context_blocks"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode context: %v", err)
	}
	block := strings.Join(payload.ContextBlocks, "\n")
	if strings.Contains(block, "Tags:") || strings.Contains(block, "noise-tag") {
		t.Fatalf("expected drive context to omit tags, got %s", block)
	}
}

func TestDriveContextExpandsFolderSelection(t *testing.T) {
	router, _ := setupDriveTest(t)
	folder := createDriveFolderViaAPI(t, router, "user-a", "", "Knowledge")
	createDriveFileViaAPI(t, router, "user-a", folder.ID, "A.md", "苹果 香蕉 召回")
	createDriveFileViaAPI(t, router, "user-a", folder.ID, "B.md", "火箭 卫星 轨道")

	body := []byte(`{"item_ids":["` + folder.ID + `"],"query":"轨道"}`)
	req := httptest.NewRequest(http.MethodPost, "/api/drive/context", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-User-ID", "user-a")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	if !strings.Contains(recorder.Body.String(), "A.md") || !strings.Contains(recorder.Body.String(), "B.md") {
		t.Fatalf("expected folder context to include descendant files, got %s", recorder.Body.String())
	}
}

func TestDriveContextSearchIncludesFileContent(t *testing.T) {
	router, _ := setupDriveTest(t)
	createDriveFileViaAPI(t, router, "user-a", "", "Rerank.md", "needle-reranking-detail should appear in the generated context")

	body := []byte(`{"query":"needle-reranking-detail"}`)
	req := httptest.NewRequest(http.MethodPost, "/api/drive/context", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-User-ID", "user-a")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	if !strings.Contains(recorder.Body.String(), "needle-reranking-detail") {
		t.Fatalf("expected auto-selected context to include file content, got %s", recorder.Body.String())
	}
}

func TestDriveShareCanBeEnabledAndDisabled(t *testing.T) {
	router, _ := setupDriveTest(t)
	file := createDriveFileViaAPI(t, router, "user-a", "", "Share.md", "public readable content")

	enabled := updateDriveShareViaAPI(t, router, "user-a", file.ID, true)
	if !enabled.ShareEnabled || enabled.ShareToken == "" {
		t.Fatalf("expected enabled share with token, got %#v", enabled)
	}

	sharedReq := httptest.NewRequest(http.MethodGet, "/share/drive/"+enabled.ShareToken, nil)
	sharedRecorder := httptest.NewRecorder()
	router.ServeHTTP(sharedRecorder, sharedReq)
	if sharedRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected public share status %d: %s", sharedRecorder.Code, sharedRecorder.Body.String())
	}
	if !strings.Contains(sharedRecorder.Body.String(), "public readable content") {
		t.Fatalf("expected public share to include content, got %s", sharedRecorder.Body.String())
	}

	disabled := updateDriveShareViaAPI(t, router, "user-a", file.ID, false)
	if disabled.ShareEnabled {
		t.Fatalf("expected share to be disabled, got %#v", disabled)
	}

	blockedReq := httptest.NewRequest(http.MethodGet, "/share/drive/"+enabled.ShareToken, nil)
	blockedRecorder := httptest.NewRecorder()
	router.ServeHTTP(blockedRecorder, blockedReq)
	if blockedRecorder.Code != http.StatusNotFound {
		t.Fatalf("expected disabled share to be unavailable, got %d: %s", blockedRecorder.Code, blockedRecorder.Body.String())
	}
	if strings.Contains(blockedRecorder.Body.String(), "public readable content") {
		t.Fatalf("disabled share leaked content: %s", blockedRecorder.Body.String())
	}
}

func TestDrivePublicShareRendersMarkdown(t *testing.T) {
	router, _ := setupDriveTest(t)
	file := createDriveFileViaAPI(t, router, "user-a", "", "Markdown.md", "# 标题\n\n- **重点** and `code`\n\n| A | B |\n| --- | ---: |\n| 1 | 2 |\n\n<script>alert(1)</script>")
	enabled := updateDriveShareViaAPI(t, router, "user-a", file.ID, true)

	req := httptest.NewRequest(http.MethodGet, "/share/drive/"+enabled.ShareToken, nil)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)
	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected public share status %d: %s", recorder.Code, recorder.Body.String())
	}
	body := recorder.Body.String()
	if !strings.Contains(body, "<h1>标题</h1>") {
		t.Fatalf("expected markdown heading to render, got %s", body)
	}
	if !strings.Contains(body, "<li><strong>重点</strong> and <code>code</code></li>") {
		t.Fatalf("expected markdown list and inline formatting to render, got %s", body)
	}
	if !strings.Contains(body, `<div class="markdown-table-wrap"><table>`) || !strings.Contains(body, `<td style="text-align:right">2</td>`) {
		t.Fatalf("expected markdown table to render, got %s", body)
	}
	if strings.Contains(body, "<script>alert(1)</script>") || !strings.Contains(body, "&lt;script&gt;alert(1)&lt;/script&gt;") {
		t.Fatalf("expected raw html to be escaped, got %s", body)
	}
}

func TestDriveDeleteRemovesDescendants(t *testing.T) {
	router, _ := setupDriveTest(t)
	folder := createDriveFolderViaAPI(t, router, "user-a", "", "Archive")
	file := createDriveFileViaAPI(t, router, "user-a", folder.ID, "Old.md", "delete me")

	req := httptest.NewRequest(http.MethodDelete, "/api/drive/items/"+folder.ID, nil)
	req.Header.Set("X-User-ID", "user-a")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)
	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected delete status %d: %s", recorder.Code, recorder.Body.String())
	}

	var count int64
	if err := database.DB.Model(&models.DriveItem{}).Where("id IN ?", []string{folder.ID, file.ID}).Count(&count).Error; err != nil {
		t.Fatalf("count items: %v", err)
	}
	if count != 0 {
		t.Fatalf("expected folder and descendants to be deleted, count=%d", count)
	}
}

func TestDriveRootCannotBeDeleted(t *testing.T) {
	router, _ := setupDriveTest(t)
	root := loadDriveRootForTest(t, "user-a")

	req := httptest.NewRequest(http.MethodDelete, "/api/drive/items/"+root.ID, nil)
	req.Header.Set("X-User-ID", "user-a")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusBadRequest {
		t.Fatalf("expected root delete to fail, got %d: %s", recorder.Code, recorder.Body.String())
	}
}

func createDriveFolderViaAPI(t *testing.T, router *gin.Engine, userID, parentID, name string) driveItemResponse {
	t.Helper()
	payload := map[string]string{"parent_id": parentID, "name": name}
	body, _ := json.Marshal(payload)
	req := httptest.NewRequest(http.MethodPost, "/api/drive/folders", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-User-ID", userID)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)
	if recorder.Code != http.StatusCreated {
		t.Fatalf("unexpected create folder status %d: %s", recorder.Code, recorder.Body.String())
	}
	var response struct {
		Item driveItemResponse `json:"item"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("decode folder: %v", err)
	}
	return response.Item
}

func createDriveFileViaAPI(t *testing.T, router *gin.Engine, userID, parentID, name, content string) driveItemResponse {
	return createDriveFileWithTagsViaAPI(t, router, userID, parentID, name, content, nil)
}

func createDriveFileWithTagsViaAPI(t *testing.T, router *gin.Engine, userID, parentID, name, content string, tags []string) driveItemResponse {
	t.Helper()
	payload := map[string]interface{}{"parent_id": parentID, "name": name, "content": content}
	if tags != nil {
		payload["tags"] = tags
	}
	body, _ := json.Marshal(payload)
	req := httptest.NewRequest(http.MethodPost, "/api/drive/files", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-User-ID", userID)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)
	if recorder.Code != http.StatusCreated {
		t.Fatalf("unexpected create file status %d: %s", recorder.Code, recorder.Body.String())
	}
	var response struct {
		Item driveItemResponse `json:"item"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("decode file: %v", err)
	}
	return response.Item
}

func updateDriveShareViaAPI(t *testing.T, router *gin.Engine, userID, itemID string, enabled bool) driveItemResponse {
	t.Helper()
	payload := map[string]bool{"enabled": enabled}
	body, _ := json.Marshal(payload)
	req := httptest.NewRequest(http.MethodPut, "/api/drive/items/"+itemID+"/share", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-User-ID", userID)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)
	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected share status %d: %s", recorder.Code, recorder.Body.String())
	}
	var response struct {
		Item driveItemResponse `json:"item"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("decode share response: %v", err)
	}
	return response.Item
}

func loadDriveRootForTest(t *testing.T, userID string) driveItemResponse {
	t.Helper()
	root, err := ensureDriveRoot(userID)
	if err != nil {
		t.Fatalf("ensure root: %v", err)
	}
	return driveItemFromModel(root, false)
}
