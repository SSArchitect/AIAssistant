package handlers

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
)

func TestPulseCreatesTopicAndPrecomputesDailyItems(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	handler := NewPulseHandler()
	router := gin.New()
	router.GET("/api/pulse", handler.Get)
	router.POST("/api/pulse/refresh", handler.Refresh)
	router.POST("/api/pulse/topics", handler.CreateTopic)

	createBody := bytes.NewBufferString(`{"name":"机器人","keywords":["具身智能","供应链"]}`)
	createReq := httptest.NewRequest(http.MethodPost, "/api/pulse/topics", createBody)
	createReq.Header.Set("Content-Type", "application/json")
	createRecorder := httptest.NewRecorder()
	router.ServeHTTP(createRecorder, createReq)
	if createRecorder.Code != http.StatusCreated {
		t.Fatalf("unexpected create status %d: %s", createRecorder.Code, createRecorder.Body.String())
	}

	refreshBody := bytes.NewBufferString(`{"date":"2026-06-20"}`)
	refreshReq := httptest.NewRequest(http.MethodPost, "/api/pulse/refresh?wait=true", refreshBody)
	refreshReq.Header.Set("Content-Type", "application/json")
	refreshRecorder := httptest.NewRecorder()
	router.ServeHTTP(refreshRecorder, refreshReq)
	if refreshRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected refresh status %d: %s", refreshRecorder.Code, refreshRecorder.Body.String())
	}

	var payload struct {
		Date    string                `json:"date"`
		Topics  []pulseTopicResponse  `json:"topics"`
		Items   []pulseItemResponse   `json:"items"`
		Modules []pulseModuleResponse `json:"modules"`
	}
	if err := json.Unmarshal(refreshRecorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode pulse response: %v", err)
	}
	if payload.Date != "2026-06-20" {
		t.Fatalf("unexpected date: %s", payload.Date)
	}
	if len(payload.Topics) != 1 || payload.Topics[0].Name != "机器人" {
		t.Fatalf("expected created topic in response, got %#v", payload.Topics)
	}
	if len(payload.Items) != 0 {
		t.Fatalf("expected no failed fallback recommendation items, got %#v", payload.Items)
	}
	if len(payload.Modules) != 3 {
		t.Fatalf("expected module background explanations, got %#v", payload.Modules)
	}
	if !strings.Contains(payload.Modules[0].Summary, "不展示推荐卡") {
		t.Fatalf("expected failure explanation in module summary, got %#v", payload.Modules[0])
	}
}

func TestPulseKeywordsSplitChineseEnumerationDelimiter(t *testing.T) {
	got := normalizeKeywords([]string{"Anthropic、Claude、OpenAI，GPT;DeepSeek、A", "Claude"})
	want := []string{"Anthropic", "Claude", "DeepSeek", "GPT", "OpenAI"}
	if fmt.Sprint(got) != fmt.Sprint(want) {
		t.Fatalf("expected delimited keyword string to be normalized, got %#v", got)
	}
	encoded := encodeKeywords([]string{"Agent、RAG、工具调用"})
	if decoded := decodeKeywords(encoded); fmt.Sprint(decoded) != fmt.Sprint([]string{"Agent", "RAG", "工具调用"}) {
		t.Fatalf("expected stored keyword strings to self-heal on decode, got %#v", decoded)
	}
}

func TestPulseGetUsesRecentHealthyItemsForWelcomeSuggestions(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	previousDate := "2026-08-23"
	now := time.Now().UTC()
	detail := pulseItemDetail{
		ContentVersion:       pulseContentVersion,
		RecommendationReason: "你近期持续关注 DeepSeek 模型与 API 成本。",
		KeyPoints:            []string{"V4 Pro agent 能力升级", "API 引入峰谷分时定价"},
		NewsSources: []pulseNewsSource{
			{Title: "DeepSeek releases V4 Pro", URL: "https://deepseek.com/news/v4-pro", Source: "official", Snippet: "DeepSeek released V4 Pro with upgraded agent capabilities on August 23, 2026.", PublishedAt: previousDate},
			{Title: "DeepSeek adjusts V4 API pricing", URL: "https://reuters.com/technology/deepseek-v4-pricing", Source: "Reuters", Snippet: "DeepSeek launched V4 Pro and introduced peak and off-peak API pricing.", PublishedAt: previousDate},
		},
		SuggestedQuestions: []string{
			"V4 Pro agent 能力比 Flash 强在哪？",
			"峰谷定价后哪个时段调用最划算？",
			"「DeepSeek 正式发布 V…」发生了什么？",
		},
	}
	item := models.PulseItem{
		ID:            "previous-welcome-item",
		UserID:        models.DefaultAccountID,
		Date:          previousDate,
		Source:        pulseSourceTopicHot,
		Title:         "DeepSeek 发布 V4 Pro 并调整 API 定价",
		Summary:       "DeepSeek 发布 V4 Pro，并为 Pro 与 Flash 引入新的 API 分时定价。官方信息显示，V4 Pro 此次更新集中在 Agent 任务的调用、规划与工具协作能力，同时保留 Flash 作为更低延迟的选项。独立报道确认了这次发布与价格调整属于同一轮产品更新，峰谷时段的调用成本会出现明显差异。对已经使用 DeepSeek API 的团队，影响不只是模型选型，还包括批处理、离线任务和高峰期流量的调度方式。值得后续核实实际计费区间、速率差异和兼容性，再决定是否迁移生产负载。",
		DetailJSON:    mustJSON(detail),
		ExplorePrompt: "对比 DeepSeek V4 Pro 与 Flash 的能力和成本",
		HeatScore:     90,
		CreatedAt:     now,
		UpdatedAt:     now,
	}
	if err := database.DB.Create(&item).Error; err != nil {
		t.Fatalf("seed previous Pulse item: %v", err)
	}

	handler := NewPulseHandler()
	router := gin.New()
	router.GET("/api/pulse", handler.Get)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/api/pulse?date=2026-08-24", nil))
	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected get status %d: %s", recorder.Code, recorder.Body.String())
	}
	var payload struct {
		Date            string              `json:"date"`
		Items           []pulseItemResponse `json:"items"`
		SuggestionDate  string              `json:"suggestion_date"`
		SuggestionItems []pulseItemResponse `json:"suggestion_items"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode pulse response: %v", err)
	}
	if payload.Date != "2026-08-24" || len(payload.Items) != 0 {
		t.Fatalf("expected today's feed to remain empty, got %#v", payload)
	}
	if payload.SuggestionDate != previousDate || len(payload.SuggestionItems) != 1 {
		t.Fatalf("expected recent Pulse welcome fallback, got %#v", payload)
	}
	if got := payload.SuggestionItems[0]; got.ID != item.ID || got.ExplorePrompt != item.ExplorePrompt {
		t.Fatalf("unexpected suggestion item: %#v", got)
	}
}

func TestFocusTodayRunsSuperChatWithoutConversationAndMaterializesOnClick(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	date := "2026-09-02"
	generatedAnswer := "这是由 Super Chat 完整生成的 Focus Today 回答。"
	var capturedRequest bridge.ChatRequest
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/agent/chat" {
			http.NotFound(w, r)
			return
		}
		if err := json.NewDecoder(r.Body).Decode(&capturedRequest); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		_ = json.NewEncoder(w).Encode(bridge.ChatResponse{
			ConversationID: capturedRequest.ConversationID,
			Response:       generatedAnswer,
			Reasoning:      "background reasoning",
			SkillsUsed:     []string{"get_pulse"},
			Citations: []bridge.Citation{{
				Index:  1,
				Title:  "Official source",
				URL:    "https://example.com/source",
				Source: "official",
			}},
			Artifacts: []bridge.ChatArtifact{{
				Type:   "drive_file",
				ItemID: "artifact-1",
				Name:   "focus.md",
			}},
			ModelUsed: "test-model",
			Runtime:   "self",
			AgentID:   superChatAgentID,
		})
	}))
	defer agentServer.Close()

	generationHandler := NewPulseHandler(bridge.NewAgentClient(agentServer.URL, time.Second))
	snapshot, err := generationHandler.generateFocusTodaySnapshot(context.Background(), date, models.DefaultAccountID)
	if err != nil {
		t.Fatalf("generate Focus Today snapshot: %v", err)
	}
	if capturedRequest.AgentID != superChatAgentID || capturedRequest.Message != focusTodayPrompt {
		t.Fatalf("expected one real Super Chat invocation, got %#v", capturedRequest)
	}
	if capturedRequest.MemoryEnabled == nil || *capturedRequest.MemoryEnabled {
		t.Fatalf("background generation must disable memory writes, got %#v", capturedRequest.MemoryEnabled)
	}
	if capturedRequest.ModelPreference != nil {
		t.Fatalf("Focus Today should use the normal Super Chat model selection, got %#v", capturedRequest.ModelPreference)
	}
	if containsString(capturedRequest.DisabledTools, "get_pulse") || !containsString(capturedRequest.DisabledTools, "refresh_pulse") || !containsString(capturedRequest.DisabledTools, "search") {
		t.Fatalf("Focus Today should allow reading Pulse but disable refresh/search, got %#v", capturedRequest.DisabledTools)
	}
	if snapshot.Content != generatedAnswer || snapshot.Prompt != focusTodayPrompt || snapshot.Title != "Focus Today · "+date {
		t.Fatalf("unexpected Focus Today prompt/title: %#v", snapshot)
	}
	if snapshot.Reasoning != "background reasoning" || snapshot.ModelUsed != "test-model" || snapshot.Runtime != "self" {
		t.Fatalf("generated response metadata was not cached: %#v", snapshot)
	}
	if !strings.Contains(snapshot.SkillsUsedJSON, "get_pulse") || !strings.Contains(snapshot.CitationsJSON, "Official source") || !strings.Contains(snapshot.ArtifactsJSON, "artifact-1") {
		t.Fatalf("generated response payload was not cached: %#v", snapshot)
	}
	var beforeSave int64
	database.DB.Model(&models.Conversation{}).Count(&beforeSave)
	if beforeSave != 0 {
		t.Fatalf("background Super Chat must not create conversations, got %d", beforeSave)
	}
	if err := saveFocusTodaySnapshot(snapshot); err != nil {
		t.Fatalf("save Focus Today snapshot: %v", err)
	}

	handler := NewPulseHandler()
	router := gin.New()
	router.GET("/api/pulse", handler.Get)
	router.POST("/api/pulse/focus-today/open", handler.OpenFocusToday)
	getRecorder := httptest.NewRecorder()
	router.ServeHTTP(getRecorder, httptest.NewRequest(http.MethodGet, "/api/pulse?date="+date, nil))
	if getRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected Focus Today metadata status %d: %s", getRecorder.Code, getRecorder.Body.String())
	}
	var metadataPayload struct {
		FocusToday focusTodayResponse `json:"focus_today"`
	}
	if err := json.Unmarshal(getRecorder.Body.Bytes(), &metadataPayload); err != nil {
		t.Fatalf("decode Focus Today metadata: %v", err)
	}
	if metadataPayload.FocusToday.ID != snapshot.ID || !metadataPayload.FocusToday.Available {
		t.Fatalf("expected cached Focus Today metadata, got %#v", metadataPayload.FocusToday)
	}
	var beforeClick int64
	database.DB.Model(&models.Conversation{}).Count(&beforeClick)
	if beforeClick != 0 {
		t.Fatalf("precomputation must not create conversations, got %d", beforeClick)
	}

	body := fmt.Sprintf(`{"snapshot_id":%q,"language":"zh"}`, snapshot.ID)
	request := httptest.NewRequest(http.MethodPost, "/api/pulse/focus-today/open", strings.NewReader(body))
	request.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)
	if recorder.Code != http.StatusCreated {
		t.Fatalf("unexpected open status %d: %s", recorder.Code, recorder.Body.String())
	}
	var opened struct {
		Conversation models.Conversation `json:"conversation"`
		FocusToday   focusTodayResponse  `json:"focus_today"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &opened); err != nil {
		t.Fatalf("decode Focus Today response: %v", err)
	}
	if opened.Conversation.AgentID != superChatAgentID || opened.Conversation.Title != "今日聚焦 · "+date || !opened.FocusToday.Available {
		t.Fatalf("unexpected materialized conversation: %#v", opened)
	}
	var messages []models.Message
	if err := database.DB.Where("conversation_id = ?", opened.Conversation.ID).Order(messageChronologicalOrder).Find(&messages).Error; err != nil {
		t.Fatalf("load materialized messages: %v", err)
	}
	if len(messages) != 2 || messages[0].Role != "user" || messages[0].Content != focusTodayPrompt || messages[1].Content != snapshot.Content {
		t.Fatalf("unexpected materialized messages: %#v", messages)
	}
	if messages[1].Runtime != snapshot.Runtime || messages[1].ModelUsed != snapshot.ModelUsed || messages[1].Reasoning != snapshot.Reasoning || messages[1].SkillsUsed != snapshot.SkillsUsedJSON || messages[1].Citations != snapshot.CitationsJSON || messages[1].Artifacts != snapshot.ArtifactsJSON || messages[1].FollowUps != snapshot.FollowUpsJSON {
		t.Fatalf("cached answer metadata was not preserved: %#v", messages[1])
	}

	retryBody := fmt.Sprintf(`{"snapshot_id":%q,"language":"en"}`, snapshot.ID)
	retry := httptest.NewRequest(http.MethodPost, "/api/pulse/focus-today/open", strings.NewReader(retryBody))
	retry.Header.Set("Content-Type", "application/json")
	retryRecorder := httptest.NewRecorder()
	router.ServeHTTP(retryRecorder, retry)
	if retryRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected idempotent retry status %d: %s", retryRecorder.Code, retryRecorder.Body.String())
	}
	var retried struct {
		Conversation models.Conversation `json:"conversation"`
	}
	if err := json.Unmarshal(retryRecorder.Body.Bytes(), &retried); err != nil {
		t.Fatalf("decode localized retry: %v", err)
	}
	if retried.Conversation.ID != opened.Conversation.ID || retried.Conversation.Title != "Focus Today · "+date {
		t.Fatalf("expected the reused conversation title to follow English, got %#v", retried.Conversation)
	}
	var conversationCount int64
	var messageCount int64
	database.DB.Model(&models.Conversation{}).Count(&conversationCount)
	database.DB.Model(&models.Message{}).Count(&messageCount)
	if conversationCount != 1 || messageCount != 2 {
		t.Fatalf("repeated clicks must reuse one materialized chat, conversations=%d messages=%d", conversationCount, messageCount)
	}
}

