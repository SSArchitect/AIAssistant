package handlers

import (
	"bytes"
	"encoding/json"
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
		if !strings.Contains(contextText, "search_evidence") || !strings.Contains(contextText, "https://example.com/robotics-latest") {
			t.Fatalf("expected search evidence in generation context, got %s", contextText)
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
	response, err := handler.requestPulseChat("pulse-acct-a-2026-07-06", "acct-a", "generate pulse", []string{"system"}, []string{"context"})
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
			Summary:    "OpenAI 发布 AgentGuard-2，并新增企业权限控制。",
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
			Summary:    "OpenAI 开放 AgentGuard-2 审计日志，并支持企业客户接入。",
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
			Summary:    "OpenAI 发布 AgentGuard-2，并新增企业权限控制。",
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
			Summary:    "Anthropic 发布 Claude 企业审计功能，并开放管理员接入。",
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

func TestPulseRecommendedItemsFiltersConsumedClusters(t *testing.T) {
	sameCluster := models.PulseItem{
		ID:         "same-cluster",
		Date:       "2026-06-20",
		Title:      "OpenAI 发布 AgentGuard-2 权限控制",
		Summary:    "OpenAI 发布 AgentGuard-2，并新增企业权限控制。",
		Source:     pulseSourceTopicHot,
		TopicName:  "AI",
		HeatScore:  96,
		DetailJSON: pulseTestVerifiedDetail("2026-06-20"),
	}
	clusterKey := pulseClusterKey(sameCluster)
	if clusterKey == "" {
		t.Fatal("expected cluster key")
	}
	items := []models.PulseItem{
		{ID: "fresh", Date: "2026-06-20", Source: pulseSourceTopicHot, Title: "OpenAI 发布 AgentGuard-2 审计日志", Summary: "OpenAI 发布 AgentGuard-2 审计日志，并开放企业接入。", HeatScore: 80, DetailJSON: pulseTestVerifiedDetail("2026-06-20")},
		{ID: "opened", Date: "2026-06-20", Source: pulseSourceTopicHot, Title: "OpenAI 推出 AgentGuard-2 管理后台", Summary: "OpenAI 推出 AgentGuard-2 管理后台，并新增权限配置。", HeatScore: 99, DetailJSON: pulseTestVerifiedDetail("2026-06-20")},
		{ID: "seen", Date: "2026-06-20", Source: pulseSourceTopicHot, Title: "OpenAI 更新 AgentGuard-2 企业策略", Summary: "OpenAI 更新 AgentGuard-2 企业策略，并扩展管理员控制。", HeatScore: 98, DetailJSON: pulseTestVerifiedDetail("2026-06-20")},
		{ID: "down", Date: "2026-06-20", Source: pulseSourceTopicHot, Title: "OpenAI 开放 AgentGuard-2 团队权限", Summary: "OpenAI 开放 AgentGuard-2 团队权限，并支持成员分组。", HeatScore: 97, DetailJSON: pulseTestVerifiedDetail("2026-06-20")},
		sameCluster,
	}
	state := pulseFeatureState{
		feedbackByItem: map[string]pulseItemFeedbackResponse{
			"opened": {OpenCount: pulseOpenFilterThreshold},
			"seen":   {ExposureCount: pulseExposureFilterThreshold},
			"down":   {Vote: "down", DownvoteCount: 1},
		},
		feedbackByKey: map[string]pulseItemFeedbackResponse{
			clusterKey: {OpenCount: pulseOpenFilterThreshold},
		},
		directScores:  map[string]int{},
		clusterScores: map[string]int{},
		topicScores:   map[string]int{},
		sourceScores:  map[string]int{},
	}

	recommended := recommendedPulseItems(items, state)
	if len(recommended) != 1 || recommended[0].ID != "fresh" {
		t.Fatalf("expected only fresh item after feature filtering, got %#v", recommended)
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
		{ID: "topic-ai", Name: "AI", Keywords: encodeKeywords([]string{"Agent", "RAG"}), Enabled: true},
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
				Title:   "GPT-5.6 reportedly supports longer context and new tool use",
				Snippet: "Several reports say OpenAI is expected to release GPT-5.6 later this year, but official timing is not confirmed.",
				URL:     "https://example.com/gpt-56-release",
				Source:  "web",
			},
			{
				Title:   "OpenAI GPT-5.6 release date rumors point to an August preview",
				Snippet: "The coverage focuses on possible launch timing, version naming, and availability for developers.",
				URL:     "https://example.com/openai-gpt-rumor",
				Source:  "web",
			},
			{
				Title:   "Anthropic unveils Claude Fable 5 with restricted access",
				Snippet: "Anthropic's model update highlights safety guardrails, access limits, and frontier capability claims.",
				URL:     "https://example.com/claude-fable-5",
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
				URL:         "https://github.com/duanyytop/agents-radar/issues/1280",
				Source:      "github",
				PublishedAt: "2026-06-19",
			},
			{
				Title:       "Agent Harness 2.0 launch adds Claude Code controls",
				Snippet:     "An independent report confirms the new Agent Harness 2.0 release for Claude Code.",
				URL:         "https://research.example.org/agent-harness-claude-gemini",
				Source:      "web",
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

func TestPulseSearchEvidenceFollowupAddsCorroboratingResults(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/agent/search" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		var req bridge.SearchRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		results := []bridge.SearchResult{
			{
				Title:   "Anthropic launches Agent Harness 2.0 for Claude Code",
				Snippet: "The Agent Harness 2.0 release adds shared controls for Claude Code and Gemini CLI.",
				URL:     "https://github.com/duanyytop/agents-radar/issues/1280",
				Source:  "github",
			},
		}
		if req.Limit == pulseSearchFollowupResultLimit {
			results = []bridge.SearchResult{
				{
					Title:   "Agent Harness 2.0 launch adds Claude Code controls",
					Snippet: "An independent report confirms the new Agent Harness 2.0 release for Claude Code.",
					URL:     "https://research.example.org/agent-harness-claude-gemini",
					Source:  "web",
				},
			}
		}
		_ = json.NewEncoder(w).Encode(bridge.SearchResponse{
			Query:   req.Query,
			Sources: []string{"web"},
			Results: results,
		})
	}))
	defer agentServer.Close()

	handler := NewPulseHandler(bridge.NewAgentClient(agentServer.URL, time.Second))
	evidence, searchErrors := handler.collectPulseSearchEvidence("2026-06-20", []models.PulseTopic{
		{ID: "topic-ai", Name: "AI 工程", Keywords: encodeKeywords([]string{"Claude Code", "Gemini CLI"}), Enabled: true},
	}, nil)
	if len(searchErrors) != 0 {
		t.Fatalf("expected no search errors, got %#v", searchErrors)
	}
	for _, item := range evidence {
		if pulseSearchIndependentSourceCount(item.Results) >= 2 {
			return
		}
	}
	t.Fatalf("expected follow-up search to add an independent corroborating source, got %#v", evidence)
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
								Title:   "GPT-5.6 reportedly supports longer context and new tool use",
								Snippet: "OpenAI is expected to release GPT-5.6 later this year, but official timing is not confirmed.",
								URL:     "https://example.com/gpt-56-release",
								Source:  "web",
							},
							{
								Title:   "Anthropic unveils Claude Fable 5 with restricted access",
								Snippet: "Anthropic's model update highlights safety guardrails and access limits.",
								URL:     "https://example.com/claude-fable-5",
								Source:  "web",
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
	if strings.Contains(items[0].Summary, "核验") ||
		strings.Contains(items[0].Summary, "推荐") ||
		strings.Count(items[0].Summary, "。") > 2 {
		t.Fatalf("expected summary to contain only one or two news-content sentences, got %q", items[0].Summary)
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
				URL:     "https://industry.example.org/robotics-latest",
				Source:  "web",
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
