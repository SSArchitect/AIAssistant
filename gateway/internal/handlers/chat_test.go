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

func TestCompactTraceEventsKeepsTimelineDetailsWithoutLargePayloads(t *testing.T) {
	largeContent := strings.Repeat("large-context ", 1000)
	resultPreview := `{"success":true,"data":{"query":"2026 movies","results":[{"title":"A useful result","url":"https://example.com/a","snippet":"` + largeContent + `"},{"title":"Second result","url":"https://example.com/b"}]},"display_text":"` + largeContent + `"}`
	events := []bridge.RunEvent{
		{
			ID:     "evt_tool",
			RunID:  "run_summary",
			Type:   "tool.completed",
			Status: "completed",
			Title:  "Tool search completed",
			Payload: map[string]interface{}{
				"arguments":      map[string]interface{}{"query": "2026 movies", "irrelevant": largeContent},
				"result_preview": resultPreview,
				"messages":       []interface{}{largeContent},
			},
		},
		{
			ID:     "evt_done",
			RunID:  "run_summary",
			Type:   "run.completed",
			Status: "completed",
			Title:  "Run completed",
			Payload: map[string]interface{}{
				"model_used":  "test-model",
				"skills_used": []interface{}{"search"},
			},
		},
	}

	summary := compactTraceEvents(events)
	summaryJSON, err := json.Marshal(summary)
	if err != nil {
		t.Fatalf("marshal summary: %v", err)
	}
	text := string(summaryJSON)
	if len(text) >= len(resultPreview) {
		t.Fatalf("expected compact summary to be smaller than raw preview")
	}
	for _, want := range []string{"tool.completed", "run.completed", "2026 movies", "A useful result", "https://example.com/a"} {
		if !strings.Contains(text, want) {
			t.Fatalf("expected summary to contain %q, got %s", want, text)
		}
	}
	if strings.Contains(text, `"messages"`) {
		t.Fatalf("expected large messages payload to be removed, got %s", text)
	}
	if len(text) > 2200 {
		t.Fatalf("expected compact summary to stay small, got %d bytes: %s", len(text), text)
	}
}

func TestStoredRunStatusPreservesPartialRun(t *testing.T) {
	events := []bridge.RunEvent{
		{
			ID:      "evt_started",
			RunID:   "run_partial",
			Type:    "run.started",
			Status:  "running",
			Title:   "Run started",
			Payload: map[string]interface{}{},
		},
		{
			ID:      "evt_partial",
			RunID:   "run_partial",
			Type:    "run.partial",
			Status:  "partial",
			Title:   "Run partial summary",
			Payload: map[string]interface{}{"response_status": "partial_summary"},
		},
	}

	if got := storedRunStatus(events, ""); got != "partial" {
		t.Fatalf("expected partial status, got %q", got)
	}
	events = append(
		events[:1],
		append(
			[]bridge.RunEvent{
				{
					ID:      "evt_model_failed",
					RunID:   "run_partial",
					Type:    "model.failed",
					Status:  "error",
					Title:   "Model call failed",
					Payload: map[string]interface{}{"error_type": "model_error"},
				},
			},
			events[1:]...,
		)...,
	)
	if got := storedRunStatus(events, ""); got != "partial" {
		t.Fatalf("expected terminal run.partial to win over model.failed, got %q", got)
	}
	if got := storedRunStatus(events, "model_error"); got != "failed" {
		t.Fatalf("expected explicit error_type to win, got %q", got)
	}
}

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
				"tokens_used": {"input": 5, "output": 2, "input_cached": 1},
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
	var usage models.TokenUsage
	if err := database.DB.First(&usage, "message_id = ?", messages[1].ID).Error; err != nil {
		t.Fatalf("load token usage: %v", err)
	}
	if usage.UserID != models.DefaultAccountID || usage.AgentID != "super_chat" || usage.InputTokens != 5 || usage.OutputTokens != 2 || usage.TotalTokens != 7 || usage.CachedInputTokens != 1 {
		t.Fatalf("unexpected token usage: %#v", usage)
	}
}

