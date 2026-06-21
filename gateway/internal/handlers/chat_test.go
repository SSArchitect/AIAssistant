package handlers

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"net"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
)

func TestChatSyncsSettingsBeforeAgentRequest(t *testing.T) {
	gin.SetMode(gin.TestMode)

	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}
	if err := database.DB.Save(&models.Setting{Key: "llm.minimax.api_key", Value: "sk-test"}).Error; err != nil {
		t.Fatalf("save setting: %v", err)
	}
	conv := models.Conversation{
		ID:        "conv-sync-chat",
		Title:     "New Conversation",
		CreatedAt: time.Now(),
		UpdatedAt: time.Now(),
	}
	if err := database.DB.Create(&conv).Error; err != nil {
		t.Fatalf("create conversation: %v", err)
	}

	synced := false
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/agent/config":
			var payload struct {
				Settings map[string]string `json:"settings"`
			}
			if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
				t.Fatalf("decode config payload: %v", err)
			}
			if payload.Settings["llm.minimax.api_key"] != "sk-test" {
				t.Fatalf("unexpected synced key: %#v", payload.Settings)
			}
			synced = true
			_, _ = w.Write([]byte(`{"status":"ok"}`))
		case "/agent/chat":
			if !synced {
				t.Fatal("chat reached agent before config sync")
			}
			_, _ = w.Write([]byte(`{
				"conversation_id": "conv-sync-chat",
				"response": "ok",
				"skills_used": [],
				"citations": [],
				"model_used": "test-model",
				"tokens_used": {},
				"agent_id": "super_chat",
				"runtime": "self",
				"run_id": "run_sync",
				"events": [
					{
						"id": "evt_sync",
						"run_id": "run_sync",
						"type": "run.completed",
						"status": "completed",
						"title": "Run completed",
						"payload": {},
						"created_at": "2026-06-18T00:00:00Z"
					}
				]
			}`))
		default:
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
	}))
	defer agentServer.Close()

	client := bridge.NewAgentClient(agentServer.URL, time.Second)
	router := gin.New()
	handler := NewChatHandler(client, NewConfigSyncer(client))
	router.POST("/api/chat", handler.Chat)

	body := bytes.NewBufferString(`{
		"conversation_id": "conv-sync-chat",
		"query": "画一张图",
		"stream": false,
		"agent_id": "super_chat"
	}`)
	req := httptest.NewRequest(http.MethodPost, "/api/chat", body)
	req.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()

	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	if !synced {
		t.Fatal("expected config sync before chat")
	}

	var messages []models.Message
	if err := database.DB.Where("conversation_id = ?", conv.ID).Order("created_at asc").Find(&messages).Error; err != nil {
		t.Fatalf("load messages: %v", err)
	}
	if len(messages) != 2 {
		t.Fatalf("expected user and assistant messages, got %#v", messages)
	}
	if messages[1].RunID != "run_sync" || messages[1].Runtime != "self" {
		t.Fatalf("expected assistant run metadata to persist, got run=%q runtime=%q", messages[1].RunID, messages[1].Runtime)
	}
	if !strings.Contains(messages[1].TraceEvents, "run.completed") {
		t.Fatalf("expected trace events to persist, got %q", messages[1].TraceEvents)
	}
}

