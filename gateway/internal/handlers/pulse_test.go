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

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/database"
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
	refreshReq := httptest.NewRequest(http.MethodPost, "/api/pulse/refresh", refreshBody)
	refreshReq.Header.Set("Content-Type", "application/json")
	refreshRecorder := httptest.NewRecorder()
	router.ServeHTTP(refreshRecorder, refreshReq)
	if refreshRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected refresh status %d: %s", refreshRecorder.Code, refreshRecorder.Body.String())
	}

	var payload struct {
		Date   string               `json:"date"`
		Topics []pulseTopicResponse `json:"topics"`
		Items  []pulseItemResponse  `json:"items"`
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
	if len(payload.Items) < 4 {
		t.Fatalf("expected topic plus hot items, got %d", len(payload.Items))
	}

	foundTopicItem := false
	foundMemoryItem := false
	foundInterestHotItem := false
	for _, item := range payload.Items {
		if item.Source == pulseSourceMemory {
			foundMemoryItem = true
		}
		if item.Source == pulseSourceInterestHot {
			foundInterestHotItem = true
		}
		if item.TopicName == "机器人" {
			foundTopicItem = true
			if item.Source != pulseSourceTopicHot {
				t.Fatalf("expected topic item source %q, got %#v", pulseSourceTopicHot, item)
			}
			if item.Detail.RecommendationReason == "" || len(item.Detail.Signals) == 0 || item.Detail.QuickContext == "" || len(item.Detail.KeyPoints) == 0 || item.ExplorePrompt == "" {
				t.Fatalf("topic item was not precomputed: %#v", item)
			}
		}
	}
	if !foundTopicItem {
		t.Fatalf("expected a pulse item for created topic, got %#v", payload.Items)
	}
	if !foundMemoryItem {
		t.Fatalf("expected a memory module item, got %#v", payload.Items)
	}
	if !foundInterestHotItem {
		t.Fatalf("expected an interest-hot module item, got %#v", payload.Items)
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
	refreshReq := httptest.NewRequest(http.MethodPost, "/api/pulse/refresh", refreshBody)
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
	refreshReq := httptest.NewRequest(http.MethodPost, "/api/pulse/refresh", refreshBody)
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
	refreshReq := httptest.NewRequest(http.MethodPost, "/api/pulse/refresh", refreshBody)
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

func TestPulseUsesSearchFallbackWhenGenerationFails(t *testing.T) {
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
	refreshReq := httptest.NewRequest(http.MethodPost, "/api/pulse/refresh", refreshBody)
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
		t.Fatalf("expected 3 modules, got %#v", payload.Modules)
	}
	if payload.Modules[0].Title != "订阅 Topic 的外网新动向" {
		t.Fatalf("expected search fallback title, got %#v", payload.Modules[0])
	}
	if len(payload.Modules[0].Items) == 0 {
		t.Fatalf("expected search fallback items, got %#v", payload.Modules[0])
	}
	signals := payload.Modules[0].Items[0].Detail.Signals
	if len(signals) == 0 || !strings.Contains(strings.Join(signals, "\n"), "https://example.com/robotics-latest") {
		t.Fatalf("expected search source signal, got %#v", signals)
	}
	questions := payload.Modules[0].Items[0].Detail.SuggestedQuestions
	joinedQuestions := strings.Join(questions, "\n")
	if len(questions) < 3 || strings.Contains(joinedQuestions, "这些来源共同说明了什么趋势") || !strings.Contains(joinedQuestions, "机器人") {
		t.Fatalf("expected personalized search fallback questions, got %#v", questions)
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
