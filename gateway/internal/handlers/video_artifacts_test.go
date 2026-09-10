package handlers

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
)

func TestVideoArtifactsSurvivePersistenceHistoryAndRunRecovery(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatal(err)
	}
	conv := models.Conversation{ID: "typed-video", UserID: "0", AgentID: "super_chat"}
	if err := database.DB.Create(&conv).Error; err != nil {
		t.Fatal(err)
	}
	const url = "/static/generated/aigc/spark-video-typed.mp4"
	response := &bridge.ChatResponse{Response: "视频已完成，没有 Markdown 链接。", RunID: "run-typed-video",
		Artifacts: []bridge.ChatArtifact{{Type: "video", ItemID: url, URL: url, MimeType: "video/mp4",
			Metadata: map[string]interface{}{"video": map[string]interface{}{"width": float64(480)}}}}}
	message := buildAssistantMessage(conv.ID, "0", response)
	if err := database.DB.Create(message).Error; err != nil {
		t.Fatal(err)
	}
	recovered, err := storedRunRecord(response.RunID, "0")
	if err != nil {
		t.Fatal(err)
	}
	if len(recovered.Artifacts) != 1 || recovered.Artifacts[0].URL != url || recovered.Artifacts[0].Type != "video" {
		t.Fatalf("lost video in run recovery: %#v", recovered.Artifacts)
	}
	if _, err := storedRunRecord(response.RunID, "other-account"); err == nil {
		t.Fatal("video run leaked across accounts")
	}
	router := gin.New()
	router.GET("/api/conversations/:id", NewConversationHandler().Get)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/api/conversations/typed-video", nil))
	if recorder.Code != http.StatusOK {
		t.Fatalf("history: %d %s", recorder.Code, recorder.Body.String())
	}
	var history struct {
		Messages []struct {
			Artifacts string `json:"artifacts"`
		} `json:"messages"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &history); err != nil {
		t.Fatal(err)
	}
	if len(history.Messages) != 1 {
		t.Fatalf("unexpected history: %s", recorder.Body.String())
	}
	var artifacts []bridge.ChatArtifact
	if err := json.Unmarshal([]byte(history.Messages[0].Artifacts), &artifacts); err != nil {
		t.Fatal(err)
	}
	if len(artifacts) != 1 || artifacts[0].URL != url || artifacts[0].MimeType != "video/mp4" {
		t.Fatalf("lost typed video in history: %#v", artifacts)
	}
}