func TestChatSendsPersistedConversationContextToAgent(t *testing.T) {
	gin.SetMode(gin.TestMode)

	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}
	conv := models.Conversation{
		ID:        "conv-context-chat",
		Title:     "MiniMax progress",
		CreatedAt: time.Now().Add(-10 * time.Minute),
		UpdatedAt: time.Now().Add(-5 * time.Minute),
	}
	if err := database.DB.Create(&conv).Error; err != nil {
		t.Fatalf("create conversation: %v", err)
	}
	messages := []models.Message{
		{
			ConversationID: conv.ID,
			Role:           "user",
			Content:        "帮我看看minimax有什么进展",
			CreatedAt:      time.Now().Add(-4 * time.Minute),
		},
		{
			ConversationID: conv.ID,
			Role:           "assistant",
			Content:        "MiniMax 最近发布了图像和语音相关能力。",
			CreatedAt:      time.Now().Add(-3 * time.Minute),
		},
	}
	if err := database.DB.Create(&messages).Error; err != nil {
		t.Fatalf("create messages: %v", err)
	}

	var captured bridge.ChatRequest
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/agent/chat" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		if err := json.NewDecoder(r.Body).Decode(&captured); err != nil {
			t.Fatalf("decode agent request: %v", err)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"conversation_id": "conv-context-chat",
			"response": "ok",
			"skills_used": [],
			"citations": [],
			"model_used": "test-model",
			"tokens_used": {},
			"agent_id": "super_chat",
			"runtime": "self",
			"run_id": "run_context"
		}`))
	}))
	defer agentServer.Close()

	router := gin.New()
	handler := NewChatHandler(bridge.NewAgentClient(agentServer.URL, time.Second))
	router.POST("/api/chat", handler.Chat)

	currentQuery := "好，帮我生成一个图片吧，总结给我"
	body := bytes.NewBufferString(`{
		"conversation_id": "conv-context-chat",
		"user_id": "42",
		"query": "` + currentQuery + `",
		"stream": false,
		"agent_id": "super_chat",
		"context_blocks": ["Uploaded note: use a clean blue visual style"],
		"agent_input": {
			"protocol_version": "agent_input.v1",
			"source_agent_id": "web",
			"target_agent_id": "super_chat",
			"current_request": "` + currentQuery + `"
		}
	}`)
	req := httptest.NewRequest(http.MethodPost, "/api/chat", body)
	req.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()

	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	if captured.UserID != "42" {
		t.Fatalf("expected user_id to be forwarded, got %q", captured.UserID)
	}
	if len(captured.ContextBlocks) != 2 {
		t.Fatalf("expected persisted history plus caller context, got %#v", captured.ContextBlocks)
	}
	historyBlock := captured.ContextBlocks[0]
	if !strings.Contains(historyBlock, "Persisted conversation history") {
		t.Fatalf("missing history header: %q", historyBlock)
	}
	if !strings.Contains(historyBlock, "user: 帮我看看minimax有什么进展") {
		t.Fatalf("missing user history: %q", historyBlock)
	}
	if !strings.Contains(historyBlock, "assistant: MiniMax 最近发布了图像和语音相关能力。") {
		t.Fatalf("missing assistant history: %q", historyBlock)
	}
	if strings.Contains(historyBlock, currentQuery) {
		t.Fatalf("history block should not duplicate current query: %q", historyBlock)
	}
	if captured.ContextBlocks[1] != "Uploaded note: use a clean blue visual style" {
		t.Fatalf("caller context was not preserved: %#v", captured.ContextBlocks)
	}
	if captured.AgentInput["protocol_version"] != "agent_input.v1" {
		t.Fatalf("agent input packet was not forwarded: %#v", captured.AgentInput)
	}
	if captured.AgentInput["target_agent_id"] != "super_chat" {
		t.Fatalf("unexpected agent input target: %#v", captured.AgentInput)
	}
}

func TestNormalizedUserIDDefaultsToZero(t *testing.T) {
	if got := normalizedUserID(""); got != "0" {
		t.Fatalf("expected empty user id to default to 0, got %q", got)
	}
	if got := normalizedUserID(" 42 "); got != "42" {
		t.Fatalf("expected user id to be trimmed, got %q", got)
	}
}

func TestPersistedConversationContextOrdersMixedTimestampFormats(t *testing.T) {
	gin.SetMode(gin.TestMode)

	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}
	conv := models.Conversation{
		ID:        "conv-mixed-time-context",
		Title:     "Mixed timestamps",
		CreatedAt: time.Now().Add(-10 * time.Minute),
		UpdatedAt: time.Now(),
	}
	if err := database.DB.Create(&conv).Error; err != nil {
		t.Fatalf("create conversation: %v", err)
	}

	rows := []struct {
		role      string
		content   string
		createdAt string
	}{
		{"user", "first question", "2026-06-19 19:25:17.782336+08:00"},
		{"assistant", "first research answer", "2026-06-19T19:31:04.009653+08:00"},
		{"user", "latest image request", "2026-06-19 21:39:21.694492+08:00"},
		{"assistant", "latest image answer", "2026-06-19 21:40:50.640082+08:00"},
	}
	for _, row := range rows {
		if err := database.DB.Exec(
			"insert into messages (conversation_id, role, content, created_at) values (?, ?, ?, ?)",
			conv.ID,
			row.role,
			row.content,
			row.createdAt,
		).Error; err != nil {
			t.Fatalf("insert mixed timestamp message: %v", err)
		}
	}

	handler := NewChatHandler(bridge.NewAgentClient("http://agent.invalid", time.Second))
	blocks := handler.persistedConversationContext(conv.ID)
	if len(blocks) != 1 {
		t.Fatalf("expected one context block, got %#v", blocks)
	}

	firstResearchIndex := strings.Index(blocks[0], "assistant: first research answer")
	latestImageIndex := strings.Index(blocks[0], "user: latest image request")
	if firstResearchIndex < 0 || latestImageIndex < 0 {
		t.Fatalf("missing expected messages in context block: %q", blocks[0])
	}
	if firstResearchIndex > latestImageIndex {
		t.Fatalf("mixed timestamp formats were sorted incorrectly: %q", blocks[0])
	}
}

func TestGenerateImageSyncsSettingsBeforeAgentRequest(t *testing.T) {
	gin.SetMode(gin.TestMode)

	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}
	if err := database.DB.Save(&models.Setting{Key: "llm.minimax.api_key", Value: "sk-test"}).Error; err != nil {
		t.Fatalf("save setting: %v", err)
	}

	synced := false
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/agent/config":
			var payload struct {
				Settings map[string]string `json:"settings"`
			}
			if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
				t.Fatalf("decode config payload: %v", err)
			}
			if payload.Settings["llm.minimax.api_key"] != "sk-test" {
				t.Fatalf("unexpected synced key: %#v", payload.Settings)
			}
			synced = true
			_, _ = w.Write([]byte(`{"status":"ok"}`))
		case "/agent/aigc/image":
			if !synced {
				t.Fatal("image reached agent before config sync")
			}
			_, _ = w.Write([]byte(`{
				"id": "img_sync",
				"provider": "minimax",
				"model": "image-01",
				"prompt": "a clean product shot",
				"aspect_ratio": "1:1",
				"response_format": "url",
				"images": [],
				"metadata": {}
			}`))
		default:
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
	}))
	defer agentServer.Close()

	client := bridge.NewAgentClient(agentServer.URL, time.Second)
	router := gin.New()
	handler := NewChatHandler(client, NewConfigSyncer(client))
	router.POST("/api/aigc/image", handler.GenerateImage)

	body := bytes.NewBufferString(`{"prompt":"a clean product shot"}`)
	req := httptest.NewRequest(http.MethodPost, "/api/aigc/image", body)
	req.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()

	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	if !synced {
		t.Fatal("expected config sync before image generation")
	}
}

func TestStreamChatPersistsAssistantError(t *testing.T) {
	gin.SetMode(gin.TestMode)

	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/agent/chat/stream" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = w.Write([]byte("event: meta\ndata: {\"run_id\":\"run_fail\"}\n\n"))
		_, _ = w.Write([]byte("event: trace\ndata: {\"id\":\"evt_1\",\"run_id\":\"run_fail\",\"type\":\"run.failed\",\"status\":\"error\",\"title\":\"Run failed\",\"payload\":{\"error_type\":\"model_error\",\"error_message\":\"Connection error.\"},\"created_at\":\"2026-06-18T00:00:00Z\"}\n\n"))
		_, _ = w.Write([]byte("event: error\ndata: {\"run_id\":\"run_fail\",\"error\":\"Connection error.\"}\n\n"))
	}))
	defer agentServer.Close()

	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	conv := models.Conversation{
		ID:        "conv-stream-error",
		Title:     "New Conversation",
		CreatedAt: time.Now(),
		UpdatedAt: time.Now(),
	}
	if err := database.DB.Create(&conv).Error; err != nil {
		t.Fatalf("create conversation: %v", err)
	}

	router := gin.New()
	handler := NewChatHandler(bridge.NewAgentClient(agentServer.URL, time.Second))
	router.POST("/api/chat", handler.Chat)

	body := bytes.NewBufferString(`{
		"conversation_id": "conv-stream-error",
		"query": "summarize this document",
		"stream": true,
		"agent_id": "super_chat"
	}`)
	req := httptest.NewRequest(http.MethodPost, "/api/chat", body)
	req.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()

	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	if !strings.Contains(recorder.Body.String(), "event: error") {
		t.Fatalf("expected error event to be proxied, got %s", recorder.Body.String())
	}

	var messages []models.Message
	if err := database.DB.Where("conversation_id = ?", conv.ID).Order("created_at asc").Find(&messages).Error; err != nil {
		t.Fatalf("load messages: %v", err)
	}
	if len(messages) != 2 {
		t.Fatalf("expected user and assistant messages, got %#v", messages)
	}
	if messages[0].Role != "user" || messages[0].Content != "summarize this document" {
		t.Fatalf("unexpected user message: %#v", messages[0])
	}
	if messages[1].Role != "assistant" || messages[1].Content != "Connection error." {
		t.Fatalf("unexpected assistant message: %#v", messages[1])
	}
	if messages[1].ErrorType != "model_error" {
		t.Fatalf("unexpected error type: %q", messages[1].ErrorType)
	}
	if messages[1].RunID != "run_fail" {
		t.Fatalf("expected error run id to persist, got %q", messages[1].RunID)
	}
	if !strings.Contains(messages[1].TraceEvents, "run.failed") {
		t.Fatalf("expected error trace events to persist, got %q", messages[1].TraceEvents)
	}

	var savedConv models.Conversation
	if err := database.DB.First(&savedConv, "id = ?", conv.ID).Error; err != nil {
		t.Fatalf("load conversation: %v", err)
	}
	if savedConv.Title != "summarize this document" {
		t.Fatalf("unexpected conversation title: %q", savedConv.Title)
	}
}

func TestStreamChatRecoversCompletedRunWithoutResponseEvent(t *testing.T) {
	gin.SetMode(gin.TestMode)

	recoveredRun := false
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/agent/chat/stream":
			w.Header().Set("Content-Type", "text/event-stream")
			_, _ = w.Write([]byte("event: meta\ndata: {\"run_id\":\"run_recover\"}\n\n"))
			_, _ = w.Write([]byte("event: trace\ndata: {\"id\":\"evt_1\",\"run_id\":\"run_recover\",\"type\":\"run.completed\",\"status\":\"success\",\"title\":\"Run completed\",\"payload\":{},\"created_at\":\"2026-06-18T00:00:00Z\"}\n\n"))
			_, _ = w.Write([]byte("event: done\ndata: {\"run_id\":\"run_recover\"}\n\n"))
		case "/agent/runs/run_recover":
			recoveredRun = true
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{
				"run_id": "run_recover",
				"conversation_id": "conv-stream-recover",
				"agent_id": "super_chat",
				"runtime": "self",
				"status": "completed",
				"input": "generate timeline image",
				"output": "recovered image result",
				"model_used": "test-model",
				"tokens_used": {"total": 7},
				"skills_used": ["image_generation"],
				"started_at": "2026-06-18T00:00:00Z",
				"completed_at": "2026-06-18T00:00:01Z",
				"events": []
			}`))
		default:
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
	}))
	defer agentServer.Close()

	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	conv := models.Conversation{
		ID:        "conv-stream-recover",
		Title:     "New Conversation",
		CreatedAt: time.Now(),
		UpdatedAt: time.Now(),
	}
	if err := database.DB.Create(&conv).Error; err != nil {
		t.Fatalf("create conversation: %v", err)
	}

	router := gin.New()
	handler := NewChatHandler(bridge.NewAgentClient(agentServer.URL, time.Second))
	router.POST("/api/chat", handler.Chat)

	body := bytes.NewBufferString(`{
		"conversation_id": "conv-stream-recover",
		"query": "generate timeline image",
		"stream": true,
		"agent_id": "super_chat"
	}`)
	req := httptest.NewRequest(http.MethodPost, "/api/chat", body)
	req.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()

	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	if !recoveredRun {
		t.Fatal("expected gateway to recover completed run output")
	}

	var messages []models.Message
	if err := database.DB.Where("conversation_id = ?", conv.ID).Order("created_at asc").Find(&messages).Error; err != nil {
		t.Fatalf("load messages: %v", err)
	}
	if len(messages) != 2 {
		t.Fatalf("expected user and assistant messages, got %#v", messages)
	}
	if messages[1].Role != "assistant" || messages[1].Content != "recovered image result" {
		t.Fatalf("unexpected assistant message: %#v", messages[1])
	}
	if messages[1].ModelUsed != "test-model" {
		t.Fatalf("unexpected model: %q", messages[1].ModelUsed)
	}
	if messages[1].RunID != "run_recover" || messages[1].Runtime != "self" {
		t.Fatalf("expected recovered run metadata to persist, got run=%q runtime=%q", messages[1].RunID, messages[1].Runtime)
	}
	if !strings.Contains(messages[1].SkillsUsed, "image_generation") {
		t.Fatalf("unexpected skills: %q", messages[1].SkillsUsed)
	}
}