func TestLocalizedFocusTodayTitle(t *testing.T) {
	if got := localizedFocusTodayTitle("zh-CN", "2026-09-02"); got != "今日聚焦 · 2026-09-02" {
		t.Fatalf("unexpected Chinese Focus Today title: %q", got)
	}
	if got := localizedFocusTodayTitle("en", "2026-09-02"); got != "Focus Today · 2026-09-02" {
		t.Fatalf("unexpected English Focus Today title: %q", got)
	}
}

func TestScheduledPulseGenerationInvokesFocusTodaySuperChat(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	date := "2026-09-02"
	userID := models.DefaultAccountID
	now := time.Now()
	detail := pulseItemDetail{
		ContentVersion:       pulseContentVersion,
		RecommendationReason: "你近期持续关注 DeepSeek 模型与 API 成本。",
		KeyPoints:            []string{"V4 Pro agent 能力升级", "API 引入峰谷分时定价"},
		NewsSources: []pulseNewsSource{
			{Title: "DeepSeek releases V4 Pro", URL: "https://deepseek.com/news/v4-pro", Source: "official", Snippet: "DeepSeek released V4 Pro with upgraded agent capabilities.", PublishedAt: date},
			{Title: "DeepSeek adjusts V4 API pricing", URL: "https://reuters.com/technology/deepseek-v4-pricing", Source: "Reuters", Snippet: "DeepSeek launched V4 Pro and introduced peak and off-peak API pricing.", PublishedAt: date},
		},
		SuggestedQuestions: []string{
			"V4 Pro agent 能力比 Flash 强在哪？",
			"峰谷定价后哪个时段调用最划算？",
			"DeepSeek V4 Pro 迁移要改什么？",
		},
	}
	item := models.PulseItem{
		ID:            "scheduled-focus",
		UserID:        userID,
		Date:          date,
		Source:        pulseSourceTopicHot,
		Title:         "DeepSeek 发布 V4 Pro 并调整 API 定价",
		Summary:       "DeepSeek 发布 V4 Pro，并为 Pro 与 Flash 引入新的 API 分时定价。官方信息显示，V4 Pro 此次更新集中在 Agent 任务的调用、规划与工具协作能力，同时保留 Flash 作为更低延迟的选项。独立报道确认了这次发布与价格调整属于同一轮产品更新，峰谷时段的调用成本会出现明显差异。对已经使用 DeepSeek API 的团队，影响不只是模型选型，还包括批处理、离线任务和高峰期流量的调度方式。值得后续核实实际计费区间、速率差异和兼容性，再决定是否迁移生产负载。",
		DetailJSON:    mustJSON(detail),
		ExplorePrompt: "对比 DeepSeek V4 Pro 与 Flash 的能力和成本",
		HeatScore:     90,
		CreatedAt:     now,
		UpdatedAt:     now,
	}
	if err := database.DB.Create(&item).Error; err != nil {
		t.Fatalf("seed Pulse item: %v", err)
	}
	modules := make([]models.PulseModule, 0, len(pulseModuleOrder))
	for _, key := range pulseModuleOrder {
		modules = append(modules, models.PulseModule{
			ID:        uuid.NewString(),
			UserID:    userID,
			Date:      date,
			Key:       key,
			Title:     key,
			Summary:   "ready",
			CreatedAt: now,
			UpdatedAt: now,
		})
	}
	if err := database.DB.Create(&modules).Error; err != nil {
		t.Fatalf("seed Pulse modules: %v", err)
	}

	requests := make(chan bridge.ChatRequest, 2)
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req bridge.ChatRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		requests <- req
		_ = json.NewEncoder(w).Encode(bridge.ChatResponse{
			ConversationID: req.ConversationID,
			Response:       "scheduled Focus Today answer",
			SkillsUsed:     []string{"get_pulse"},
			ModelUsed:      "test-model",
			AgentID:        superChatAgentID,
			Runtime:        "self",
		})
	}))
	defer agentServer.Close()

	handler := NewPulseHandler(bridge.NewAgentClient(agentServer.URL, time.Second))
	if !handler.startPulseGeneration(date, userID, false, "scheduled:test") {
		t.Fatal("expected scheduled generation to start")
	}
	deadline := time.Now().Add(2 * time.Second)
	for handler.pulseGenerationActive(date, userID) && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if handler.pulseGenerationActive(date, userID) {
		t.Fatal("scheduled Focus Today generation did not finish")
	}

	select {
	case req := <-requests:
		if req.AgentID != superChatAgentID || req.Message != focusTodayPrompt {
			t.Fatalf("unexpected scheduled Super Chat request: %#v", req)
		}
	default:
		t.Fatal("scheduled Pulse generation did not invoke Focus Today Super Chat")
	}
	select {
	case extra := <-requests:
		t.Fatalf("healthy cached Pulse should require only the Focus Today Super Chat call, got extra request %#v", extra)
	default:
	}

	var snapshotCount int64
	var conversationCount int64
	database.DB.Model(&models.FocusTodaySnapshot{}).Count(&snapshotCount)
	database.DB.Model(&models.Conversation{}).Count(&conversationCount)
	if snapshotCount != 1 || conversationCount != 0 {
		t.Fatalf("scheduled generation should cache one snapshot without a conversation, snapshots=%d conversations=%d", snapshotCount, conversationCount)
	}
}

func TestFocusTodaySuperChatFailureDoesNotCacheOrCreateConversation(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(bridge.ChatResponse{
			Response:  "provider unavailable",
			ErrorType: "provider_error",
		})
	}))
	defer agentServer.Close()

	handler := NewPulseHandler(bridge.NewAgentClient(agentServer.URL, time.Second))
	if _, err := handler.generateFocusTodaySnapshot(context.Background(), "2026-09-02", models.DefaultAccountID); err == nil {
		t.Fatal("expected failed Super Chat response to reject Focus Today generation")
	}
	var snapshotCount int64
	var conversationCount int64
	database.DB.Model(&models.FocusTodaySnapshot{}).Count(&snapshotCount)
	database.DB.Model(&models.Conversation{}).Count(&conversationCount)
	if snapshotCount != 0 || conversationCount != 0 {
		t.Fatalf("failed generation must not create cached or user-visible state, snapshots=%d conversations=%d", snapshotCount, conversationCount)
	}
}

func TestFocusTodayMissingSnapshotDoesNotCreateConversation(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}
	handler := NewPulseHandler()
	router := gin.New()
	router.POST("/api/pulse/focus-today/open", handler.OpenFocusToday)
	request := httptest.NewRequest(http.MethodPost, "/api/pulse/focus-today/open", strings.NewReader(`{"snapshot_id":"missing"}`))
	request.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)
	if recorder.Code != http.StatusNotFound {
		t.Fatalf("unexpected missing snapshot status %d: %s", recorder.Code, recorder.Body.String())
	}
	var count int64
	database.DB.Model(&models.Conversation{}).Count(&count)
	if count != 0 {
		t.Fatalf("missing precomputation must not create a conversation, got %d", count)
	}
}

func TestFocusTodaySharesPulseSixHourSchedule(t *testing.T) {
	if pulseScheduledRefreshInterval != 6*time.Hour {
		t.Fatalf("Focus Today should refresh with Pulse every 6 hours, got %s", pulseScheduledRefreshInterval)
	}
	if pulseScheduledRefreshInterval < 4*time.Hour || pulseScheduledRefreshInterval > 8*time.Hour {
		t.Fatalf("Focus Today refresh must stay inside the requested 4-8 hour window, got %s", pulseScheduledRefreshInterval)
	}
}

func TestPulseMemorySignalsOnlyUseMessagesFromLastThirtyDays(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}
	now := time.Now().UTC()
	messages := []models.Message{
		{ConversationID: "recent", UserID: "memory-user", Role: "user", Content: "最近在研究 AI Agent 和模型能力", CreatedAt: now.Add(-2 * time.Hour)},
		{ConversationID: "old", UserID: "memory-user", Role: "user", Content: "旅行路线和住宿规划", CreatedAt: now.Add(-31 * 24 * time.Hour)},
	}
	for _, message := range messages {
		if err := database.DB.Create(&message).Error; err != nil {
			t.Fatalf("seed message: %v", err)
		}
	}

	signals, err := NewPulseHandler().loadMemorySignals("memory-user")
	if err != nil {
		t.Fatalf("load Memory signals: %v", err)
	}
	themes := map[string]bool{}
	for _, signal := range signals {
		themes[signal.Theme] = true
	}
	if !themes["AI 应用与 Agent"] {
		t.Fatalf("expected recent AI memory signal, got %#v", signals)
	}
	if themes["旅行规划"] {
		t.Fatalf("expected messages older than 30 days to be excluded, got %#v", signals)
	}
}

func TestPulseTopicOptimizationContextCombinesHistoryAndRetrievalQuality(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}
	now := time.Now()
	date := now.Format("2006-01-02")
	userID := "optimization-user"
	topics := []models.PulseTopic{
		{ID: "topic-product", UserID: userID, Name: "Agent 产品", Keywords: encodeKeywords([]string{"Agent", "RAG", "工作流"}), CreatedAt: now, UpdatedAt: now},
		{ID: "topic-engineering", UserID: userID, Name: "Agent 工程", Keywords: encodeKeywords([]string{"Agent", "RAG", "评测"}), CreatedAt: now, UpdatedAt: now},
	}
	if err := database.DB.Create(&topics).Error; err != nil {
		t.Fatalf("seed topics: %v", err)
	}
	if err := database.DB.Create(&models.Message{
		ConversationID: "optimization-conversation",
		UserID:         userID,
		Role:           "user",
		Content:        "最近在研究 Agent、RAG 和评测体系",
		CreatedAt:      now.Add(-time.Hour),
	}).Error; err != nil {
		t.Fatalf("seed message: %v", err)
	}
	item := qualityTestPulseItem(date, "optimization-item", []pulseNewsSource{
		{Title: "OpenAI releases agent controls", URL: "https://openai.com/news/agent-controls", Snippet: "OpenAI released agent controls for enterprise customers.", PublishedAt: date},
		{Title: "OpenAI agent controls launch", URL: "https://reuters.com/technology/agent-controls", Snippet: "OpenAI launched new agent controls for enterprise customers.", PublishedAt: date},
	})
	item.UserID = userID
	item.TopicID = topics[0].ID
	item.TopicName = topics[0].Name
	item.CreatedAt = now
	item.UpdatedAt = now
	if err := database.DB.Create(&item).Error; err != nil {
		t.Fatalf("seed item: %v", err)
	}
	deletedTopicItem := qualityTestPulseItem(date, "deleted-topic-item", []pulseNewsSource{
		{Title: "Old route note", URL: "https://example.com/old-route", Snippet: "Historical content for a removed topic.", PublishedAt: date},
		{Title: "Old route report", URL: "https://example.org/old-route", Snippet: "Another historical source.", PublishedAt: date},
	})
	deletedTopicItem.UserID = userID
	deletedTopicItem.TopicID = "removed-topic"
	deletedTopicItem.TopicName = "清远自驾三条 + AIGC 创作"
	deletedTopicItem.CreatedAt = now
	deletedTopicItem.UpdatedAt = now
	if err := database.DB.Create(&deletedTopicItem).Error; err != nil {
		t.Fatalf("seed removed topic item: %v", err)
	}
	if err := database.DB.Create(&models.PulseEvent{
		ID: "optimization-open", UserID: userID, Date: date, ItemID: item.ID,
		TopicID: item.TopicID, TopicName: item.TopicName, Source: item.Source,
		EventType: pulseEventOpen, Value: 1, CreatedAt: now,
	}).Error; err != nil {
		t.Fatalf("seed event: %v", err)
	}
	evidence := []pulseSearchEvidence{
		{
			QueryID: "q1", Module: pulseSourceTopicHot, Query: "Agent RAG latest news", Intent: "recent updates",
			TopicID: topics[0].ID, TopicName: topics[0].Name,
			Results: []pulseSearchResult{{Title: "OpenAI releases agent controls", URL: "https://openai.com/news/agent-controls", PublishedAt: date}},
		},
	}
	evidence[0].Stage = "initial"
	diagnostics := pulseGenerationDiagnostics{
		RawCandidateCount: 2,
		GroundedItemCount: 1,
		CandidateRejections: []pulseCandidateRejectionDiagnostic{
			{Stage: "publishing", Module: pulseSourceTopicHot, Title: "Generic update", Reasons: []string{"generic_title"}},
		},
	}
	if err := persistPulseRetrievalRun(date, userID, evidence, nil, 1, 1, false, diagnostics, nil); err != nil {
		t.Fatalf("persist retrieval run: %v", err)
	}

	router := gin.New()
	router.GET("/api/pulse/topic-optimization", NewPulseHandler().TopicOptimizationContext)
	req := httptest.NewRequest(http.MethodGet, "/api/pulse/topic-optimization?lookback_days=30", nil)
	req.Header.Set("X-User-ID", userID)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)
	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	var payload map[string]interface{}
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if strings.Contains(recorder.Body.String(), `"enabled"`) {
		t.Fatalf("topic optimization must not expose a status field: %s", recorder.Body.String())
	}
	if strings.Contains(recorder.Body.String(), deletedTopicItem.TopicName) {
		t.Fatalf("removed topic history must not be returned: %s", recorder.Body.String())
	}
	if payload["lookback_days"] != float64(30) {
		t.Fatalf("unexpected lookback: %#v", payload["lookback_days"])
	}
	if _, exists := payload["topics"]; exists {
		t.Fatalf("legacy topics key must not be returned: %#v", payload["topics"])
	}
	currentTopics, ok := payload["current_topics"].([]interface{})
	if !ok || len(currentTopics) != 2 {
		t.Fatalf("expected current topics, got %#v", payload["current_topics"])
	}
	if _, ok := payload["candidate_interest_signals"].([]interface{}); !ok {
		t.Fatalf("expected separately labeled candidate interests, got %#v", payload["candidate_interest_signals"])
	}
	semantics, ok := payload["topic_semantics"].(map[string]interface{})
	if !ok || semantics["existing_topics_source"] != "current_topics_only" {
		t.Fatalf("expected explicit topic semantics, got %#v", payload["topic_semantics"])
	}
	if intents, ok := payload["recent_user_intents"].([]interface{}); !ok || len(intents) != 1 {
		t.Fatalf("expected recent user intent, got %#v", payload["recent_user_intents"])
	}
	history, ok := payload["history"].(map[string]interface{})
	if !ok {
		t.Fatalf("expected history object, got %#v", payload["history"])
	}
	if overlaps, ok := history["overlap_candidates"].([]interface{}); !ok || len(overlaps) != 1 {
		t.Fatalf("expected overlapping topics, got %#v", history["overlap_candidates"])
	}
	runs, ok := history["retrieval_runs"].([]interface{})
	if !ok || len(runs) != 1 {
		t.Fatalf("expected retrieval diagnostics, got %#v", history["retrieval_runs"])
	}
	firstRun, _ := runs[0].(map[string]interface{})
	if firstRun["raw_candidate_count"] != float64(2) {
		t.Fatalf("expected raw candidate diagnostics, got %#v", firstRun)
	}
	if rejections, ok := firstRun["candidate_rejections"].([]interface{}); !ok || len(rejections) != 1 {
		t.Fatalf("expected item rejection reasons, got %#v", firstRun["candidate_rejections"])
	}
	metrics, ok := history["current_topic_metrics"].([]interface{})
	if !ok || len(metrics) != 2 {
		t.Fatalf("expected current-topic metrics, got %#v", history["current_topic_metrics"])
	}
	if _, exists := history["topic_metrics"]; exists {
		t.Fatalf("ambiguous topic metrics key must not be returned: %#v", history["topic_metrics"])
	}
	summary, _ := history["summary"].(map[string]interface{})
	if summary["sampled_cluster_count"] != float64(1) {
		t.Fatalf("expected only current-topic history in summary, got %#v", summary)
	}
	firstMetric, _ := metrics[0].(map[string]interface{})
	if firstMetric["stored_clusters"] != float64(1) {
		t.Fatalf("expected topic cluster history, got %#v", firstMetric)
	}
	engagement, _ := firstMetric["engagement"].(map[string]interface{})
	if engagement[pulseEventOpen] != float64(1) {
		t.Fatalf("expected topic engagement, got %#v", engagement)
	}
}