func TestChatRegenerateSkipsPersistingDuplicateUserMessage(t *testing.T) {
	gin.SetMode(gin.TestMode)

	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}
	conv := models.Conversation{
		ID:        "conv-regenerate-chat",
		Title:     "Existing Conversation",
		CreatedAt: time.Now().Add(-10 * time.Minute),
		UpdatedAt: time.Now().Add(-5 * time.Minute),
	}
	if err := database.DB.Create(&conv).Error; err != nil {
		t.Fatalf("create conversation: %v", err)
	}
	existingMessages := []models.Message{
		{
			ConversationID: conv.ID,
			Role:           "user",
			Content:        "explain this again",
			CreatedAt:      time.Now().Add(-2 * time.Minute),
		},
		{
			ConversationID: conv.ID,
			Role:           "assistant",
			Content:        "old answer",
			CreatedAt:      time.Now().Add(-1 * time.Minute),
		},
	}
	if err := database.DB.Create(&existingMessages).Error; err != nil {
		t.Fatalf("create messages: %v", err)
	}

	sawRegenerateContext := false
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/agent/chat" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		var payload bridge.ChatRequest
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Fatalf("decode chat payload: %v", err)
		}
		if payload.Message != "explain this again" {
			t.Fatalf("unexpected message: %q", payload.Message)
		}
		for _, block := range payload.ContextBlocks {
			if strings.Contains(block, "Regeneration request") {
				sawRegenerateContext = true
			}
		}
		_, _ = w.Write([]byte(`{
			"conversation_id": "conv-regenerate-chat",
			"response": "fresh answer",
			"skills_used": [],
			"citations": [],
			"model_used": "test-model",
			"tokens_used": {},
			"agent_id": "super_chat",
			"runtime": "self",
			"run_id": "run_regenerate",
			"events": []
		}`))
	}))
	defer agentServer.Close()

	router := gin.New()
	handler := NewChatHandler(bridge.NewAgentClient(agentServer.URL, time.Second))
	router.POST("/api/chat", handler.Chat)

	body := bytes.NewBufferString(`{
		"conversation_id": "conv-regenerate-chat",
		"query": "explain this again",
		"stream": false,
		"agent_id": "super_chat",
		"regenerate": true
	}`)
	req := httptest.NewRequest(http.MethodPost, "/api/chat", body)
	req.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()

	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	if !sawRegenerateContext {
		t.Fatal("expected regenerate context block to reach agent")
	}

	var messages []models.Message
	if err := database.DB.Where("conversation_id = ?", conv.ID).Order("created_at asc").Find(&messages).Error; err != nil {
		t.Fatalf("load messages: %v", err)
	}
	if len(messages) != 3 {
		t.Fatalf("expected original user plus two assistant messages, got %#v", messages)
	}
	userCount := 0
	for _, message := range messages {
		if message.Role == "user" {
			userCount += 1
		}
	}
	if userCount != 1 {
		t.Fatalf("expected regenerate to avoid duplicate user messages, got %d", userCount)
	}
	if messages[2].Role != "assistant" || messages[2].Content != "fresh answer" {
		t.Fatalf("unexpected regenerated assistant message: %#v", messages[2])
	}
}

func TestChatSendsPersistedConversationContextToAgent(t *testing.T) {
	gin.SetMode(gin.TestMode)

	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}
	conv := models.Conversation{
		ID:        "conv-context-chat",
		UserID:    "42",
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
			UserID:         "42",
			Role:           "user",
			Content:        "帮我看看minimax有什么进展",
			CreatedAt:      time.Now().Add(-4 * time.Minute),
		},
		{
			ConversationID: conv.ID,
			UserID:         "42",
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
		"drive_context": {
			"current_folder_id": "folder-root",
			"current_path": "/我的网盘",
			"items": [
				{"id": "file-1", "type": "file", "name": "Notes.md", "path": "/我的网盘/Notes.md", "summary": "lightweight summary"}
			]
		},
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
	if captured.DriveContext == nil || captured.DriveContext.CurrentPath != "/我的网盘" {
		t.Fatalf("drive context was not forwarded: %#v", captured.DriveContext)
	}
	if len(captured.DriveContext.Items) != 1 || captured.DriveContext.Items[0].Summary != "lightweight summary" {
		t.Fatalf("drive context items were not forwarded: %#v", captured.DriveContext.Items)
	}
	if captured.AgentInput["protocol_version"] != "agent_input.v1" {
		t.Fatalf("agent input packet was not forwarded: %#v", captured.AgentInput)
	}
	if captured.AgentInput["target_agent_id"] != "super_chat" {
		t.Fatalf("unexpected agent input target: %#v", captured.AgentInput)
	}
}

