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
			"response": "{\"modules\":[{\"key\":\"topic_hot\",\"title\":\"你的机器人订阅今日追踪\",\"summary\":\"围绕具身智能订阅生成。\",\"items\":[{\"topic_name\":\"机器人\",\"category\":\"关注 Topic\",\"title\":\"具身智能项目今天该看什么\",\"summary\":\"一条来自 Agent 的个性化 topic 推荐。\",\"heat_score\":88,\"recommendation_reason\":\"因为你订阅了机器人。\",\"signals\":[\"搜索来源：机器人与具身智能出现新进展 - https://example.com/robotics-latest\"],\"quick_context\":\"先看产业化落地。\",\"key_points\":[\"供应链\",\"场景\",\"成本\"],\"suggested_questions\":[\"具身智能近期有什么变化？\",\"我该看哪些公司？\",\"有哪些风险？\"],\"explore_prompt\":\"展开具身智能今日推荐\"}]},{\"key\":\"memory\",\"title\":\"延续你的最近对话\",\"summary\":\"根据最近 memory 生成。\",\"items\":[{\"category\":\"近日 Memory\",\"title\":\"继续整理 AI 工作台想法\",\"summary\":\"一条 memory 推荐。\",\"heat_score\":77,\"recommendation_reason\":\"最近多次讨论工作台。\",\"signals\":[\"搜索来源：机器人与具身智能出现新进展 - https://example.com/robotics-latest\"],\"quick_context\":\"把想法落为功能。\",\"key_points\":[\"结构\",\"验证\",\"迭代\"],\"suggested_questions\":[\"下一步做什么？\",\"怎么验证？\",\"如何排优先级？\"],\"explore_prompt\":\"继续整理工作台想法\"}]},{\"key\":\"interest_hot\",\"title\":\"你可能会关心的热门延伸\",\"summary\":\"结合订阅和 memory 生成。\",\"items\":[{\"category\":\"可能兴趣\",\"title\":\"AI 硬件生态为什么值得跟踪\",\"summary\":\"一条兴趣热门推荐。\",\"heat_score\":74,\"recommendation_reason\":\"由机器人和 AI 信号外扩。\",\"signals\":[\"搜索来源：机器人与具身智能出现新进展 - https://example.com/robotics-latest\"],\"quick_context\":\"关注硬件生态。\",\"key_points\":[\"芯片\",\"终端\",\"应用\"],\"suggested_questions\":[\"为什么值得跟？\",\"有哪些公司？\",\"有什么风险？\"],\"explore_prompt\":\"展开 AI 硬件生态\"}]}]}",
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
	if len(payload.Modules[0].Items) != 1 || payload.Modules[0].Items[0].Title != "具身智能项目今天该看什么" {
		t.Fatalf("expected agent-generated topic item, got %#v", payload.Modules[0].Items)
	}
	if got := payload.Modules[0].Items[0].Detail.SuggestedQuestions; len(got) < 3 || got[0] == "" || !strings.Contains(strings.Join(got, "\n"), "具身智能") {
		t.Fatalf("expected suggested questions, got %#v", got)
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
				Response:       `{"modules":[{"key":"topic_hot","title":"同步后的 Topic","summary":"已同步配置后生成。","items":[{"topic_name":"机器人","category":"关注 Topic","title":"同步后生成 topic 推荐","summary":"配置同步后，Agent 可以正常生成。","heat_score":88,"recommendation_reason":"因为你订阅了机器人。","signals":["搜索来源：机器人与具身智能出现新进展 - https://example.com/robotics-latest"],"quick_context":"先看配置同步是否生效。","key_points":["配置","检索","生成"],"suggested_questions":["机器人这条来源说了什么？","怎么核验具身智能进展？","后续跟踪哪些公司？"],"explore_prompt":"展开同步测试"}]},{"key":"memory","title":"同步后的 Memory","summary":"保持模块完整。","items":[{"category":"近日 Memory","title":"同步后生成 memory 推荐","summary":"配置同步后继续生成。","heat_score":76,"recommendation_reason":"最近在看 Pulse。","signals":["搜索来源：机器人与具身智能出现新进展 - https://example.com/robotics-latest"],"quick_context":"确认模块完整。","key_points":["配置","候选","过滤"],"suggested_questions":["Pulse 配置同步怎么验证？","候选池怎么补满？","过滤逻辑怎么评估？"],"explore_prompt":"展开 memory"}]},{"key":"interest_hot","title":"同步后的兴趣延伸","summary":"保持模块完整。","items":[{"category":"可能兴趣","title":"同步后生成兴趣推荐","summary":"配置同步后兴趣延伸可生成。","heat_score":72,"recommendation_reason":"机器人与 AI 相关。","signals":["搜索来源：机器人与具身智能出现新进展 - https://example.com/robotics-latest"],"quick_context":"确认兴趣模块完整。","key_points":["兴趣","外扩","来源"],"suggested_questions":["这条兴趣推荐依据是什么？","有哪些外部来源？","下一步追什么？"],"explore_prompt":"展开兴趣"}]}]}`,
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
			Title:      "高热但未反馈的信息簇",
			Summary:    "基础热度更高。",
			HeatScore:  90,
			DetailJSON: mustJSON(pulseItemDetail{KeyPoints: []string{"高热"}}),
			CreatedAt:  now,
			UpdatedAt:  now,
		},
		{
			ID:         "pulse-liked",
			UserID:     "0",
			Date:       date,
			Source:     pulseSourceTopicHot,
			Category:   "关注 Topic",
			Title:      "用户点赞的信息簇",
			Summary:    "基础热度略低，但用户反馈更强。",
			HeatScore:  70,
			DetailJSON: mustJSON(pulseItemDetail{KeyPoints: []string{"点赞"}}),
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
			Title:      "新的同 Topic 信息簇",
			Summary:    "基础热度略低，但应继承 topic 偏好。",
			HeatScore:  70,
			DetailJSON: mustJSON(pulseItemDetail{KeyPoints: []string{"同 topic"}}),
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
			Title:      "新的其他信息簇",
			Summary:    "基础热度更高。",
			HeatScore:  78,
			DetailJSON: mustJSON(pulseItemDetail{KeyPoints: []string{"其他 topic"}}),
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
		Title:      "同一资讯簇",
		Source:     pulseSourceTopicHot,
		TopicName:  "AI",
		HeatScore:  96,
		DetailJSON: mustJSON(pulseItemDetail{NewsSources: []pulseNewsSource{{Title: "来源", URL: "https://example.com/a"}}}),
	}
	clusterKey := pulseClusterKey(sameCluster)
	if clusterKey == "" {
		t.Fatal("expected cluster key")
	}
	items := []models.PulseItem{
		{ID: "fresh", Title: "新候选", HeatScore: 80},
		{ID: "opened", Title: "已打开", HeatScore: 99},
		{ID: "seen", Title: "多次曝光", HeatScore: 98},
		{ID: "down", Title: "点踩", HeatScore: 97},
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
	detail := mustJSON(pulseItemDetail{NewsSources: []pulseNewsSource{{Title: "来源", URL: "https://example.com/a"}}})
	items := []models.PulseItem{
		{ID: "lower", Title: "同一资讯簇", Source: pulseSourceTopicHot, TopicName: "AI", HeatScore: 80, DetailJSON: detail},
		{ID: "higher", Title: "同一资讯簇", Source: pulseSourceTopicHot, TopicName: "AI", HeatScore: 96, DetailJSON: detail},
		{ID: "other", Title: "另一个资讯簇", Source: pulseSourceTopicHot, TopicName: "AI", HeatScore: 70},
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
			{Title: "官方发布", URL: "https://example.com/official"},
			{Title: "开发者文档", URL: "https://example.com/docs"},
		},
	})
	items := []models.PulseItem{
		{ID: "low-info", Title: "AI 模型进展：GPT-RAG、Claude Code、Gemini CLI 待核验线索", Summary: "单一来源提到AI 模型进展，但不足以判断为热点或趋势。", Source: pulseSourceTopicHot, TopicName: "AI", HeatScore: 99, DetailJSON: lowInfoDetail},
		{ID: "strong", Title: "AI 模型进展：官方发布多来源确认", Summary: "官方发布和文档同步更新。", Source: pulseSourceTopicHot, TopicName: "AI", HeatScore: 70, DetailJSON: strongDetail},
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
			response = `{"modules":[{"key":"topic_hot","title":"修复后的机器人订阅","summary":"根据订阅 topic 生成。","items":[{"topic_name":"机器人","category":"关注 Topic","title":"机器人产业链今日入口","summary":"修复后的 topic 推荐。","heat_score":86,"recommendation_reason":"你订阅了机器人。","signals":["搜索来源：机器人与具身智能出现新进展 - https://example.com/robotics-latest"],"quick_context":"从产业链进展切入。","key_points":["供应链","场景","成本"],"suggested_questions":["最近有哪些进展？","哪些公司值得看？","风险是什么？"],"explore_prompt":"展开机器人产业链"}]},{"key":"memory","title":"修复后的近日记忆","summary":"根据近期工程化对话生成。","items":[{"category":"近日 Memory","title":"继续推进 Pulse 预计算","summary":"修复后的 memory 推荐。","heat_score":78,"recommendation_reason":"最近正在做 Pulse。","signals":["搜索来源：机器人与具身智能出现新进展 - https://example.com/robotics-latest"],"quick_context":"把推荐链路产品化。","key_points":["定时","可解释","追问"],"suggested_questions":["怎么设计定时任务？","如何解释推荐？","怎么评估点击？"],"explore_prompt":"继续推进 Pulse 预计算"}]},{"key":"interest_hot","title":"修复后的兴趣延伸","summary":"结合机器人与 AI 外扩。","items":[{"category":"可能兴趣","title":"具身智能 Agent 值得跟踪","summary":"修复后的兴趣推荐。","heat_score":74,"recommendation_reason":"由机器人和 AI 信号外扩。","signals":["搜索来源：机器人与具身智能出现新进展 - https://example.com/robotics-latest"],"quick_context":"关注具身智能产品化。","key_points":["模型","硬件","数据"],"suggested_questions":["为什么值得跟？","有什么落地场景？","成本瓶颈在哪？"],"explore_prompt":"展开具身智能 Agent"}]}]}`
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

func TestPulseFallsBackToPerModuleGeneration(t *testing.T) {
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
		if strings.Contains(req.Message, "修复 Broken Pulse JSON") {
			http.Error(w, "repair unavailable", http.StatusInternalServerError)
			return
		}

		response := `{"modules":[{"key":"topic_hot","title":"坏 JSON" "summary":"缺逗号","items":[]}]}`
		switch {
		case strings.Contains(req.Message, "key=topic_hot"):
			response = `{"key":"topic_hot","title":"单模块 Topic 生成","summary":"围绕机器人订阅生成。","items":[{"topic_name":"机器人","category":"关注 Topic","title":"机器人 topic 单模块推荐","summary":"来自单模块路径。","heat_score":86,"recommendation_reason":"你订阅了机器人。","signals":["搜索来源：机器人与具身智能出现新进展 - https://example.com/robotics-latest"],"quick_context":"从产业链切入。","key_points":["供应链","场景","成本"],"suggested_questions":["最近有哪些进展？","哪些公司值得看？","风险是什么？"],"explore_prompt":"展开机器人 topic"}]}`
		case strings.Contains(req.Message, "key=memory"):
			response = `{"key":"memory","title":"单模块 Memory 生成","summary":"根据近期 Pulse 对话生成。","items":[{"category":"近日 Memory","title":"Pulse 单模块链路","summary":"继续推进预计算。","heat_score":78,"recommendation_reason":"最近正在改 Pulse。","signals":["搜索来源：机器人与具身智能出现新进展 - https://example.com/robotics-latest"],"quick_context":"把推荐链路产品化。","key_points":["定时","可解释","追问"],"suggested_questions":["怎么设计定时？","如何解释推荐？","怎么评估点击？"],"explore_prompt":"展开 Pulse 单模块链路"}]}`
		case strings.Contains(req.Message, "key=interest_hot"):
			response = `{"key":"interest_hot","title":"单模块兴趣延伸","summary":"结合机器人与 AI 外扩。","items":[{"category":"可能兴趣","title":"具身智能 Agent 跟踪","summary":"由兴趣信号外扩。","heat_score":74,"recommendation_reason":"机器人和 AI 信号相关。","signals":["搜索来源：机器人与具身智能出现新进展 - https://example.com/robotics-latest"],"quick_context":"关注具身智能产品化。","key_points":["模型","硬件","数据"],"suggested_questions":["为什么值得跟？","有什么落地场景？","成本瓶颈在哪？"],"explore_prompt":"展开具身智能 Agent"}]}`
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
	if callCount != 5 {
		t.Fatalf("expected full generation, repair, and 3 module calls; got %d", callCount)
	}

	var payload struct {
		Modules []pulseModuleResponse `json:"modules"`
	}
	if err := json.Unmarshal(refreshRecorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode pulse response: %v", err)
	}
	if len(payload.Modules) != 3 {
		t.Fatalf("expected 3 modules, got %#v", payload.Modules)
	}
	if payload.Modules[0].Title != "单模块 Topic 生成" {
		t.Fatalf("expected per-module topic title, got %#v", payload.Modules[0])
	}
	if payload.Modules[2].Title != "单模块兴趣延伸" {
		t.Fatalf("expected per-module interest title, got %#v", payload.Modules[2])
	}
}

func TestPulseHidesLowInformationSearchFallbackWhenGenerationFails(t *testing.T) {
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
	if payload.RecommendedCount != 0 || len(payload.Items) != 0 || len(payload.Modules[0].Items) != 0 {
		t.Fatalf("expected low-information single-source fallback to stay out of visible recommendations, got %#v", payload)
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
	if !strings.Contains(item.Title, "AI 模型进展") || !strings.Contains(item.Title, "GPT") {
		t.Fatalf("expected model-focused fallback title, got %q", item.Title)
	}
	if strings.HasPrefix(item.Summary, "聚合 ") || strings.Contains(item.Summary, "关键线索是") {
		t.Fatalf("expected integrated summary, got %q", item.Summary)
	}
	if strings.Contains(item.Summary, "GPT-5.6 reportedly supports") {
		t.Fatalf("summary should not concatenate source titles/snippets, got %q", item.Summary)
	}
	if !strings.Contains(item.Summary, "发布时间") || !strings.Contains(item.Summary, "版本") {
		t.Fatalf("expected summary to explain the actionable news angle, got %q", item.Summary)
	}

	var detail pulseItemDetail
	if err := json.Unmarshal([]byte(item.DetailJSON), &detail); err != nil {
		t.Fatalf("decode detail: %v", err)
	}
	if !strings.HasPrefix(detail.QuickContext, "综合判断：") {
		t.Fatalf("expected synthesized quick context, got %q", detail.QuickContext)
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

	if !strings.Contains(item.Title, "待核验线索") {
		t.Fatalf("expected weak-source title to be cautious, got %q", item.Title)
	}
	if !strings.Contains(item.Summary, "弱证据") || !strings.Contains(item.Summary, "不足以判断") {
		t.Fatalf("expected weak-source summary to avoid trend framing, got %q", item.Summary)
	}
}

func TestPulseSearchFallbackClustersExposeIndividualResults(t *testing.T) {
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
	if len(clusters) != len(evidence.Results) {
		t.Fatalf("expected one fallback candidate per search result, got %#v", clusters)
	}
	for index, cluster := range clusters {
		if len(cluster) != 1 || cluster[0].URL != evidence.Results[index].URL {
			t.Fatalf("expected singleton cluster at %d, got %#v", index, cluster)
		}
	}
}

func TestPulseSearchFallbackClustersGroupsCorroboratedResultsFirst(t *testing.T) {
	evidence := pulseSearchEvidence{
		Module:    pulseSourceTopicHot,
		Query:     "Claude Code Gemini CLI agent harness recent update 2026",
		TopicName: "AI",
		Results: []pulseSearchResult{
			{
				Title:   "Claude Code and Gemini CLI agent harness trends",
				Snippet: "Agent harness patterns for Claude Code, Codex and Gemini CLI are gaining traction.",
				URL:     "https://github.com/duanyytop/agents-radar/issues/1280",
				Source:  "github",
			},
			{
				Title:   "Agent harness adoption for Claude Code and Gemini CLI",
				Snippet: "A separate analysis tracks Claude Code and Gemini CLI performance optimization layers.",
				URL:     "https://research.example.org/agent-harness-claude-gemini",
				Source:  "web",
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
				Title:   "Claude Code and Gemini CLI agent harness trends",
				Snippet: "Agent harness patterns for Claude Code, Codex and Gemini CLI are gaining traction.",
				URL:     "https://github.com/duanyytop/agents-radar/issues/1280",
				Source:  "github",
			},
		}
		if req.Limit == pulseSearchFollowupResultLimit {
			results = []bridge.SearchResult{
				{
					Title:   "Agent harness adoption for Claude Code and Gemini CLI",
					Snippet: "A separate analysis tracks Claude Code and Gemini CLI performance optimization layers.",
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

	if !strings.Contains(item.Title, "待核验线索") {
		t.Fatalf("expected single-source title to be cautious, got %q", item.Title)
	}
	if !strings.Contains(item.Summary, "单一来源") || !strings.Contains(item.Summary, "不足以判断") {
		t.Fatalf("expected single-source summary to avoid trend framing, got %q", item.Summary)
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
	if !strings.Contains(items[0].Summary, "核验") {
		t.Fatalf("expected rewritten summary to mention verification, got %q", items[0].Summary)
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
				Title:   "机器人与具身智能出现新进展",
				Snippet: "测试搜索结果摘要，用于验证 Pulse 生成链路会接收外网检索证据。",
				URL:     "https://example.com/robotics-latest",
				Source:  "web",
				Metadata: map[string]interface{}{
					"rank": 1,
				},
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