func TestPulseTopicManagementUsesCreateUpdateAndDelete(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}
	handler := NewPulseHandler()
	router := gin.New()
	router.GET("/api/pulse/topics", handler.ListTopics)
	router.POST("/api/pulse/topics", handler.CreateTopic)
	router.PUT("/api/pulse/topics/:id", handler.UpdateTopic)
	router.DELETE("/api/pulse/topics/:id", handler.DeleteTopic)

	createReq := httptest.NewRequest(
		http.MethodPost,
		"/api/pulse/topics",
		bytes.NewBufferString(`{"name":"AI Agent","keywords":["Agent"]}`),
	)
	createReq.Header.Set("Content-Type", "application/json")
	createReq.Header.Set("X-User-ID", "topic-lifecycle-user")
	createRecorder := httptest.NewRecorder()
	router.ServeHTTP(createRecorder, createReq)
	if createRecorder.Code != http.StatusCreated {
		t.Fatalf("unexpected create status %d: %s", createRecorder.Code, createRecorder.Body.String())
	}
	var createPayload struct {
		Topic pulseTopicResponse `json:"topic"`
	}
	if err := json.Unmarshal(createRecorder.Body.Bytes(), &createPayload); err != nil {
		t.Fatalf("decode create response: %v", err)
	}
	if strings.Contains(createRecorder.Body.String(), `"enabled"`) {
		t.Fatalf("create response must not expose a topic status field: %s", createRecorder.Body.String())
	}

	updateReq := httptest.NewRequest(
		http.MethodPut,
		"/api/pulse/topics/"+createPayload.Topic.ID,
		bytes.NewBufferString(`{"keywords":["Agent","workflow"]}`),
	)
	updateReq.Header.Set("Content-Type", "application/json")
	updateReq.Header.Set("X-User-ID", "topic-lifecycle-user")
	updateRecorder := httptest.NewRecorder()
	router.ServeHTTP(updateRecorder, updateReq)
	if updateRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected update status %d: %s", updateRecorder.Code, updateRecorder.Body.String())
	}
	var updatePayload struct {
		Topic pulseTopicResponse `json:"topic"`
	}
	if err := json.Unmarshal(updateRecorder.Body.Bytes(), &updatePayload); err != nil {
		t.Fatalf("decode update response: %v", err)
	}
	if strings.Contains(updateRecorder.Body.String(), `"enabled"`) {
		t.Fatalf("update response must not expose a topic status field: %s", updateRecorder.Body.String())
	}

	deleteReq := httptest.NewRequest(http.MethodDelete, "/api/pulse/topics/"+createPayload.Topic.ID, nil)
	deleteReq.Header.Set("X-User-ID", "topic-lifecycle-user")
	deleteRecorder := httptest.NewRecorder()
	router.ServeHTTP(deleteRecorder, deleteReq)
	if deleteRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected delete status %d: %s", deleteRecorder.Code, deleteRecorder.Body.String())
	}

	listReq := httptest.NewRequest(http.MethodGet, "/api/pulse/topics", nil)
	listReq.Header.Set("X-User-ID", "topic-lifecycle-user")
	listRecorder := httptest.NewRecorder()
	router.ServeHTTP(listRecorder, listReq)
	if listRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected list status %d: %s", listRecorder.Code, listRecorder.Body.String())
	}
	var listPayload struct {
		Topics []pulseTopicResponse `json:"topics"`
	}
	if err := json.Unmarshal(listRecorder.Body.Bytes(), &listPayload); err != nil {
		t.Fatalf("decode list response: %v", err)
	}
	if len(listPayload.Topics) != 0 {
		t.Fatalf("expected deleted topic to disappear, got %#v", listPayload.Topics)
	}

	missingRecorder := httptest.NewRecorder()
	router.ServeHTTP(missingRecorder, deleteReq)
	if missingRecorder.Code != http.StatusNotFound {
		t.Fatalf("expected repeated delete to return 404, got %d: %s", missingRecorder.Code, missingRecorder.Body.String())
	}
}

