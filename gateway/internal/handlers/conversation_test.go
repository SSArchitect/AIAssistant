package handlers

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
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
