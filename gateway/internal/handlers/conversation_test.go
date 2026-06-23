package handlers

import (
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

func TestConversationListIsScopedByUserID(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	conversations := []models.Conversation{
		{ID: "conv-user-a", UserID: "a", Title: "A", CreatedAt: time.Now(), UpdatedAt: time.Now()},
		{ID: "conv-user-b", UserID: "b", Title: "B", CreatedAt: time.Now(), UpdatedAt: time.Now()},
	}
	if err := database.DB.Create(&conversations).Error; err != nil {
		t.Fatalf("create conversations: %v", err)
	}

	router := gin.New()
	handler := NewConversationHandler()
	router.GET("/api/conversations", handler.List)

	req := httptest.NewRequest(http.MethodGet, "/api/conversations", nil)
	req.Header.Set("X-User-ID", "a")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	var payload struct {
		Conversations []models.Conversation `json:"conversations"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if len(payload.Conversations) != 1 || payload.Conversations[0].ID != "conv-user-a" {
		t.Fatalf("expected only user a conversation, got %#v", payload.Conversations)
	}
}

func TestConversationGetOmitsTraceEventsByDefault(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	conv := models.Conversation{
		ID:        "conv-trace-light",
		UserID:    "user-a",
		Title:     "Trace Light",
		CreatedAt: time.Now(),
		UpdatedAt: time.Now(),
	}
	if err := database.DB.Create(&conv).Error; err != nil {
		t.Fatalf("create conversation: %v", err)
	}
	message := models.Message{
		ConversationID: conv.ID,
		UserID:         conv.UserID,
		Role:           "assistant",
		Content:        "done",
		RunID:          "run-heavy",
		TraceEvents:    `[{"type":"run.completed","payload":{"prompt":"very large"}}]`,
		CreatedAt:      time.Now(),
	}
	if err := database.DB.Create(&message).Error; err != nil {
		t.Fatalf("create message: %v", err)
	}

	router := gin.New()
	handler := NewConversationHandler()
	router.GET("/api/conversations/:id", handler.Get)

	req := httptest.NewRequest(http.MethodGet, "/api/conversations/"+conv.ID, nil)
	req.Header.Set("X-User-ID", conv.UserID)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	if strings.Contains(recorder.Body.String(), "trace_events") {
		t.Fatalf("expected trace events to be omitted by default, got %s", recorder.Body.String())
	}
	if !strings.Contains(recorder.Body.String(), `"run_id":"run-heavy"`) {
		t.Fatalf("expected run id to remain available, got %s", recorder.Body.String())
	}
}

func TestConversationGetCanIncludeTraceEvents(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	conv := models.Conversation{
		ID:        "conv-trace-full",
		UserID:    "user-a",
		Title:     "Trace Full",
		CreatedAt: time.Now(),
		UpdatedAt: time.Now(),
	}
	if err := database.DB.Create(&conv).Error; err != nil {
		t.Fatalf("create conversation: %v", err)
	}
	message := models.Message{
		ConversationID: conv.ID,
		UserID:         conv.UserID,
		Role:           "assistant",
		Content:        "done",
		RunID:          "run-full",
		TraceEvents:    `[{"type":"run.completed","payload":{"prompt":"large"}}]`,
		CreatedAt:      time.Now(),
	}
	if err := database.DB.Create(&message).Error; err != nil {
		t.Fatalf("create message: %v", err)
	}

	router := gin.New()
	handler := NewConversationHandler()
	router.GET("/api/conversations/:id", handler.Get)

	req := httptest.NewRequest(http.MethodGet, "/api/conversations/"+conv.ID+"?include_trace=true", nil)
	req.Header.Set("X-User-ID", conv.UserID)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	if !strings.Contains(recorder.Body.String(), `"trace_events"`) {
		t.Fatalf("expected trace events when requested, got %s", recorder.Body.String())
	}
}

func TestConversationCreateSessionUserOverridesBodyUserID(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}
	token := "session-token-conversation"
	if err := database.DB.Create(&models.AccountSession{
		TokenHash:  accountSessionTokenHash(token),
		UserID:     "session-user",
		CreatedAt:  time.Now(),
		LastUsedAt: time.Now(),
	}).Error; err != nil {
		t.Fatalf("create account session: %v", err)
	}

	router := gin.New()
	handler := NewConversationHandler()
	router.POST("/api/conversations", handler.Create)

	req := httptest.NewRequest(http.MethodPost, "/api/conversations", strings.NewReader(`{"user_id":"attacker-user"}`))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Account-Session", token)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusCreated {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	var conv models.Conversation
	if err := json.Unmarshal(recorder.Body.Bytes(), &conv); err != nil {
		t.Fatalf("decode conversation: %v", err)
	}
	if conv.UserID != "session-user" {
		t.Fatalf("expected session user, got %q", conv.UserID)
	}
}

func TestConversationCreatePersistsAgentID(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	router := gin.New()
	handler := NewConversationHandler()
	router.POST("/api/conversations", handler.Create)

	req := httptest.NewRequest(
		http.MethodPost,
		"/api/conversations",
		strings.NewReader(`{"user_id":"user-a","agent_id":"deep_research_v1"}`),
	)
	req.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusCreated {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	var conv models.Conversation
	if err := json.Unmarshal(recorder.Body.Bytes(), &conv); err != nil {
		t.Fatalf("decode conversation: %v", err)
	}
	if conv.AgentID != "deep_research_v1" {
		t.Fatalf("expected conversation agent to persist, got %q", conv.AgentID)
	}
}

func TestConversationCreateDefaultsAgentIDToSuperChat(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	router := gin.New()
	handler := NewConversationHandler()
	router.POST("/api/conversations", handler.Create)

	req := httptest.NewRequest(
		http.MethodPost,
		"/api/conversations",
		strings.NewReader(`{"user_id":"user-a"}`),
	)
	req.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusCreated {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	var conv models.Conversation
	if err := json.Unmarshal(recorder.Body.Bytes(), &conv); err != nil {
		t.Fatalf("decode conversation: %v", err)
	}
	if conv.AgentID != "super_chat" {
		t.Fatalf("expected default conversation agent super_chat, got %q", conv.AgentID)
	}
}