func TestPulseUsesAgentGeneratedModules(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/agent/search" {
			writePulseTestSearchResponse(w, r)
			return
		}
		if r.URL.Path != "/agent/chat" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		var req bridge.ChatRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			t.Fatalf("decode request: %v", err)
		}
		contextText := strings.Join(req.ContextBlocks, "\n")
		if !strings.Contains(contextText, "verified_clusters") || !strings.Contains(contextText, "https://example.com/robotics-latest") {
			t.Fatalf("expected verified clusters in generation context, got %s", contextText)
		}
		if strings.Contains(contextText, `"search_evidence"`) || strings.Contains(contextText, `"search_queries"`) {
			t.Fatalf("raw discovery evidence must stay out of the bounded generation context, got %s", contextText)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"conversation_id": "pulse-2026-06-20",
			"response": "{\"modules\":[{\"key\":\"topic_hot\",\"title\":\"你的机器人订阅今日追踪\",\"summary\":\"围绕具身智能订阅生成。\",\"items\":[{\"topic_name\":\"机器人\",\"category\":\"关注 Topic\",\"title\":\"具身智能机器人项目发布新控制系统\",\"summary\":\"具身智能机器人项目发布新控制系统，并开放供应链试点。\",\"heat_score\":88,\"recommendation_reason\":\"因为你订阅了机器人。\",\"signals\":[\"搜索来源：机器人与具身智能出现新进展 - https://example.com/robotics-latest\"],\"quick_context\":\"先看产业化落地。\",\"key_points\":[\"供应链\",\"场景\",\"成本\"],\"suggested_questions\":[\"具身智能近期有什么变化？\",\"我该看哪些公司？\",\"有哪些风险？\"],\"explore_prompt\":\"展开具身智能今日推荐\"}]},{\"key\":\"memory\",\"title\":\"延续你的最近对话\",\"summary\":\"根据最近 memory 生成。\",\"items\":[{\"category\":\"近日 Memory\",\"title\":\"Pulse 预计算服务完成上线\",\"summary\":\"Pulse 预计算服务完成上线，并新增资讯簇推荐能力。\",\"heat_score\":77,\"recommendation_reason\":\"最近多次讨论工作台。\",\"signals\":[\"搜索来源：机器人与具身智能出现新进展 - https://example.com/robotics-latest\"],\"quick_context\":\"把想法落为功能。\",\"key_points\":[\"结构\",\"验证\",\"迭代\"],\"suggested_questions\":[\"下一步做什么？\",\"怎么验证？\",\"如何排优先级？\"],\"explore_prompt\":\"继续整理工作台想法\"}]},{\"key\":\"interest_hot\",\"title\":\"你可能会关心的热门延伸\",\"summary\":\"结合订阅和 memory 生成。\",\"items\":[{\"category\":\"可能兴趣\",\"title\":\"AI 硬件厂商推出具身智能终端\",\"summary\":\"AI 硬件厂商推出具身智能终端，并开放首批应用测试。\",\"heat_score\":74,\"recommendation_reason\":\"由机器人和 AI 信号外扩。\",\"signals\":[\"搜索来源：机器人与具身智能出现新进展 - https://example.com/robotics-latest\"],\"quick_context\":\"关注硬件生态。\",\"key_points\":[\"芯片\",\"终端\",\"应用\"],\"suggested_questions\":[\"为什么值得跟？\",\"有哪些公司？\",\"有什么风险？\"],\"explore_prompt\":\"展开 AI 硬件生态\"}]}]}",
			"skills_used": [],
			"model_used": "test",
			"tokens_used": {},
			"agent_id": "super_chat",
			"runtime": "self"
		}`))
	}))
	defer agentServer.Close()

	handler := NewPulseHandler(bridge.NewAgentClient(agentServer.URL, time.Second))
	router := gin.New()
	router.POST("/api/pulse/topics", handler.CreateTopic)
	router.POST("/api/pulse/refresh", handler.Refresh)

	createBody := bytes.NewBufferString(`{"name":"机器人","keywords":["具身智能"]}`)
	createReq := httptest.NewRequest(http.MethodPost, "/api/pulse/topics", createBody)
	createReq.Header.Set("Content-Type", "application/json")
	createRecorder := httptest.NewRecorder()
	router.ServeHTTP(createRecorder, createReq)
	if createRecorder.Code != http.StatusCreated {
		t.Fatalf("unexpected create status %d: %s", createRecorder.Code, createRecorder.Body.String())
	}

	refreshBody := bytes.NewBufferString(`{"date":"2026-06-20"}`)
	refreshReq := httptest.NewRequest(http.MethodPost, "/api/pulse/refresh?wait=true", refreshBody)
	refreshReq.Header.Set("Content-Type", "application/json")
	refreshRecorder := httptest.NewRecorder()
	router.ServeHTTP(refreshRecorder, refreshReq)
	if refreshRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected refresh status %d: %s", refreshRecorder.Code, refreshRecorder.Body.String())
	}

	var payload struct {
		Modules []pulseModuleResponse `json:"modules"`
	}
	if err := json.Unmarshal(refreshRecorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode pulse response: %v", err)
	}
	if len(payload.Modules) != 3 {
		t.Fatalf("expected 3 generated modules, got %#v", payload.Modules)
	}
	if payload.Modules[0].Title != "你的机器人订阅今日追踪" {
		t.Fatalf("expected agent-generated module title, got %#v", payload.Modules[0])
	}
	if len(payload.Modules[0].Items) != 1 || payload.Modules[0].Items[0].Title != "具身智能机器人项目发布新控制系统" {
		t.Fatalf("expected agent-generated topic item, got %#v", payload.Modules[0].Items)
	}
	if got := payload.Modules[0].Items[0].Detail.SuggestedQuestions; len(got) < 3 || got[0] == "" || !strings.Contains(strings.Join(got, "\n"), "具身智能") {
		t.Fatalf("expected suggested questions, got %#v", got)
	}
}

func TestPulseChatPersistsBackgroundTokenUsage(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/agent/chat" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		var req bridge.ChatRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			t.Fatalf("decode request: %v", err)
		}
		if req.ConversationID != "pulse-acct-a-2026-07-06" || req.UserID != "acct-a" || req.AgentID != superChatAgentID {
			t.Fatalf("unexpected pulse chat request: %#v", req)
		}
		disabled := map[string]bool{}
		for _, name := range req.DisabledTools {
			disabled[name] = true
		}
		for _, name := range pulseBackgroundDisabledTools {
			if !disabled[name] {
				t.Fatalf("expected Pulse background request to disable %s: %#v", name, req.DisabledTools)
			}
		}

		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(bridge.ChatResponse{
			ConversationID: req.ConversationID,
			Response:       `{"modules":[]}`,
			SkillsUsed:     []string{},
			ModelUsed:      "MiniMax-M3",
			TokensUsed: map[string]int{
				"input":        10,
				"output":       3,
				"input_cached": 4,
			},
			AgentID: "super_chat",
			Runtime: "self",
			RunID:   "run-pulse",
		})
	}))
	defer agentServer.Close()

	handler := NewPulseHandler(bridge.NewAgentClient(agentServer.URL, time.Second))
	response, err := handler.requestPulseChat(context.Background(), "pulse-acct-a-2026-07-06", "acct-a", "generate pulse", []string{"system"}, []string{"context"})
	if err != nil {
		t.Fatalf("request pulse chat: %v", err)
	}
	if response != `{"modules":[]}` {
		t.Fatalf("unexpected response: %s", response)
	}

	var usages []models.TokenUsage
	if err := database.DB.Find(&usages).Error; err != nil {
		t.Fatalf("load token usages: %v", err)
	}
	if len(usages) != 1 {
		t.Fatalf("expected one token usage row, got %#v", usages)
	}
	usage := usages[0]
	if usage.UserID != "acct-a" || usage.ConversationID != "pulse-acct-a-2026-07-06" || usage.MessageID != 0 || usage.AgentID != pulseBackgroundAgentID {
		t.Fatalf("unexpected pulse usage identity: %#v", usage)
	}
	if usage.RunID != "run-pulse" || usage.Runtime != "self" || usage.ModelUsed != "MiniMax-M3" {
		t.Fatalf("unexpected pulse usage metadata: %#v", usage)
	}
	if usage.InputTokens != 10 || usage.OutputTokens != 3 || usage.TotalTokens != 13 || usage.CachedInputTokens != 4 {
		t.Fatalf("unexpected pulse usage totals: %#v", usage)
	}
	if !strings.Contains(usage.UsageJSON, "input_cached") {
		t.Fatalf("expected raw token JSON to be persisted, got %q", usage.UsageJSON)
	}
}

func TestPulseAutomaticRefreshThrottlePersistsAcrossHandlers(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	now := time.Date(2026, 8, 24, 8, 0, 0, 0, time.UTC)
	handler := NewPulseHandler()
	reserved, err := handler.reservePulseAutomaticAttempt("2026-08-24", "active-user", now)
	if err != nil || !reserved {
		t.Fatalf("expected first automatic attempt reservation, reserved=%v err=%v", reserved, err)
	}
	if err := handler.finishPulseAutomaticAttempt("2026-08-24", "active-user", fmt.Errorf("provider unavailable"), now.Add(time.Minute)); err != nil {
		t.Fatalf("persist failed attempt: %v", err)
	}

	// A fresh handler simulates a gateway restart. The failed attempt must still
	// suppress the old 30-minute retry loop and use the 12-hour failure backoff.
	restarted := NewPulseHandler()
	reserved, err = restarted.reservePulseAutomaticAttempt("2026-08-24", "active-user", now.Add(6*time.Hour))
	if err != nil {
		t.Fatalf("check persisted throttle: %v", err)
	}
	if reserved {
		t.Fatal("expected failed automatic generation to remain throttled after restart")
	}
	reserved, err = restarted.reservePulseAutomaticAttempt("2026-08-24", "active-user", now.Add(12*time.Hour))
	if err != nil || !reserved {
		t.Fatalf("expected retry after failure backoff, reserved=%v err=%v", reserved, err)
	}
	crashRestart := NewPulseHandler()
	reserved, err = crashRestart.reservePulseAutomaticAttempt("2026-08-24", "active-user", now.Add(18*time.Hour))
	if err != nil {
		t.Fatalf("check running retry throttle: %v", err)
	}
	if reserved {
		t.Fatal("expected an interrupted retry to retain its failure backoff")
	}
	if err := restarted.finishPulseAutomaticAttempt("2026-08-24", "active-user", nil, now.Add(12*time.Hour+time.Minute)); err != nil {
		t.Fatalf("persist successful attempt: %v", err)
	}

	var state models.PulseScheduleState
	if err := database.DB.First(&state, "user_id = ?", "active-user").Error; err != nil {
		t.Fatalf("load schedule state: %v", err)
	}
	if state.LastStatus != "succeeded" || state.ConsecutiveFailures != 0 || state.LastSuccessAt == nil {
		t.Fatalf("unexpected recovered schedule state: %#v", state)
	}
}

func TestPulseSchedulerTargetsOnlyRecentlyActiveAccounts(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	now := time.Now()
	sessions := []models.AccountSession{
		{TokenHash: "active-new", UserID: "active-user", CreatedAt: now, LastUsedAt: now.Add(-time.Hour)},
		{TokenHash: "active-old", UserID: "active-user", CreatedAt: now, LastUsedAt: now.Add(-2 * time.Hour)},
		{TokenHash: "second-active", UserID: "second-user", CreatedAt: now, LastUsedAt: now.Add(-6 * 24 * time.Hour)},
		{TokenHash: "inactive", UserID: "inactive-user", CreatedAt: now, LastUsedAt: now.Add(-8 * 24 * time.Hour)},
	}
	if err := database.DB.Create(&sessions).Error; err != nil {
		t.Fatalf("seed sessions: %v", err)
	}

	got := NewPulseHandler().scheduledPulseUserIDs()
	if strings.Join(got, ",") != "active-user,second-user" {
		t.Fatalf("expected unique recently active users ordered by recency, got %#v", got)
	}
}

func TestPulseSyncsSettingsBeforeGeneration(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}
	if err := database.DB.Create(&[]models.Setting{
		{
			Key:       "llm.minimax.api_key",
			Value:     "sk-test",
			UpdatedAt: time.Now(),
		},
		{
			Key:       "llm.minimax.model",
			Value:     "abab6.5s-chat",
			UpdatedAt: time.Now(),
		},
	}).Error; err != nil {
		t.Fatalf("seed setting: %v", err)
	}

	var mu sync.Mutex
	agentCalls := []string{}
	recordCall := func(path string) {
		mu.Lock()
		defer mu.Unlock()
		agentCalls = append(agentCalls, path)
	}

	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		recordCall(r.URL.Path)
		switch r.URL.Path {
		case "/agent/config":
			var req struct {
				Settings map[string]string `json:"settings"`
			}
			if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
				t.Fatalf("decode config request: %v", err)
			}
			if req.Settings["llm.minimax.api_key"] != "sk-test" {
				t.Fatalf("expected synced MiniMax key, got %#v", req.Settings)
			}
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"status":"ok"}`))
		case "/agent/search":
			writePulseTestSearchResponse(w, r)
		case "/agent/chat":
			var req bridge.ChatRequest
			if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
				t.Fatalf("decode chat request: %v", err)
			}
			if req.ModelPreference == nil || *req.ModelPreference != "minimax:abab6.5s-chat" {
				t.Fatalf("expected pulse generation to use minimax only, got %#v", req.ModelPreference)
			}
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(bridge.ChatResponse{
				ConversationID: "pulse-2026-06-20",
				Response:       `{"modules":[{"key":"topic_hot","title":"同步后的 Topic","summary":"已同步配置后生成。","items":[{"topic_name":"机器人","category":"关注 Topic","title":"具身智能机器人项目发布控制系统","summary":"具身智能机器人项目发布控制系统，并开放首批场景测试。","heat_score":88,"recommendation_reason":"因为你订阅了机器人。","signals":["搜索来源：机器人与具身智能出现新进展 - https://example.com/robotics-latest"],"quick_context":"先看配置同步是否生效。","key_points":["配置","检索","生成"],"suggested_questions":["机器人这条来源说了什么？","怎么核验具身智能进展？","后续跟踪哪些公司？"],"explore_prompt":"展开同步测试"}]},{"key":"memory","title":"同步后的 Memory","summary":"保持模块完整。","items":[{"category":"近日 Memory","title":"Pulse 服务完成配置同步","summary":"Pulse 服务完成配置同步，并恢复资讯簇生成。","heat_score":76,"recommendation_reason":"最近在看 Pulse。","signals":["搜索来源：机器人与具身智能出现新进展 - https://example.com/robotics-latest"],"quick_context":"确认模块完整。","key_points":["配置","候选","过滤"],"suggested_questions":["Pulse 配置同步怎么验证？","候选池怎么补满？","过滤逻辑怎么评估？"],"explore_prompt":"展开 memory"}]},{"key":"interest_hot","title":"同步后的兴趣延伸","summary":"保持模块完整。","items":[{"category":"可能兴趣","title":"AI 硬件厂商推出机器人终端","summary":"AI 硬件厂商推出机器人终端，并新增供应链合作方。","heat_score":72,"recommendation_reason":"机器人与 AI 相关。","signals":["搜索来源：机器人与具身智能出现新进展 - https://example.com/robotics-latest"],"quick_context":"确认兴趣模块完整。","key_points":["兴趣","外扩","来源"],"suggested_questions":["这条兴趣推荐依据是什么？","有哪些外部来源？","下一步追什么？"],"explore_prompt":"展开兴趣"}]}]}`,
				ModelUsed:      "test",
				TokensUsed:     map[string]int{},
				AgentID:        "super_chat",
				Runtime:        "self",
			})
		default:
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
	}))
	defer agentServer.Close()

	agentClient := bridge.NewAgentClient(agentServer.URL, time.Second)
	handler := NewPulseHandlerWithSyncer(agentClient, NewConfigSyncer(agentClient))
	router := gin.New()
	router.POST("/api/pulse/topics", handler.CreateTopic)
	router.POST("/api/pulse/refresh", handler.Refresh)

	createReq := httptest.NewRequest(http.MethodPost, "/api/pulse/topics", bytes.NewBufferString(`{"name":"机器人","keywords":["具身智能"]}`))
	createReq.Header.Set("Content-Type", "application/json")
	createRecorder := httptest.NewRecorder()
	router.ServeHTTP(createRecorder, createReq)
	if createRecorder.Code != http.StatusCreated {
		t.Fatalf("unexpected create status %d: %s", createRecorder.Code, createRecorder.Body.String())
	}

	refreshReq := httptest.NewRequest(http.MethodPost, "/api/pulse/refresh?wait=true", bytes.NewBufferString(`{"date":"2026-06-20"}`))
	refreshReq.Header.Set("Content-Type", "application/json")
	refreshRecorder := httptest.NewRecorder()
	router.ServeHTTP(refreshRecorder, refreshReq)
	if refreshRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected refresh status %d: %s", refreshRecorder.Code, refreshRecorder.Body.String())
	}

	mu.Lock()
	defer mu.Unlock()
	if len(agentCalls) < 3 || agentCalls[0] != "/agent/config" {
		t.Fatalf("expected config sync before generation calls, got %#v", agentCalls)
	}
}

func TestPulseExpandsSingleTopicKeywordsAndSuggestsTopics(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	handler := NewPulseHandler()
	router := gin.New()
	router.POST("/api/pulse/topics", handler.CreateTopic)
	router.GET("/api/pulse", handler.Get)

	createReq := httptest.NewRequest(http.MethodPost, "/api/pulse/topics", bytes.NewBufferString(`{"name":"AI 应用开发"}`))
	createReq.Header.Set("Content-Type", "application/json")
	createRecorder := httptest.NewRecorder()
	router.ServeHTTP(createRecorder, createReq)
	if createRecorder.Code != http.StatusCreated {
		t.Fatalf("unexpected create status %d: %s", createRecorder.Code, createRecorder.Body.String())
	}

	var created struct {
		Topic pulseTopicResponse `json:"topic"`
	}
	if err := json.Unmarshal(createRecorder.Body.Bytes(), &created); err != nil {
		t.Fatalf("decode created topic: %v", err)
	}
	joinedKeywords := strings.Join(created.Topic.Keywords, "\n")
	if !strings.Contains(joinedKeywords, "多模态") || !strings.Contains(joinedKeywords, "模型能力") {
		t.Fatalf("expected expanded AI keywords, got %#v", created.Topic.Keywords)
	}

	getReq := httptest.NewRequest(http.MethodGet, "/api/pulse?date=2026-06-20", nil)
	getRecorder := httptest.NewRecorder()
	router.ServeHTTP(getRecorder, getReq)
	if getRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected get status %d: %s", getRecorder.Code, getRecorder.Body.String())
	}

	var payload struct {
		SuggestedTopics []pulseSuggestedTopicResponse `json:"suggested_topics"`
	}
	if err := json.Unmarshal(getRecorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode pulse response: %v", err)
	}
	if len(payload.SuggestedTopics) == 0 {
		t.Fatalf("expected suggested topics")
	}
	for _, suggestion := range payload.SuggestedTopics {
		if suggestion.Name == created.Topic.Name {
			t.Fatalf("suggested topics should exclude subscribed topic, got %#v", payload.SuggestedTopics)
		}
	}
}

