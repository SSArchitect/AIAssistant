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

func setupKnowledgeTest(t *testing.T) (*gin.Engine, *KnowledgeHandler) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}
	handler := NewKnowledgeHandler()
	router := gin.New()
	router.GET("/api/projects", handler.List)
	router.POST("/api/projects", handler.Create)
	router.PUT("/api/projects/order", handler.Reorder)
	router.POST("/api/projects/from-selection", handler.CreateFromSelection)
	router.GET("/api/projects/:id", handler.Get)
	router.DELETE("/api/projects/:id", handler.Delete)
	router.POST("/api/projects/:id/documents", handler.CreateDocument)
	router.GET("/api/projects/:id/search", handler.Search)
	router.POST("/api/projects/:id/context", handler.Context)
	return router, handler
}

func TestKnowledgeProjectsAreScopedByUser(t *testing.T) {
	router, _ := setupKnowledgeTest(t)
	now := time.Now()
	projects := []models.KnowledgeProject{
		{ID: "project-a", UserID: "user-a", Name: "A", SortOrder: 0, CreatedAt: now, UpdatedAt: now},
		{ID: "project-b", UserID: "user-b", Name: "B", SortOrder: 0, CreatedAt: now, UpdatedAt: now},
	}
	if err := database.DB.Create(&projects).Error; err != nil {
		t.Fatalf("create projects: %v", err)
	}

	req := httptest.NewRequest(http.MethodGet, "/api/projects", nil)
	req.Header.Set("X-User-ID", "user-a")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	var payload struct {
		Projects []knowledgeProjectResponse `json:"projects"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if len(payload.Projects) != 1 || payload.Projects[0].ID != "project-a" {
		t.Fatalf("expected only user-a project, got %#v", payload.Projects)
	}
}

func TestKnowledgeDocumentCreatesSearchableMapLink(t *testing.T) {
	router, _ := setupKnowledgeTest(t)
	project := createKnowledgeProjectForTest(t, "project-map", "user-a")

	createKnowledgeDocumentViaAPI(t, router, project.ID, "user-a", `{
		"title":"RAG 系统设计",
		"content":"RAG 系统设计需要检索、重排、引用和上下文压缩。向量数据库用于召回相关资料。"
	}`)
	createKnowledgeDocumentViaAPI(t, router, project.ID, "user-a", `{
		"title":"向量数据库调研",
		"content":"向量数据库用于 RAG 召回，关注 embedding、索引、相似度检索和重排。"
	}`)

	getReq := httptest.NewRequest(http.MethodGet, "/api/projects/"+project.ID, nil)
	getReq.Header.Set("X-User-ID", "user-a")
	getRecorder := httptest.NewRecorder()
	router.ServeHTTP(getRecorder, getReq)
	if getRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected get status %d: %s", getRecorder.Code, getRecorder.Body.String())
	}
	var detail knowledgeProjectDetailResponse
	if err := json.Unmarshal(getRecorder.Body.Bytes(), &detail); err != nil {
		t.Fatalf("decode detail: %v", err)
	}
	if len(detail.Documents) != 2 {
		t.Fatalf("expected two documents, got %d", len(detail.Documents))
	}
	if len(detail.Links) == 0 {
		t.Fatalf("expected at least one inferred map link, got none")
	}

	searchReq := httptest.NewRequest(http.MethodGet, "/api/projects/"+project.ID+"/search?q=embedding", nil)
	searchReq.Header.Set("X-User-ID", "user-a")
	searchRecorder := httptest.NewRecorder()
	router.ServeHTTP(searchRecorder, searchReq)
	if searchRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected search status %d: %s", searchRecorder.Code, searchRecorder.Body.String())
	}
	if !strings.Contains(searchRecorder.Body.String(), "向量数据库") {
		t.Fatalf("expected search to find vector database document, got %s", searchRecorder.Body.String())
	}
}

func TestKnowledgeContextUsesSelectedDocuments(t *testing.T) {
	router, _ := setupKnowledgeTest(t)
	project := createKnowledgeProjectForTest(t, "project-context", "user-a")
	docA := createKnowledgeDocumentForTest(t, project.ID, "user-a", "文档 A", "苹果 香蕉 召回")
	docB := createKnowledgeDocumentForTest(t, project.ID, "user-a", "文档 B", "火箭 卫星 轨道")

	body := []byte(`{"document_ids":["` + docB.ID + `"],"query":"轨道"}`)
	req := httptest.NewRequest(http.MethodPost, "/api/projects/"+project.ID+"/context", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-User-ID", "user-a")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	if strings.Contains(recorder.Body.String(), docA.Title) {
		t.Fatalf("context should not include unselected doc: %s", recorder.Body.String())
	}
	if !strings.Contains(recorder.Body.String(), docB.Title) {
		t.Fatalf("context should include selected doc: %s", recorder.Body.String())
	}
}

func TestKnowledgeCreateFromSelectionCopiesDocuments(t *testing.T) {
	router, _ := setupKnowledgeTest(t)
	projectA := createKnowledgeProjectForTest(t, "project-a", "user-a")
	projectB := createKnowledgeProjectForTest(t, "project-b", "user-a")
	docA := createKnowledgeDocumentForTest(t, projectA.ID, "user-a", "RAG 设计", "检索增强生成")
	docB := createKnowledgeDocumentForTest(t, projectB.ID, "user-a", "Agent 笔记", "工具调用和上下文")

	payload := map[string]interface{}{
		"name":         "组合 Project",
		"document_ids": []string{docA.ID, docB.ID},
	}
	body, _ := json.Marshal(payload)
	req := httptest.NewRequest(http.MethodPost, "/api/projects/from-selection", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-User-ID", "user-a")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusCreated {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	var detail knowledgeProjectDetailResponse
	if err := json.Unmarshal(recorder.Body.Bytes(), &detail); err != nil {
		t.Fatalf("decode detail: %v", err)
	}
	if detail.Project.Name != "组合 Project" || len(detail.Documents) != 2 {
		t.Fatalf("expected new project with two copied docs, got %#v", detail)
	}
	sourceIDs := map[string]bool{}
	for _, doc := range detail.Documents {
		sourceIDs[doc.SourceDocumentID] = true
	}
	if !sourceIDs[docA.ID] || !sourceIDs[docB.ID] {
		t.Fatalf("expected copied docs to retain source document ids, got %#v", detail.Documents)
	}
}

func createKnowledgeProjectForTest(t *testing.T, id, userID string) models.KnowledgeProject {
	t.Helper()
	now := time.Now()
	project := models.KnowledgeProject{
		ID:        id,
		UserID:    userID,
		Name:      id,
		SortOrder: 0,
		CreatedAt: now,
		UpdatedAt: now,
	}
	if err := database.DB.Create(&project).Error; err != nil {
		t.Fatalf("create project: %v", err)
	}
	return project
}

func createKnowledgeDocumentViaAPI(t *testing.T, router *gin.Engine, projectID, userID, jsonBody string) {
	t.Helper()
	req := httptest.NewRequest(http.MethodPost, "/api/projects/"+projectID+"/documents", strings.NewReader(jsonBody))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-User-ID", userID)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)
	if recorder.Code != http.StatusCreated {
		t.Fatalf("unexpected create document status %d: %s", recorder.Code, recorder.Body.String())
	}
}

func createKnowledgeDocumentForTest(t *testing.T, projectID, userID, title, content string) models.KnowledgeDocument {
	t.Helper()
	now := time.Now()
	doc := models.KnowledgeDocument{
		ID:        title + "-id",
		UserID:    userID,
		ProjectID: projectID,
		Type:      "source",
		Title:     title,
		Summary:   summarizeKnowledgeContent(content),
		TagsJSON:  knowledgeJSON(extractKnowledgeTags(title + "\n" + content)),
		Content:   content,
		CreatedAt: now,
		UpdatedAt: now,
	}
	if err := database.DB.Create(&doc).Error; err != nil {
		t.Fatalf("create document: %v", err)
	}
	return doc
}