func TestStreamChatPersistsFinalResponseAfterClientDisconnect(t *testing.T) {
	gin.SetMode(gin.TestMode)

	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/agent/chat/stream" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = w.Write([]byte("event: meta\ndata: {\"run_id\":\"run_done\"}\n\n"))
		_, _ = w.Write([]byte("event: response\ndata: {\"conversation_id\":\"conv-stream-disconnect\",\"response\":\"final summary\",\"skills_used\":[],\"citations\":[],\"model_used\":\"test-model\",\"tokens_used\":{},\"agent_id\":\"super_chat\",\"runtime\":\"self\",\"run_id\":\"run_done\"}\n\n"))
		_, _ = w.Write([]byte("event: done\ndata: {\"run_id\":\"run_done\"}\n\n"))
	}))
	defer agentServer.Close()

	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	conv := models.Conversation{
		ID:        "conv-stream-disconnect",
		Title:     "New Conversation",
		CreatedAt: time.Now(),
		UpdatedAt: time.Now(),
	}
	if err := database.DB.Create(&conv).Error; err != nil {
		t.Fatalf("create conversation: %v", err)
	}

	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	c.Writer = newFailingStreamWriter(1)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/chat", nil)

	handler := NewChatHandler(bridge.NewAgentClient(agentServer.URL, time.Second))
	handler.streamChat(
		c,
		conv,
		ChatRequestBody{
			ConversationID: conv.ID,
			Query:          "summarize with disconnect",
			Stream:         true,
			AgentID:        "super_chat",
		},
		bridge.ChatRequest{
			ConversationID: conv.ID,
			Message:        "summarize with disconnect",
			Stream:         true,
			AgentID:        "super_chat",
		},
	)

	var messages []models.Message
	if err := database.DB.Where("conversation_id = ?", conv.ID).Order("created_at asc").Find(&messages).Error; err != nil {
		t.Fatalf("load messages: %v", err)
	}
	if len(messages) != 1 {
		t.Fatalf("expected assistant message, got %#v", messages)
	}
	if messages[0].Role != "assistant" || messages[0].Content != "final summary" {
		t.Fatalf("unexpected assistant message: %#v", messages[0])
	}
	if messages[0].ModelUsed != "test-model" {
		t.Fatalf("unexpected model: %q", messages[0].ModelUsed)
	}
	if messages[0].RunID != "run_done" || messages[0].Runtime != "self" {
		t.Fatalf("expected final run metadata to persist, got run=%q runtime=%q", messages[0].RunID, messages[0].Runtime)
	}
}