func TestPulseResponseIncludesRelatedClusters(t *testing.T) {
	now := time.Now()
	items := []models.PulseItem{
		{
			ID:        "cluster-a",
			Date:      "2026-06-20",
			TopicID:   "topic-robotics",
			TopicName: "机器人",
			Source:    pulseSourceTopicHot,
			Category:  "关注 Topic",
			Title:     "具身智能供应链出现新线索",
			Summary:   "机器人量产和供应链值得跟踪。",
			HeatScore: 90,
			DetailJSON: mustJSON(pulseItemDetail{
				KeyPoints: []string{"具身智能", "供应链", "量产"},
			}),
			CreatedAt: now,
			UpdatedAt: now,
		},
		{
			ID:        "cluster-b",
			Date:      "2026-06-20",
			TopicID:   "topic-robotics",
			TopicName: "机器人",
			Source:    pulseSourceInterestHot,
			Category:  "可能兴趣",
			Title:     "人形机器人量产节奏需要核验",
			Summary:   "具身智能和供应链消息需要对照来源。",
			HeatScore: 84,
			DetailJSON: mustJSON(pulseItemDetail{
				KeyPoints: []string{"人形机器人", "具身智能", "供应链"},
			}),
			CreatedAt: now.Add(time.Second),
			UpdatedAt: now.Add(time.Second),
		},
	}

	responses := itemResponses(items)
	if len(responses) != 2 {
		t.Fatalf("expected two responses, got %#v", responses)
	}
	if len(responses[0].RelatedClusters) == 0 || responses[0].RelatedClusters[0].ID != "cluster-b" {
		t.Fatalf("expected related cluster-b, got %#v", responses[0].RelatedClusters)
	}
	if !strings.Contains(responses[0].RelatedClusters[0].Reason, "topic") {
		t.Fatalf("expected explainable related reason, got %#v", responses[0].RelatedClusters[0])
	}
}

func TestPulseEventsUpdateFeedbackAndRanking(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	date := "2026-06-20"
	now := time.Now()
	items := []models.PulseItem{
		{
			ID:         "pulse-high",
			UserID:     "0",
			Date:       date,
			Source:     pulseSourceTopicHot,
			Category:   "关注 Topic",
			Title:      "OpenAI 发布 AgentGuard-2 权限控制",
			Summary:    pulseTestLongSummary("OpenAI AgentGuard-2 企业权限控制"),
			HeatScore:  90,
			DetailJSON: pulseTestVerifiedDetail(date),
			CreatedAt:  now,
			UpdatedAt:  now,
		},
		{
			ID:         "pulse-liked",
			UserID:     "0",
			Date:       date,
			Source:     pulseSourceTopicHot,
			Category:   "关注 Topic",
			Title:      "OpenAI 开放 AgentGuard-2 审计日志",
			Summary:    pulseTestLongSummary("OpenAI AgentGuard-2 审计日志"),
			HeatScore:  70,
			DetailJSON: pulseTestVerifiedDetail(date),
			CreatedAt:  now.Add(time.Second),
			UpdatedAt:  now.Add(time.Second),
		},
	}
	if err := database.DB.Create(&items).Error; err != nil {
		t.Fatalf("seed pulse items: %v", err)
	}

	handler := NewPulseHandler()
	router := gin.New()
	router.POST("/api/pulse/events", handler.RecordEvent)
	router.GET("/api/pulse", handler.Get)

	eventReq := httptest.NewRequest(http.MethodPost, "/api/pulse/events", bytes.NewBufferString(`{"item_id":"pulse-liked","event_type":"upvote","value":1}`))
	eventReq.Header.Set("Content-Type", "application/json")
	eventRecorder := httptest.NewRecorder()
	router.ServeHTTP(eventRecorder, eventReq)
	if eventRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected event status %d: %s", eventRecorder.Code, eventRecorder.Body.String())
	}
	var eventPayload struct {
		Feedback pulseItemFeedbackResponse `json:"feedback"`
	}
	if err := json.Unmarshal(eventRecorder.Body.Bytes(), &eventPayload); err != nil {
		t.Fatalf("decode event response: %v", err)
	}
	if eventPayload.Feedback.Vote != "up" || eventPayload.Feedback.UpvoteCount == 0 {
		t.Fatalf("expected upvote feedback, got %#v", eventPayload.Feedback)
	}

	getReq := httptest.NewRequest(http.MethodGet, "/api/pulse?date=2026-06-20", nil)
	getRecorder := httptest.NewRecorder()
	router.ServeHTTP(getRecorder, getReq)
	if getRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected get status %d: %s", getRecorder.Code, getRecorder.Body.String())
	}
	var payload struct {
		Items []pulseItemResponse `json:"items"`
	}
	if err := json.Unmarshal(getRecorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode pulse response: %v", err)
	}
	if len(payload.Items) != 2 {
		t.Fatalf("expected two items, got %#v", payload.Items)
	}
	if payload.Items[0].ID != "pulse-liked" {
		t.Fatalf("expected feedback-ranked item first, got %#v", payload.Items)
	}
	if payload.Items[0].Feedback.Vote != "up" || payload.Items[0].FeatureScore <= payload.Items[1].FeatureScore {
		t.Fatalf("expected ranked feedback in response, got %#v", payload.Items)
	}
}

func TestPulseWelcomeQuestionClickPersistsConsumedKeyWithoutItem(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	handler := NewPulseHandler()
	router := gin.New()
	router.POST("/api/pulse/events", handler.RecordEvent)
	router.GET("/api/pulse", handler.Get)

	eventReq := httptest.NewRequest(
		http.MethodPost,
		"/api/pulse/events",
		bytes.NewBufferString(`{"date":"2026-08-28","event_type":"question_click","metadata":{"surface":"welcome","source":"fallback","question":" 今天最应该先推进什么？ "}}`),
	)
	eventReq.Header.Set("Content-Type", "application/json")
	eventReq.Header.Set("X-User-ID", "welcome-user")
	eventRecorder := httptest.NewRecorder()
	router.ServeHTTP(eventRecorder, eventReq)
	if eventRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected event status %d: %s", eventRecorder.Code, eventRecorder.Body.String())
	}

	getReq := httptest.NewRequest(http.MethodGet, "/api/pulse?date=2026-08-28", nil)
	getReq.Header.Set("X-User-ID", "welcome-user")
	getRecorder := httptest.NewRecorder()
	router.ServeHTTP(getRecorder, getReq)
	if getRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected get status %d: %s", getRecorder.Code, getRecorder.Body.String())
	}
	var payload struct {
		ConsumedQuestionKeys  []string `json:"consumed_question_keys"`
		ConsumptionTTLSeconds int      `json:"consumption_ttl_seconds"`
	}
	if err := json.Unmarshal(getRecorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode pulse response: %v", err)
	}
	if len(payload.ConsumedQuestionKeys) != 1 || payload.ConsumedQuestionKeys[0] != "今天最应该先推进什么？" {
		t.Fatalf("expected normalized consumed question, got %#v", payload.ConsumedQuestionKeys)
	}
	if payload.ConsumptionTTLSeconds != 7*24*60*60 {
		t.Fatalf("expected configured default consumption TTL, got %d", payload.ConsumptionTTLSeconds)
	}

	var event models.PulseEvent
	if err := database.DB.First(&event, "user_id = ?", "welcome-user").Error; err != nil {
		t.Fatalf("load question event: %v", err)
	}
	if event.ItemID != "welcome" || event.EventType != pulseEventQuestion {
		t.Fatalf("unexpected persisted question event: %#v", event)
	}
	if err := database.DB.Model(&event).Update("created_at", time.Now().Add(-8*24*time.Hour)).Error; err != nil {
		t.Fatalf("expire question event: %v", err)
	}
	expiredReq := httptest.NewRequest(http.MethodGet, "/api/pulse?date=2026-08-28", nil)
	expiredReq.Header.Set("X-User-ID", "welcome-user")
	expiredRecorder := httptest.NewRecorder()
	router.ServeHTTP(expiredRecorder, expiredReq)
	if expiredRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected expired get status %d: %s", expiredRecorder.Code, expiredRecorder.Body.String())
	}
	if err := json.Unmarshal(expiredRecorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode expired Pulse response: %v", err)
	}
	if len(payload.ConsumedQuestionKeys) != 0 {
		t.Fatalf("expected question consumption to expire after TTL, got %#v", payload.ConsumedQuestionKeys)
	}
}

func TestPulseEventsBoostFutureItemsByTopic(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	now := time.Now()
	items := []models.PulseItem{
		{
			ID:         "pulse-old-liked",
			UserID:     "0",
			Date:       "2026-06-19",
			TopicID:    "topic-ai",
			TopicName:  "AI 应用开发",
			Source:     pulseSourceTopicHot,
			Category:   "关注 Topic",
			Title:      "旧的信息簇",
			Summary:    "用户之前赞过的方向。",
			HeatScore:  70,
			DetailJSON: mustJSON(pulseItemDetail{KeyPoints: []string{"旧反馈"}}),
			CreatedAt:  now.Add(-24 * time.Hour),
			UpdatedAt:  now.Add(-24 * time.Hour),
		},
		{
			ID:         "pulse-future-topic",
			UserID:     "0",
			Date:       "2026-06-20",
			TopicID:    "topic-ai",
			TopicName:  "AI 应用开发",
			Source:     pulseSourceTopicHot,
			Category:   "关注 Topic",
			Title:      "OpenAI 发布 AgentGuard-2 权限控制",
			Summary:    pulseTestLongSummary("OpenAI AgentGuard-2 企业权限控制"),
			HeatScore:  70,
			DetailJSON: pulseTestVerifiedDetail("2026-06-20"),
			CreatedAt:  now,
			UpdatedAt:  now,
		},
		{
			ID:         "pulse-future-other",
			UserID:     "0",
			Date:       "2026-06-20",
			TopicID:    "topic-other",
			TopicName:  "其他方向",
			Source:     pulseSourceTopicHot,
			Category:   "关注 Topic",
			Title:      "Anthropic 发布 Claude 企业审计功能",
			Summary:    pulseTestLongSummary("Anthropic Claude 企业审计功能"),
			HeatScore:  78,
			DetailJSON: pulseTestVerifiedDetail("2026-06-20"),
			CreatedAt:  now.Add(time.Second),
			UpdatedAt:  now.Add(time.Second),
		},
	}
	if err := database.DB.Create(&items).Error; err != nil {
		t.Fatalf("seed pulse items: %v", err)
	}

	handler := NewPulseHandler()
	router := gin.New()
	router.POST("/api/pulse/events", handler.RecordEvent)
	router.GET("/api/pulse", handler.Get)

	eventReq := httptest.NewRequest(http.MethodPost, "/api/pulse/events", bytes.NewBufferString(`{"item_id":"pulse-old-liked","event_type":"upvote","value":1}`))
	eventReq.Header.Set("Content-Type", "application/json")
	eventRecorder := httptest.NewRecorder()
	router.ServeHTTP(eventRecorder, eventReq)
	if eventRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected event status %d: %s", eventRecorder.Code, eventRecorder.Body.String())
	}

	getReq := httptest.NewRequest(http.MethodGet, "/api/pulse?date=2026-06-20", nil)
	getRecorder := httptest.NewRecorder()
	router.ServeHTTP(getRecorder, getReq)
	if getRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected get status %d: %s", getRecorder.Code, getRecorder.Body.String())
	}
	var payload struct {
		Items []pulseItemResponse `json:"items"`
	}
	if err := json.Unmarshal(getRecorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode pulse response: %v", err)
	}
	if len(payload.Items) != 2 {
		t.Fatalf("expected current-day items, got %#v", payload.Items)
	}
	if payload.Items[0].ID != "pulse-future-topic" {
		t.Fatalf("expected historical topic feedback to boost future topic item, got %#v", payload.Items)
	}
}

func TestPulseRecommendedItemsFiltersConsumedItemIDs(t *testing.T) {
	items := []models.PulseItem{
		{ID: "fresh", Date: "2026-06-20", Source: pulseSourceTopicHot, Title: "OpenAI 发布全新模型能力", Summary: "OpenAI 发布全新模型能力并开放企业接入。", HeatScore: 80, DetailJSON: pulseTestVerifiedDetail("2026-06-20")},
		{ID: "opened", Date: "2026-06-20", Source: pulseSourceTopicHot, Title: "Anthropic 推出管理后台", Summary: "Anthropic 推出管理后台并新增权限配置。", HeatScore: 99, DetailJSON: pulseTestVerifiedDetail("2026-06-20")},
		{ID: "seen", Date: "2026-06-20", Source: pulseSourceTopicHot, Title: "Google 更新企业策略", Summary: "Google 更新企业策略并扩展管理员控制。", HeatScore: 98, DetailJSON: pulseTestVerifiedDetail("2026-06-20")},
		{ID: "down", Date: "2026-06-20", Source: pulseSourceTopicHot, Title: "Meta 开放团队权限", Summary: "Meta 开放团队权限并支持成员分组。", HeatScore: 97, DetailJSON: pulseTestVerifiedDetail("2026-06-20")},
	}
	state := pulseFeatureState{
		feedbackByItem: map[string]pulseItemFeedbackResponse{
			"seen": {ExposureCount: pulseExposureFilterThreshold},
			"down": {Vote: "down", DownvoteCount: 1},
		},
		feedbackByKey:   map[string]pulseItemFeedbackResponse{},
		consumedItemIDs: map[string]bool{"opened": true},
		directScores:    map[string]int{},
		clusterScores:   map[string]int{},
		topicScores:     map[string]int{},
		sourceScores:    map[string]int{},
	}

	recommended := recommendedPulseItems(items, state)
	if len(recommended) != 1 || recommended[0].ID != "fresh" {
		t.Fatalf("expected only fresh item after feature filtering, got %#v", recommended)
	}
}