func TestChatSessionUserOverridesBodyUserID(t *testing.T) {
	gin.SetMode(gin.TestMode)

	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}
	token := "session-token-chat"
	if err := database.DB.Create(&models.AccountSession{
		TokenHash:  accountSessionTokenHash(token),
		UserID:     "session-user",
		CreatedAt:  time.Now(),
		LastUsedAt: time.Now(),
	}).Error; err != nil {
		t.Fatalf("create account session: %v", err)
	}
	if err := database.DB.Create(&models.Conversation{
		ID:        "conv-session-chat",
		UserID:    "session-user",
		Title:     "Session scoped",
		CreatedAt: time.Now(),
		UpdatedAt: time.Now(),
	}).Error; err != nil {
		t.Fatalf("create conversation: %v", err)
	}

	var captured bridge.ChatRequest
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if err := json.NewDecoder(r.Body).Decode(&captured); err != nil {
			t.Fatalf("decode agent request: %v", err)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"conversation_id": "conv-session-chat",
			"response": "ok",
			"skills_used": [],
			"model_used": "test-model",
			"tokens_used": {},
			"agent_id": "super_chat",
			"runtime": "self"
		}`))
	}))
	defer agentServer.Close()

	router := gin.New()
	handler := NewChatHandler(bridge.NewAgentClient(agentServer.URL, time.Second))
	router.POST("/api/chat", handler.Chat)

	body := bytes.NewBufferString(`{
		"conversation_id": "conv-session-chat",
		"user_id": "attacker-user",
		"query": "hello",
		"agent_id": "super_chat"
	}`)
	req := httptest.NewRequest(http.MethodPost, "/api/chat", body)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Account-Session", token)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	if captured.UserID != "session-user" {
		t.Fatalf("expected session user to be forwarded, got %q", captured.UserID)
	}
}

func TestRoleMemoryCreateSessionUserOverridesBodyUserID(t *testing.T) {
	gin.SetMode(gin.TestMode)

	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}
	token := "session-token-role-memory"
	if err := database.DB.Create(&models.AccountSession{
		TokenHash:  accountSessionTokenHash(token),
		UserID:     "session-user",
		CreatedAt:  time.Now(),
		LastUsedAt: time.Now(),
	}).Error; err != nil {
		t.Fatalf("create account session: %v", err)
	}

	var captured bridge.MemoryWriteRequest
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/agent/roles/default/memories" {
			t.Fatalf("unexpected %s %s", r.Method, r.URL.Path)
		}
		if err := json.NewDecoder(r.Body).Decode(&captured); err != nil {
			t.Fatalf("decode memory request: %v", err)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"id": "mem_session",
			"role_id": "default",
			"user_id": "session-user",
			"kind": "role",
			"content": "Use a concise tone",
			"source": "manual",
			"confidence": 1,
			"tags": ["role_config"],
			"created_at": "2026-06-21T00:00:00Z",
			"updated_at": "2026-06-21T00:00:00Z",
			"metadata": {}
		}`))
	}))
	defer agentServer.Close()

	router := gin.New()
	handler := NewChatHandler(bridge.NewAgentClient(agentServer.URL, time.Second))
	router.POST("/api/roles/:id/memories", handler.CreateRoleMemory)

	body := bytes.NewBufferString(`{
		"user_id": "attacker-user",
		"kind": "role",
		"content": "Use a concise tone"
	}`)
	req := httptest.NewRequest(http.MethodPost, "/api/roles/default/memories", body)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Account-Session", token)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	if captured.UserID != "session-user" {
		t.Fatalf("expected session user to be forwarded, got %q", captured.UserID)
	}
	if captured.Kind != "role" || captured.Source != "manual" {
		t.Fatalf("expected default role/manual memory, got %#v", captured)
	}
	if captured.Metadata["entrypoint"] != "super_chat_role_memory" {
		t.Fatalf("expected role memory entrypoint metadata, got %#v", captured.Metadata)
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
	blocks := handler.persistedConversationContext(conv.ID, "0")
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

func TestGetRunFallsBackToStoredTraceEvents(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	conv := models.Conversation{
		ID:        "conv-stored-run",
		UserID:    "user-a",
		AgentID:   "super_chat",
		Title:     "Stored Run",
		CreatedAt: time.Now(),
		UpdatedAt: time.Now(),
	}
	if err := database.DB.Create(&conv).Error; err != nil {
		t.Fatalf("create conversation: %v", err)
	}
	userMsg := models.Message{
		ConversationID: conv.ID,
		UserID:         conv.UserID,
		Role:           "user",
		Content:        "hello",
		CreatedAt:      time.Now().Add(-time.Second),
	}
	if err := database.DB.Create(&userMsg).Error; err != nil {
		t.Fatalf("create user message: %v", err)
	}
	assistantMsg := models.Message{
		ConversationID: conv.ID,
		UserID:         conv.UserID,
		Role:           "assistant",
		Content:        "stored answer",
		SkillsUsed:     `["memory"]`,
		ModelUsed:      "test-model",
		Runtime:        "self",
		RunID:          "run_stored",
		TraceEvents: `[{
			"id":"evt_started",
			"run_id":"run_stored",
			"type":"run.started",
			"status":"running",
			"title":"Run started",
			"payload":{"agent_id":"super_chat"},
			"created_at":"2026-06-18T00:00:00Z"
		},{
			"id":"evt_done",
			"run_id":"run_stored",
			"type":"run.completed",
			"status":"completed",
			"title":"Run completed",
			"payload":{},
			"created_at":"2026-06-18T00:00:01Z"
		}]`,
		CreatedAt: time.Now(),
	}
	if err := database.DB.Create(&assistantMsg).Error; err != nil {
		t.Fatalf("create assistant message: %v", err)
	}

	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/agent/runs/run_stored" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		http.NotFound(w, r)
	}))
	defer agentServer.Close()

	router := gin.New()
	handler := NewChatHandler(bridge.NewAgentClient(agentServer.URL, time.Second))
	router.GET("/api/runs/:id", handler.GetRun)

	req := httptest.NewRequest(http.MethodGet, "/api/runs/run_stored", nil)
	req.Header.Set("X-User-ID", conv.UserID)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	var run bridge.RunRecord
	if err := json.Unmarshal(recorder.Body.Bytes(), &run); err != nil {
		t.Fatalf("decode run: %v", err)
	}
	if run.RunID != "run_stored" || run.Input != "hello" || run.Output != "stored answer" {
		t.Fatalf("unexpected stored run: %#v", run)
	}
	if run.Status != "completed" || len(run.Events) != 2 || run.Events[1].Type != "run.completed" {
		t.Fatalf("expected stored trace events, got %#v", run.Events)
	}
	if len(run.SkillsUsed) != 1 || run.SkillsUsed[0] != "memory" {
		t.Fatalf("expected stored skills, got %#v", run.SkillsUsed)
	}
}