type failingStreamWriter struct {
	header              http.Header
	body                bytes.Buffer
	status              int
	writes              int
	maxSuccessfulWrites int
}

func newFailingStreamWriter(maxSuccessfulWrites int) *failingStreamWriter {
	return &failingStreamWriter{
		header:              make(http.Header),
		maxSuccessfulWrites: maxSuccessfulWrites,
	}
}

func (w *failingStreamWriter) Header() http.Header {
	return w.header
}

func (w *failingStreamWriter) WriteHeader(code int) {
	w.status = code
}

func (w *failingStreamWriter) WriteHeaderNow() {
	if w.status == 0 {
		w.status = http.StatusOK
	}
}

func (w *failingStreamWriter) Write(data []byte) (int, error) {
	w.WriteHeaderNow()
	w.writes++
	if w.writes > w.maxSuccessfulWrites {
		return 0, errors.New("client disconnected")
	}
	return w.body.Write(data)
}

func (w *failingStreamWriter) WriteString(data string) (int, error) {
	return w.Write([]byte(data))
}

func (w *failingStreamWriter) Status() int {
	return w.status
}

func (w *failingStreamWriter) Size() int {
	return w.body.Len()
}

func (w *failingStreamWriter) Written() bool {
	return w.status != 0
}

func (w *failingStreamWriter) Flush() {}

func (w *failingStreamWriter) Pusher() http.Pusher {
	return nil
}

func (w *failingStreamWriter) CloseNotify() <-chan bool {
	ch := make(chan bool)
	return ch
}

func (w *failingStreamWriter) Hijack() (net.Conn, *bufio.ReadWriter, error) {
	return nil, nil, errors.New("hijack unsupported")
}