func TestPulseFeatureStateFiltersExactItemIDWithinTTL(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	userID := "ttl-consumption-user"
	activeItem := models.PulseItem{
		ID:        "active-card",
		UserID:    userID,
		Date:      "2026-08-28",
		Source:    pulseSourceTopicHot,
		TopicName: "AI",
		Title:     "OpenAI 发布 AgentGuard-2 权限控制",
		Summary:   "新版增加企业权限与审计能力。",
	}
	replacementItem := activeItem
	replacementItem.ID = "replacement-card"
	expiredItem := activeItem
	expiredItem.ID = "expired-card"
	expiredItem.Title = "Anthropic 发布新的企业权限功能"

	events := []models.PulseEvent{
		{
			ID:        "active-open",
			UserID:    userID,
			Date:      activeItem.Date,
			ItemID:    activeItem.ID,
			EventType: pulseEventOpen,
			Value:     1,
			CreatedAt: time.Now().Add(-10 * time.Minute),
		},
		{
			ID:        "expired-open",
			UserID:    userID,
			Date:      expiredItem.Date,
			ItemID:    expiredItem.ID,
			EventType: pulseEventOpen,
			Value:     1,
			CreatedAt: time.Now().Add(-2 * time.Hour),
		},
	}
	if err := database.DB.Create(&events).Error; err != nil {
		t.Fatalf("seed Pulse open events: %v", err)
	}

	state, err := loadPulseFeatureState(
		userID,
		activeItem.Date,
		[]models.PulseItem{activeItem, replacementItem, expiredItem},
		time.Hour,
	)
	if err != nil {
		t.Fatalf("load Pulse feature state: %v", err)
	}
	if !state.shouldFilter(activeItem) {
		t.Fatal("expected recently opened item ID to be filtered")
	}
	if state.shouldFilter(replacementItem) {
		t.Fatal("expected a different item ID from the same cluster to remain eligible")
	}
	if state.shouldFilter(expiredItem) {
		t.Fatal("expected an item click older than the TTL to expire")
	}
}

func TestPulseRecommendedItemsDedupesVisibleClusters(t *testing.T) {
	detail := pulseTestVerifiedDetail("2026-06-20")
	items := []models.PulseItem{
		{ID: "lower", Date: "2026-06-20", Title: "OpenAI 发布 AgentGuard-2 权限控制", Summary: "OpenAI 发布 AgentGuard-2，并新增企业权限控制。", Source: pulseSourceTopicHot, TopicName: "AI", HeatScore: 80, DetailJSON: detail},
		{ID: "higher", Date: "2026-06-20", Title: "OpenAI 发布 AgentGuard-2 权限控制", Summary: "OpenAI 发布 AgentGuard-2，并新增企业权限控制。", Source: pulseSourceTopicHot, TopicName: "AI", HeatScore: 96, DetailJSON: detail},
		{ID: "other", Date: "2026-06-20", Title: "Anthropic 发布 Claude 企业审计功能", Summary: "Anthropic 发布 Claude 企业审计功能，并开放管理员接入。", Source: pulseSourceTopicHot, TopicName: "AI", HeatScore: 70, DetailJSON: detail},
	}

	recommended := recommendedPulseItems(items, pulseFeatureState{
		feedbackByItem: map[string]pulseItemFeedbackResponse{},
		feedbackByKey:  map[string]pulseItemFeedbackResponse{},
		directScores:   map[string]int{},
		clusterScores:  map[string]int{},
		topicScores:    map[string]int{},
		sourceScores:   map[string]int{},
	})

	if len(recommended) != 2 {
		t.Fatalf("expected duplicate cluster to be hidden, got %#v", recommended)
	}
	if recommended[0].ID != "higher" || recommended[1].ID != "other" {
		t.Fatalf("expected highest ranked duplicate plus other item, got %#v", recommended)
	}
}

func TestPulseRecommendedItemsHideLowInformationSingleSource(t *testing.T) {
	lowInfoDetail := mustJSON(pulseItemDetail{
		RecommendationReason: "这组来源和「AI 模型进展」相关，适合作为今日快速判断入口。",
		QuickContext:         "综合判断：单一来源提到AI 模型进展，但不足以判断为热点或趋势。",
		KeyPoints:            []string{"证据提示：这是搜索结果聚合摘要，具体事实应以原文为准。"},
		NewsSources: []pulseNewsSource{
			{
				Title: "AI Open Source Trends 2026-05-26 · Issue #1280 · duanyytop/agents-radar · GitHub",
				URL:   "https://github.com/duanyytop/agents-radar/issues/1280",
			},
		},
	})
	strongDetail := mustJSON(pulseItemDetail{
		RecommendationReason: "多来源共同指向同一更新。",
		QuickContext:         "两条来源互相印证。",
		NewsSources: []pulseNewsSource{
			{Title: "OpenAI 发布 AgentGuard-2 权限控制", URL: "https://openai.com/official", PublishedAt: "2026-06-19"},
			{Title: "独立报道确认 AgentGuard-2 权限控制发布", URL: "https://reuters.com/report", PublishedAt: "2026-06-18"},
		},
	})
	items := []models.PulseItem{
		{ID: "low-info", Date: "2026-06-20", Title: "AI 模型进展：GPT-RAG、Claude Code、Gemini CLI 待核验线索", Summary: "单一来源提到AI 模型进展，但不足以判断为热点或趋势。", Source: pulseSourceTopicHot, TopicName: "AI", HeatScore: 99, DetailJSON: lowInfoDetail},
		{ID: "strong", Date: "2026-06-20", Title: "OpenAI 发布 AgentGuard-2 权限控制", Summary: "OpenAI 发布 AgentGuard-2，并新增企业权限控制。", Source: pulseSourceTopicHot, TopicName: "AI", HeatScore: 70, DetailJSON: strongDetail},
	}

	recommended := recommendedPulseItems(items, pulseFeatureState{
		feedbackByItem: map[string]pulseItemFeedbackResponse{},
		feedbackByKey:  map[string]pulseItemFeedbackResponse{},
		directScores:   map[string]int{},
		clusterScores:  map[string]int{},
		topicScores:    map[string]int{},
		sourceScores:   map[string]int{},
	})

	if len(recommended) != 1 || recommended[0].ID != "strong" {
		t.Fatalf("expected low-information single source to be hidden, got %#v", recommended)
	}
}

func TestPulseRecommendedItemsReturnsEmptyForOnlyLowInformationItems(t *testing.T) {
	detail := mustJSON(pulseItemDetail{
		QuickContext: "单一来源提到AI 模型进展，但不足以判断为热点或趋势。",
		NewsSources:  []pulseNewsSource{{Title: "GitHub issue", URL: "https://github.com/example/repo/issues/1"}},
	})
	items := []models.PulseItem{
		{ID: "low-info", Title: "AI 模型进展：待核验线索", Summary: "单一来源提到AI 模型进展，但不足以判断为热点或趋势。", Source: pulseSourceTopicHot, TopicName: "AI", HeatScore: 99, DetailJSON: detail},
	}

	recommended := recommendedPulseItems(items, pulseFeatureState{
		feedbackByItem: map[string]pulseItemFeedbackResponse{},
		feedbackByKey:  map[string]pulseItemFeedbackResponse{},
		directScores:   map[string]int{},
		clusterScores:  map[string]int{},
		topicScores:    map[string]int{},
		sourceScores:   map[string]int{},
	})

	if len(recommended) != 0 {
		t.Fatalf("expected only low-information items to produce empty recommendations, got %#v", recommended)
	}
}

func TestPulseRepairsMalformedAgentJSON(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	callCount := 0
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/agent/search" {
			writePulseTestSearchResponse(w, r)
			return
		}
		if r.URL.Path != "/agent/chat" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		callCount++

		var req bridge.ChatRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			t.Fatalf("decode request: %v", err)
		}

		response := `{"modules":[{"key":"topic_hot","title":"坏 JSON" "summary":"缺逗号","items":[]}]}`
		if callCount == 2 {
			if !strings.Contains(req.Message, "解析错误") {
				t.Fatalf("expected repair prompt, got %s", req.Message)
			}
			response = `{"modules":[{"key":"topic_hot","title":"修复后的机器人订阅","summary":"根据订阅 topic 生成。","items":[{"topic_name":"机器人","category":"关注 Topic","title":"机器人项目发布新控制系统","summary":"机器人项目发布新控制系统，并开放首批供应链试点。","heat_score":86,"recommendation_reason":"你订阅了机器人。","signals":["搜索来源：机器人与具身智能出现新进展 - https://example.com/robotics-latest"],"quick_context":"从产业链进展切入。","key_points":["供应链","场景","成本"],"suggested_questions":["最近有哪些进展？","哪些公司值得看？","风险是什么？"],"explore_prompt":"展开机器人产业链"}]},{"key":"memory","title":"修复后的近日记忆","summary":"根据近期工程化对话生成。","items":[{"category":"近日 Memory","title":"Pulse 预计算服务完成上线","summary":"Pulse 预计算服务完成上线，并新增定时资讯簇生成。","heat_score":78,"recommendation_reason":"最近正在做 Pulse。","signals":["搜索来源：机器人与具身智能出现新进展 - https://example.com/robotics-latest"],"quick_context":"把推荐链路产品化。","key_points":["定时","可解释","追问"],"suggested_questions":["怎么设计定时任务？","如何解释推荐？","怎么评估点击？"],"explore_prompt":"继续推进 Pulse 预计算"}]},{"key":"interest_hot","title":"修复后的兴趣延伸","summary":"结合机器人与 AI 外扩。","items":[{"category":"可能兴趣","title":"具身智能厂商推出 Agent 控制器","summary":"具身智能厂商推出 Agent 控制器，并开放首批机器人测试。","heat_score":74,"recommendation_reason":"由机器人和 AI 信号外扩。","signals":["搜索来源：机器人与具身智能出现新进展 - https://example.com/robotics-latest"],"quick_context":"关注具身智能产品化。","key_points":["模型","硬件","数据"],"suggested_questions":["为什么值得跟？","有什么落地场景？","成本瓶颈在哪？"],"explore_prompt":"展开具身智能 Agent"}]}]}`
		}

		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(bridge.ChatResponse{
			ConversationID: req.ConversationID,
			Response:       response,
			SkillsUsed:     []string{},
			ModelUsed:      "test",
			TokensUsed:     map[string]int{},
			AgentID:        "super_chat",
			Runtime:        "self",
		})
	}))
	defer agentServer.Close()

	handler := NewPulseHandler(bridge.NewAgentClient(agentServer.URL, time.Second))
	router := gin.New()
	router.POST("/api/pulse/topics", handler.CreateTopic)
	router.POST("/api/pulse/refresh", handler.Refresh)

	createBody := bytes.NewBufferString(`{"name":"机器人","keywords":["具身智能"]}`)
	createReq := httptest.NewRequest(http.MethodPost, "/api/pulse/topics", createBody)
	createReq.Header.Set("Content-Type", "application/json")
	createRecorder := httptest.NewRecorder()
	router.ServeHTTP(createRecorder, createReq)
	if createRecorder.Code != http.StatusCreated {
		t.Fatalf("unexpected create status %d: %s", createRecorder.Code, createRecorder.Body.String())
	}

	refreshBody := bytes.NewBufferString(`{"date":"2026-06-20"}`)
	refreshReq := httptest.NewRequest(http.MethodPost, "/api/pulse/refresh?wait=true", refreshBody)
	refreshReq.Header.Set("Content-Type", "application/json")
	refreshRecorder := httptest.NewRecorder()
	router.ServeHTTP(refreshRecorder, refreshReq)
	if refreshRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected refresh status %d: %s", refreshRecorder.Code, refreshRecorder.Body.String())
	}
	if callCount != 2 {
		t.Fatalf("expected generation plus repair call, got %d", callCount)
	}

	var payload struct {
		Modules []pulseModuleResponse `json:"modules"`
	}
	if err := json.Unmarshal(refreshRecorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode pulse response: %v", err)
	}
	if len(payload.Modules) != 3 {
		t.Fatalf("expected 3 repaired modules, got %#v", payload.Modules)
	}
	if payload.Modules[0].Title != "修复后的机器人订阅" {
		t.Fatalf("expected repaired module title, got %#v", payload.Modules[0])
	}
	if got := payload.Modules[0].Items[0].Detail.SuggestedQuestions; len(got) < 3 || !strings.Contains(strings.Join(got, "\n"), "机器人") {
		t.Fatalf("expected repaired suggested questions, got %#v", got)
	}
}