func TestGetRunReturnsNotFoundWhenAgentAndStoredRunMissing(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/agent/runs/run_missing" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		http.NotFound(w, r)
	}))
	defer agentServer.Close()

	router := gin.New()
	handler := NewChatHandler(bridge.NewAgentClient(agentServer.URL, time.Second))
	router.GET("/api/runs/:id", handler.GetRun)

	req := httptest.NewRequest(http.MethodGet, "/api/runs/run_missing", nil)
	req.Header.Set("X-User-ID", "user-a")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusNotFound {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
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

func TestListToolsAppliesUserScopedSettings(t *testing.T) {
	gin.SetMode(gin.TestMode)

	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}
	if err := database.DB.Save(&models.UserSetting{
		UserID: "user-a",
		Key:    "tool.search.enabled",
		Value:  "false",
	}).Error; err != nil {
		t.Fatalf("save user setting: %v", err)
	}
	if err := database.DB.Save(&models.UserSetting{
		UserID: "user-a",
		Key:    "tool.calculator.policy",
		Value:  "deny",
	}).Error; err != nil {
		t.Fatalf("save user policy: %v", err)
	}

	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/agent/skills" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"skills": [
				{"name": "search", "description": "Search", "enabled": true, "source": "builtin", "default_policy": "auto"},
				{"name": "calculator", "description": "Calculator", "enabled": true, "source": "builtin", "default_policy": "auto"}
			]
		}`))
	}))
	defer agentServer.Close()

	router := gin.New()
	handler := NewChatHandler(bridge.NewAgentClient(agentServer.URL, time.Second))
	router.GET("/api/tools", handler.ListTools)

	reqA := httptest.NewRequest(http.MethodGet, "/api/tools", nil)
	reqA.Header.Set("X-User-ID", "user-a")
	recA := httptest.NewRecorder()
	router.ServeHTTP(recA, reqA)
	if recA.Code != http.StatusOK {
		t.Fatalf("unexpected status for user-a %d: %s", recA.Code, recA.Body.String())
	}
	var payloadA bridge.SkillListResponse
	if err := json.Unmarshal(recA.Body.Bytes(), &payloadA); err != nil {
		t.Fatalf("decode user-a payload: %v", err)
	}
	if len(payloadA.Disabled) != 1 || payloadA.Disabled[0] != "search" {
		t.Fatalf("expected search disabled for user-a, got %#v", payloadA.Disabled)
	}
	for _, skill := range payloadA.Skills {
		if skill.Name == "search" && skill.EffectiveEnabled {
			t.Fatalf("expected search to be disabled for user-a: %#v", skill)
		}
		if skill.Name == "calculator" && !skill.EffectiveEnabled {
			t.Fatalf("expected calculator to remain enabled for user-a: %#v", skill)
		}
		if skill.Name == "calculator" && skill.EffectivePolicy != "deny" {
			t.Fatalf("expected calculator policy deny for user-a: %#v", skill)
		}
	}

	reqB := httptest.NewRequest(http.MethodGet, "/api/tools", nil)
	reqB.Header.Set("X-User-ID", "user-b")
	recB := httptest.NewRecorder()
	router.ServeHTTP(recB, reqB)
	if recB.Code != http.StatusOK {
		t.Fatalf("unexpected status for user-b %d: %s", recB.Code, recB.Body.String())
	}
	var payloadB bridge.SkillListResponse
	if err := json.Unmarshal(recB.Body.Bytes(), &payloadB); err != nil {
		t.Fatalf("decode user-b payload: %v", err)
	}
	if len(payloadB.Disabled) != 0 {
		t.Fatalf("expected no disabled tools for user-b, got %#v", payloadB.Disabled)
	}
	for _, skill := range payloadB.Skills {
		if skill.Name == "search" && !skill.EffectiveEnabled {
			t.Fatalf("expected search to remain enabled for user-b: %#v", skill)
		}
	}
}

func TestChatPassesDisabledToolsForUser(t *testing.T) {
	gin.SetMode(gin.TestMode)

	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}
	if err := database.DB.Save(&models.UserSetting{
		UserID: "user-a",
		Key:    "tool.search.enabled",
		Value:  "false",
	}).Error; err != nil {
		t.Fatalf("save user setting: %v", err)
	}
	if err := database.DB.Save(&models.UserSetting{
		UserID: "user-a",
		Key:    "tool.delete_drive.policy",
		Value:  "confirm",
	}).Error; err != nil {
		t.Fatalf("save tool policy: %v", err)
	}
	conv := models.Conversation{
		ID:        "conv-disabled-tools",
		UserID:    "user-a",
		Title:     "New Conversation",
		CreatedAt: time.Now(),
		UpdatedAt: time.Now(),
	}
	if err := database.DB.Create(&conv).Error; err != nil {
		t.Fatalf("create conversation: %v", err)
	}

	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/agent/chat" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		var payload bridge.ChatRequest
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Fatalf("decode chat payload: %v", err)
		}
		if len(payload.DisabledTools) != 1 || payload.DisabledTools[0] != "search" {
			t.Fatalf("expected disabled search in agent payload, got %#v", payload.DisabledTools)
		}
		if payload.ToolPolicies["delete_drive"] != "confirm" {
			t.Fatalf("expected delete_drive policy in agent payload, got %#v", payload.ToolPolicies)
		}
		_, _ = w.Write([]byte(`{
			"conversation_id": "conv-disabled-tools",
			"response": "ok",
			"skills_used": [],
			"citations": [],
			"model_used": "test-model",
			"tokens_used": {},
			"agent_id": "super_chat",
			"runtime": "self"
		}`))
	}))
	defer agentServer.Close()

	router := gin.New()
	handler := NewChatHandler(bridge.NewAgentClient(agentServer.URL, time.Second))
	router.POST("/api/chat", handler.Chat)

	body := bytes.NewBufferString(`{
		"conversation_id": "conv-disabled-tools",
		"query": "hello",
		"stream": false,
		"agent_id": "super_chat"
	}`)
	req := httptest.NewRequest(http.MethodPost, "/api/chat", body)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-User-ID", "user-a")
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", rec.Code, rec.Body.String())
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
