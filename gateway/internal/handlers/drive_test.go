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
	router.DELETE("/api/drive/items/:id", handler.Delete)
	router.GET("/api/drive/items/:id/download", handler.Download)
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

func loadDriveRootForTest(t *testing.T, userID string) driveItemResponse {
	t.Helper()
	root, err := ensureDriveRoot(userID)
	if err != nil {
		t.Fatalf("ensure root: %v", err)
	}
	return driveItemFromModel(root, false)
}