func TestPulseGenerationRepairFailureUsesVerifiedSearchFallback(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	callCount := 0
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/agent/search" {
			writePulseTestSearchResponse(w, r)
			return
		}
		if r.URL.Path != "/agent/chat" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		callCount++

		var req bridge.ChatRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			t.Fatalf("decode request: %v", err)
		}
		if strings.Contains(req.Message, "key=topic_hot") ||
			strings.Contains(req.Message, "key=memory") ||
			strings.Contains(req.Message, "key=interest_hot") {
			t.Fatalf("generation must not fan out into per-module model calls: %s", req.Message)
		}
		if callCount > 2 {
			t.Fatalf("expected at most two model calls, got call %d", callCount)
		}
		if callCount == 2 {
			if !strings.Contains(req.Message, "修复 Broken Pulse JSON") {
				t.Fatalf("expected the second model call to be JSON repair, got %s", req.Message)
			}
			http.Error(w, "repair unavailable", http.StatusInternalServerError)
			return
		}

		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(bridge.ChatResponse{
			ConversationID: req.ConversationID,
			Response:       `{"modules":[{"key":"topic_hot","title":"坏 JSON" "summary":"缺逗号","items":[]}]}`,
			SkillsUsed:     []string{},
			ModelUsed:      "test",
			TokensUsed:     map[string]int{},
			AgentID:        "super_chat",
			Runtime:        "self",
		})
	}))
	defer agentServer.Close()

	handler := NewPulseHandler(bridge.NewAgentClient(agentServer.URL, time.Second))
	router := gin.New()
	router.POST("/api/pulse/topics", handler.CreateTopic)
	router.POST("/api/pulse/refresh", handler.Refresh)

	createBody := bytes.NewBufferString(`{"name":"机器人","keywords":["具身智能"]}`)
	createReq := httptest.NewRequest(http.MethodPost, "/api/pulse/topics", createBody)
	createReq.Header.Set("Content-Type", "application/json")
	createRecorder := httptest.NewRecorder()
	router.ServeHTTP(createRecorder, createReq)
	if createRecorder.Code != http.StatusCreated {
		t.Fatalf("unexpected create status %d: %s", createRecorder.Code, createRecorder.Body.String())
	}

	refreshBody := bytes.NewBufferString(`{"date":"2026-06-20"}`)
	refreshReq := httptest.NewRequest(http.MethodPost, "/api/pulse/refresh?wait=true", refreshBody)
	refreshReq.Header.Set("Content-Type", "application/json")
	refreshRecorder := httptest.NewRecorder()
	router.ServeHTTP(refreshRecorder, refreshReq)
	if refreshRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected refresh status %d: %s", refreshRecorder.Code, refreshRecorder.Body.String())
	}
	if callCount != 2 {
		t.Fatalf("expected generation plus one repair call, got %d", callCount)
	}

	var payload struct {
		CandidateCount   int                   `json:"candidate_count"`
		RecommendedCount int                   `json:"recommended_count"`
		Modules          []pulseModuleResponse `json:"modules"`
	}
	if err := json.Unmarshal(refreshRecorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode pulse response: %v", err)
	}
	if len(payload.Modules) != 3 {
		t.Fatalf("expected 3 modules, got %#v", payload.Modules)
	}
	if payload.Modules[0].Title != "订阅 Topic 的外网新动向" {
		t.Fatalf("expected deterministic search fallback module, got %#v", payload.Modules[0])
	}
	if payload.CandidateCount == 0 || payload.RecommendedCount == 0 || len(payload.Modules[0].Items) == 0 {
		t.Fatalf("expected verified deterministic fallback items, got %#v", payload)
	}
}

func TestPulseUsesVerifiedSearchFallbackWhenGenerationFails(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/agent/search" {
			writePulseTestSearchResponse(w, r)
			return
		}
		if r.URL.Path != "/agent/chat" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		http.Error(w, "generation unavailable", http.StatusInternalServerError)
	}))
	defer agentServer.Close()

	handler := NewPulseHandler(bridge.NewAgentClient(agentServer.URL, time.Second))
	router := gin.New()
	router.POST("/api/pulse/topics", handler.CreateTopic)
	router.POST("/api/pulse/refresh", handler.Refresh)

	createBody := bytes.NewBufferString(`{"name":"机器人","keywords":["具身智能"]}`)
	createReq := httptest.NewRequest(http.MethodPost, "/api/pulse/topics", createBody)
	createReq.Header.Set("Content-Type", "application/json")
	createRecorder := httptest.NewRecorder()
	router.ServeHTTP(createRecorder, createReq)
	if createRecorder.Code != http.StatusCreated {
		t.Fatalf("unexpected create status %d: %s", createRecorder.Code, createRecorder.Body.String())
	}

	refreshBody := bytes.NewBufferString(`{"date":"2026-06-20"}`)
	refreshReq := httptest.NewRequest(http.MethodPost, "/api/pulse/refresh?wait=true", refreshBody)
	refreshReq.Header.Set("Content-Type", "application/json")
	refreshRecorder := httptest.NewRecorder()
	router.ServeHTTP(refreshRecorder, refreshReq)
	if refreshRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected refresh status %d: %s", refreshRecorder.Code, refreshRecorder.Body.String())
	}

	var payload struct {
		CandidateCount   int                   `json:"candidate_count"`
		RecommendedCount int                   `json:"recommended_count"`
		Items            []pulseItemResponse   `json:"items"`
		Modules          []pulseModuleResponse `json:"modules"`
	}
	if err := json.Unmarshal(refreshRecorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode pulse response: %v", err)
	}
	if len(payload.Modules) != 3 {
		t.Fatalf("expected 3 modules, got %#v", payload.Modules)
	}
	if payload.Modules[0].Title != "订阅 Topic 的外网新动向" {
		t.Fatalf("expected search fallback title, got %#v", payload.Modules[0])
	}
	if payload.CandidateCount == 0 {
		t.Fatalf("expected search fallback candidates to be retained in the pool, got %#v", payload)
	}
	if payload.RecommendedCount == 0 || len(payload.Items) == 0 || len(payload.Modules[0].Items) == 0 {
		t.Fatalf("expected corroborated recent fallback to remain visible, got %#v", payload)
	}
}

func TestFallbackPulseDoesNotCreateFailedRecommendationItems(t *testing.T) {
	modules, items := buildFallbackPulse("2026-06-20", []models.PulseTopic{
		{ID: "topic-ai", Name: "AI", Keywords: encodeKeywords([]string{"Agent", "RAG"})},
	}, []memoryPulseSignal{
		{Theme: "最近对话延展", Focus: "Go 语言工程实现", Keywords: []string{"Go", "接口", "测试"}},
	}, []string{"Go 语言工程实现 recent update 2026: agent returned status 502"})

	if len(modules) != 3 {
		t.Fatalf("expected module background explanations, got %#v", modules)
	}
	if len(items) != 0 {
		t.Fatalf("expected failed fallback to produce no recommendation items, got %#v", items)
	}
	if !strings.Contains(modules[0].Summary, "不展示推荐卡") {
		t.Fatalf("expected module summary to explain empty recommendation state, got %q", modules[0].Summary)
	}
}

func TestPulseRefreshKeepsExistingItemsWhenReplacementFails(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	date := "2026-06-20"
	now := time.Now()
	oldItem := models.PulseItem{
		ID:        "existing-pulse-item",
		UserID:    "0",
		Date:      date,
		Source:    pulseSourceMemory,
		Category:  "近日 Memory",
		Title:     "旧的 Pulse 内容",
		Summary:   "刷新失败时应该保留。",
		HeatScore: 70,
		CreatedAt: now,
		UpdatedAt: now,
	}
	oldModule := models.PulseModule{
		ID:        "existing-pulse-module",
		UserID:    "0",
		Date:      date,
		Key:       pulseSourceMemory,
		Title:     "旧模块",
		Summary:   "刷新失败时应该保留。",
		CreatedAt: now,
		UpdatedAt: now,
	}
	conflictingModule := models.PulseModule{
		ID:        pulseItemID(date, "module", pulseSourceTopicHot),
		UserID:    "other-user",
		Date:      date,
		Key:       pulseSourceTopicHot,
		Title:     "占用即将写入的 ID",
		Summary:   "触发事务写入失败。",
		CreatedAt: now,
		UpdatedAt: now,
	}
	if err := database.DB.Create(&[]models.PulseModule{oldModule, conflictingModule}).Error; err != nil {
		t.Fatalf("seed modules: %v", err)
	}
	if err := database.DB.Create(&oldItem).Error; err != nil {
		t.Fatalf("seed item: %v", err)
	}

	handler := NewPulseHandler()
	router := gin.New()
	router.POST("/api/pulse/refresh", handler.Refresh)

	refreshBody := bytes.NewBufferString(`{"date":"2026-06-20"}`)
	refreshReq := httptest.NewRequest(http.MethodPost, "/api/pulse/refresh?wait=true", refreshBody)
	refreshReq.Header.Set("Content-Type", "application/json")
	refreshRecorder := httptest.NewRecorder()
	router.ServeHTTP(refreshRecorder, refreshReq)
	if refreshRecorder.Code != http.StatusInternalServerError {
		t.Fatalf("expected refresh failure, got status %d: %s", refreshRecorder.Code, refreshRecorder.Body.String())
	}

	var keptItem models.PulseItem
	if err := database.DB.First(&keptItem, "id = ?", oldItem.ID).Error; err != nil {
		t.Fatalf("expected old item to remain after failed replacement: %v", err)
	}
	if keptItem.Title != oldItem.Title {
		t.Fatalf("unexpected kept item title: %q", keptItem.Title)
	}

	var keptModule models.PulseModule
	if err := database.DB.First(&keptModule, "id = ?", oldModule.ID).Error; err != nil {
		t.Fatalf("expected old module to remain after failed replacement: %v", err)
	}
}

func TestSearchFallbackClusterSummarizesNewsCluster(t *testing.T) {
	item := searchFallbackClusterItem("2026-06-20", pulseSearchEvidence{
		Module:    pulseSourceTopicHot,
		Query:     "AI GPT-5 latest news 2026",
		TopicName: "AI",
		Results: []pulseSearchResult{
			{
				Title:   "GPT-5.6 release reportedly adds terminal controls and longer context",
				Snippet: "OpenAI is expected to preview GPT-5.6 with terminal controls and longer context, but official timing is not confirmed.",
				URL:     "https://openai.com/news/gpt-56-release",
				Source:  "official",
			},
			{
				Title:   "OpenAI GPT-5.6 release preview with terminal controls points to August",
				Snippet: "The independent coverage describes the same expected GPT-5.6 preview with terminal controls, longer context, and developer availability.",
				URL:     "https://www.reuters.com/technology/openai-gpt-rumor",
				Source:  "web",
			},
		},
	}, 0)

	if strings.Contains(item.Title, "近期资讯聚合") || strings.Contains(strings.ToLower(item.Title), "latest news") {
		t.Fatalf("expected Chinese editorial title, got %q", item.Title)
	}
	if !strings.Contains(item.Title, "GPT") || !strings.Contains(item.Title, "发布计划") {
		t.Fatalf("expected a subject-and-event fallback title, got %q", item.Title)
	}
	if strings.HasPrefix(item.Summary, "聚合 ") || strings.Contains(item.Summary, "关键线索是") {
		t.Fatalf("expected integrated summary, got %q", item.Summary)
	}
	if strings.Contains(item.Summary, "GPT-5.6 reportedly supports") {
		t.Fatalf("summary should not concatenate source titles/snippets, got %q", item.Summary)
	}
	if !strings.Contains(item.Summary, "发布") || !strings.Contains(item.Summary, "版本") {
		t.Fatalf("expected summary to explain the actionable news angle, got %q", item.Summary)
	}
	if length := len([]rune(item.Summary)); length < pulseSummaryMinRunes || length > pulseSummaryMaxRunes {
		t.Fatalf("expected a %d-%d character cluster summary, got %d: %q", pulseSummaryMinRunes, pulseSummaryMaxRunes, length, item.Summary)
	}

	var detail pulseItemDetail
	if err := json.Unmarshal([]byte(item.DetailJSON), &detail); err != nil {
		t.Fatalf("decode detail: %v", err)
	}
	if !strings.Contains(detail.QuickContext, "独立来源互证") ||
		strings.Contains(detail.QuickContext, "Several reports say") ||
		strings.Contains(detail.QuickContext, "来源线索：") {
		t.Fatalf("expected compact evidence context without source snippets, got %q", detail.QuickContext)
	}
}

func TestPulseSearchRelevanceRejectsNoise(t *testing.T) {
	query := pulseSearchQuery{
		Module:    pulseSourceInterestHot,
		Query:     "Agent 工程实践 Dify RAG trend analysis 2026",
		TopicName: "Agent 工程实践",
	}
	relevant := pulseSearchResult{
		Title:   "Dify Agent RAG 工程实践复盘",
		Snippet: "围绕 Dify 知识库、Agent 工作流和 RAG 评测展开。",
		URL:     "https://example.com/dify-agent-rag",
	}
	noise := pulseSearchResult{
		Title:   "Homemade crispy french fries",
		Snippet: "A recipe with potatoes, oil, and salt.",
		URL:     "https://example.com/fries",
	}

	if score := pulseSearchResultRelevanceScore(query, relevant); score <= 0 {
		t.Fatalf("expected relevant result to score above zero, got %d", score)
	}
	if score := pulseSearchResultRelevanceScore(query, noise); score != 0 {
		t.Fatalf("expected unrelated result to be rejected, got score %d", score)
	}
}

func TestSearchFallbackMarksWeakSourceClusters(t *testing.T) {
	item := searchFallbackClusterItem("2026-06-20", pulseSearchEvidence{
		Module:    pulseSourceInterestHot,
		Query:     "Agent 工程实践 Dify RAG trend analysis 2026",
		TopicName: "Agent 工程实践",
		Results: []pulseSearchResult{
			{
				Title:   "Dify 三层知识库与工业级 RAG 实践",
				Snippet: "一篇围绕 Dify、Agent 和 RAG 的工程实践文章。",
				URL:     "https://blog.csdn.net/example/article/details/123",
				Source:  "minimax-mcp",
			},
			{
				Title:   "Dify Agent RAG 随笔",
				Snippet: "个人博客记录 Dify Agent 搭建过程。",
				URL:     "https://www.cnblogs.com/example/p/dify-agent-rag.html",
				Source:  "minimax-mcp",
			},
		},
	}, 0)

	if item.Title != "" || item.Summary != "" {
		t.Fatalf("weak opinion sources must not produce placeholder news copy, got %q / %q", item.Title, item.Summary)
	}
	if pulseNewsCopyMeetsQualityGate(item.Title, item.Summary) {
		t.Fatalf("weak-source fallback unexpectedly passed copy quality gate: %#v", item)
	}
}

func TestPulseSearchFallbackClustersRejectUncorroboratedResults(t *testing.T) {
	evidence := pulseSearchEvidence{
		Module:    pulseSourceTopicHot,
		Query:     "Agent RAG recent update 2026",
		TopicName: "Agent RAG",
		Results: []pulseSearchResult{
			{Title: "Agent RAG 工程实践一", URL: "https://example.com/agent-rag-1"},
			{Title: "Agent RAG 工程实践二", URL: "https://example.com/agent-rag-2"},
			{Title: "Agent RAG 工程实践三", URL: "https://example.com/agent-rag-3"},
			{Title: "Agent RAG 工程实践四", URL: "https://example.com/agent-rag-4"},
		},
	}

	clusters := pulseSearchFallbackClusters(evidence)
	if len(clusters) != 0 {
		t.Fatalf("expected uncorroborated results to produce no fallback clusters, got %#v", clusters)
	}
}

func TestPulseSearchFallbackClustersGroupsCorroboratedResultsFirst(t *testing.T) {
	evidence := pulseSearchEvidence{
		Module:    pulseSourceTopicHot,
		Query:     "Claude Code Gemini CLI agent harness recent update 2026",
		TopicName: "AI",
		Results: []pulseSearchResult{
			{
				Title:       "Anthropic launches Agent Harness 2.0 for Claude Code",
				Snippet:     "The Agent Harness 2.0 release adds shared controls for Claude Code and Gemini CLI.",
				URL:         "https://anthropic.com/news/agent-harness-2",
				Source:      "official",
				PublishedAt: "2026-06-19",
			},
			{
				Title:       "Agent Harness 2.0 launch adds Claude Code controls",
				Snippet:     "An independent report confirms the new Agent Harness 2.0 release for Claude Code.",
				URL:         "https://reuters.com/technology/anthropic-agent-harness-2",
				Source:      "Reuters",
				PublishedAt: "2026-06-18",
			},
			{
				Title:   "机器人供应链跟踪",
				Snippet: "与 Claude Code 无关的制造业信息。",
				URL:     "https://factory.example.org/robotics",
				Source:  "web",
			},
		},
	}

	clusters := pulseSearchFallbackClusters(evidence)
	if len(clusters) == 0 || len(clusters[0]) < 2 {
		t.Fatalf("expected corroborated cluster first, got %#v", clusters)
	}
	if got := pulseSearchIndependentSourceCount(clusters[0]); got < 2 {
		t.Fatalf("expected independent sources, got %d in %#v", got, clusters[0])
	}
	item := searchFallbackClusterItem("2026-06-20", pulseSearchEvidence{
		Module:    evidence.Module,
		Query:     evidence.Query,
		TopicName: evidence.TopicName,
		Results:   clusters[0],
	}, 0)
	if pulseItemLooksLowInformation(item) {
		t.Fatalf("expected corroborated fallback item to be visible, got %q / %q", item.Title, item.Summary)
	}
}

func TestSearchFallbackClusterEntitiesPreferSharedTerms(t *testing.T) {
	entities := searchFallbackClusterEntities(pulseSearchEvidence{
		Module:    pulseSourceTopicHot,
		Query:     "AI Agent RAG 多模态 模型 recent update 2026",
		TopicName: "AI",
	}, []pulseSearchResult{
		{
			Title:   "Agentic RAG 系统具备多模态推理",
			Snippet: "这篇文章顺带提到 xAI，但主体是 Agentic RAG 和多模态推理架构。",
			URL:     "https://news.example.com/agentic-rag",
		},
		{
			Title:   "多模态 RAG 笔记",
			Snippet: "课程记录多模态检索增强生成 RAG 系统实现。",
			URL:     "https://docs.example.org/multimodal-rag",
		},
		{
			Title:   "OpenClaw 多模态推理",
			Snippet: "多模态推理和知识图谱融合实践。",
			URL:     "https://blog.example.net/openclaw",
		},
		{
			Title:   "xAI",
			Snippet: "Company homepage.",
			URL:     "https://x.ai/",
		},
	})

	joined := strings.Join(entities, " ")
	if strings.Contains(joined, "xAI") {
		t.Fatalf("expected one-off xAI mention to stay out of shared entities, got %#v", entities)
	}
	if !strings.Contains(joined, "RAG") && !strings.Contains(joined, "多模态") {
		t.Fatalf("expected shared RAG or multimodal terms, got %#v", entities)
	}
}

func TestPulseSearchEvidenceUsesTwoDiscoveryQueriesAndOneEventFollowupPerKeyword(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	requestCount := 0
	var requestMu sync.Mutex
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/agent/search" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		var req bridge.SearchRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		requestMu.Lock()
		requestCount++
		requestMu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		subject := "Claude Code"
		slug := "claude-code"
		if strings.Contains(strings.ToLower(req.Query), "gemini") {
			subject = "Gemini CLI"
			slug = "gemini-cli"
		}
		results := []bridge.SearchResult{
			{
				Title:   "Model vendor launches Agent Harness 2.0 for " + subject,
				Snippet: "The Agent Harness 2.0 release adds shared controls for " + subject + ".",
				URL:     "https://github.com/duanyytop/agents-radar/issues/" + slug,
				Source:  "github",
			},
		}
		_ = json.NewEncoder(w).Encode(bridge.SearchResponse{
			Query:   req.Query,
			Sources: []string{"web"},
			Results: results,
			TraceNodes: []map[string]interface{}{{
				"node": "query_rewrite",
				"queries": []string{
					req.Query + " latest product updates",
					"最新 " + req.Query + " 产品动态",
				},
			}},
		})
	}))
	defer agentServer.Close()

	handler := NewPulseHandler(bridge.NewAgentClient(agentServer.URL, time.Second))
	evidence, searchErrors := handler.collectPulseSearchEvidence(context.Background(), "2026-06-20", []models.PulseTopic{
		{ID: "topic-ai", Name: "AI 工程", Keywords: encodeKeywords([]string{"Claude Code", "Gemini CLI"})},
	}, nil)
	if len(searchErrors) != 0 {
		t.Fatalf("expected no search errors, got %#v", searchErrors)
	}
	if requestCount != 6 {
		t.Fatalf("expected four discovery requests and two event follow-ups, got %d", requestCount)
	}
	stageCounts := map[string]int{}
	for _, item := range evidence {
		stageCounts[item.Stage]++
		if item.Keyword == "" {
			t.Fatalf("expected keyword attribution on every query, got %#v", item)
		}
		if item.Stage == "followup" && item.ParentQueryID == "" {
			t.Fatalf("expected event follow-up to reference its discovery query, got %#v", item)
		}
		if len(item.RewrittenQueries) != 2 {
			t.Fatalf("expected SearchService rewrite variants to be retained, got %#v", item)
		}
	}
	if stageCounts["initial"] != 4 || stageCounts["followup"] != 2 {
		t.Fatalf("unexpected two-stage evidence shape: %#v", stageCounts)
	}
}

func TestSearchFallbackMarksSingleSourceAsUnverified(t *testing.T) {
	item := searchFallbackClusterItem("2026-06-20", pulseSearchEvidence{
		Module:    pulseSourceTopicHot,
		Query:     "Agent RAG recent update",
		TopicName: "Agent 工程实践",
		Results: []pulseSearchResult{
			{
				Title:   "Agent RAG 工程实践发布新案例",
				Snippet: "A single source mentions a recent Agent RAG implementation update.",
				URL:     "https://example.com/agent-rag-update",
				Source:  "web",
			},
		},
	}, 0)

	if item.Title != "" || item.Summary != "" {
		t.Fatalf("single-source fallback must not produce placeholder news copy, got %q / %q", item.Title, item.Summary)
	}
	var detail pulseItemDetail
	if err := json.Unmarshal([]byte(item.DetailJSON), &detail); err != nil {
		t.Fatalf("decode detail: %v", err)
	}
	if !strings.Contains(detail.RecommendationReason, "一条外网线索") {
		t.Fatalf("expected cautious recommendation reason, got %q", detail.RecommendationReason)
	}
}

func TestGeneratedPulseRewritesSearchDumpCopy(t *testing.T) {
	payload := generatedPulsePayload{
		Modules: []generatedPulseModule{
			{
				Key:     pulseSourceTopicHot,
				Title:   "你的 AI 订阅",
				Summary: "根据订阅生成。",
				Items: []generatedPulseItem{
					{
						TopicName: "AI",
						Category:  "关注 Topic",
						Title:     "「AI」近期资讯聚合：GPT-5 The Latest News on AI - the latest information on machine learning",
						Summary:   "聚合 3 条来源，关键线索是：GPT-5 The Latest News on AI，Anthropic Announces Claude Fable 5。",
						HeatScore: 92,
						NewsSources: []pulseNewsSource{
							{
								Title:   "OpenAI releases GPT-5.6 with longer context and new tool use",
								Snippet: "OpenAI released GPT-5.6 with longer context, new tool use controls, and phased API access.",
								URL:     "https://openai.com/news/gpt-56-release",
								Source:  "official",
							},
							{
								Title:   "GPT-5.6 launch adds longer context and phased API access",
								Snippet: "An independent report confirms the same GPT-5.6 launch, including longer context and phased API availability.",
								URL:     "https://reuters.com/technology/openai-gpt-56-release",
								Source:  "Reuters",
							},
						},
					},
				},
			},
		},
	}

	_, items := generatedPayloadToModels("2026-06-20", payload, nil)
	if len(items) != 1 {
		t.Fatalf("expected one item, got %#v", items)
	}
	if strings.Contains(items[0].Title, "近期资讯聚合") || strings.Contains(strings.ToLower(items[0].Title), "latest news") {
		t.Fatalf("expected rewritten title, got %q", items[0].Title)
	}
	if strings.HasPrefix(items[0].Summary, "聚合 ") || strings.Contains(items[0].Summary, "关键线索是") {
		t.Fatalf("expected rewritten summary, got %q", items[0].Summary)
	}
	if length := len([]rune(items[0].Summary)); length < pulseSummaryMinRunes || length > pulseSummaryMaxRunes {
		t.Fatalf("expected rewritten cluster summary to contain %d-%d characters, got %d: %q", pulseSummaryMinRunes, pulseSummaryMaxRunes, length, items[0].Summary)
	}
}

func writePulseTestSearchResponse(w http.ResponseWriter, r *http.Request) {
	var req bridge.SearchRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(bridge.SearchResponse{
		Query:   req.Query,
		Sources: []string{"web"},
		Results: []bridge.SearchResult{
			{
				Title:   "机器人与具身智能 RoboControl-7 控制器发布",
				Snippet: "RoboControl-7 控制器完成发布，用于验证 Pulse 生成链路会接收同一事件的外网检索证据。",
				URL:     "https://example.com/robotics-latest",
				Source:  "web",
				Metadata: map[string]interface{}{
					"rank":         1,
					"published_at": "2026-06-19",
				},
			},
			{
				Title:   "独立报道确认 RoboControl-7 机器人控制器发布",
				Snippet: "另一家独立来源确认 RoboControl-7 控制器完成同一次发布，用于交叉核验。",
				URL:     "https://reuters.com/technology/robocontrol-7-launch",
				Source:  "Reuters",
				Metadata: map[string]interface{}{
					"rank":         2,
					"published_at": "2026-06-18",
				},
			},
		},
	})
}

func pulseTestVerifiedDetail(date string) string {
	reference, err := time.Parse("2006-01-02", date)
	if err != nil {
		reference = time.Now().UTC()
	}
	return mustJSON(pulseItemDetail{
		RecommendationReason: "两个近期独立来源共同确认。",
		QuickContext:         "官方来源与独立报道可以交叉核验。",
		KeyPoints:            []string{"近期更新", "独立互证"},
		NewsSources: []pulseNewsSource{
			{
				Title:       "OpenAI releases AgentGuard-2 permission controls",
				URL:         "https://openai.com/news/verified-update",
				PublishedAt: reference.Add(-24 * time.Hour).Format("2006-01-02"),
			},
			{
				Title:       "Report confirms AgentGuard-2 permission controls release",
				URL:         "https://reuters.com/technology/verified-update",
				PublishedAt: reference.Add(-48 * time.Hour).Format("2006-01-02"),
			},
		},
	})
}

func pulseTestLongSummary(subject string) string {
	return subject + "已在近期正式发布，官方材料说明了产品范围、开放对象和主要能力。独立报道确认了同一次发布的主体、版本和时间线，并补充了企业用户接入与部署时需要注意的条件。两个来源对核心事实的表述一致，差异主要在于官方更强调功能设计，媒体更关注实际应用和风险边界。对正在评估这项能力的团队，后续应继续核对实际权限、兼容性和上线成本。"
}

func TestPulseRejectsInvalidDate(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	router := gin.New()
	router.GET("/api/pulse", NewPulseHandler().Get)

	req := httptest.NewRequest(http.MethodGet, "/api/pulse?date=tomorrow", nil)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusBadRequest {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	if !strings.Contains(recorder.Body.String(), "invalid date") {
		t.Fatalf("expected date error, got %s", recorder.Body.String())
	}
}
