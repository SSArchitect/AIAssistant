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

func TestPulseGetUpgradesValidLegacyCacheBeforeServing(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	const date = "2026-07-27"
	now := time.Now().UTC()
	legacyDetail := pulseItemDetail{
		RecommendationReason: "你订阅了 AI Agent，因此这次产品发布值得关注。第二句不应继续占用推荐理由。",
		QuickContext:         "OpenAI 发布了 AgentKit 2.0。这个背景与摘要重复。",
		KeyPoints:            []string{"AgentKit 2.0 正式发布。", "推荐理由：与你订阅的 AI 相关。"},
		NewsSources: []pulseNewsSource{
			{
				Title:       "OpenAI releases AgentKit 2.0 with new workflow controls",
				URL:         "https://openai.com/news/agentkit-2",
				Snippet:     "OpenAI released AgentKit 2.0 with new workflow controls for production agents.",
				PublishedAt: "2026-07-26",
			},
			{
				Title:       "OpenAI launches AgentKit 2.0 workflow controls",
				URL:         "https://reuters.com/technology/openai-agentkit-2",
				Snippet:     "The AgentKit 2.0 launch adds workflow controls for production agent deployments.",
				PublishedAt: "2026-07-26",
			},
		},
		SuggestedQuestions: []string{
			"用 5 分钟帮我读懂「AgentKit 2.0」：发生了什么、证据是什么、我该关注哪一点？",
			"这条里「AgentKit 2.0 正在出现新的资讯信号」这个判断靠谱吗？请按来源逐条核验。",
			"把两个来源分开看：哪些是事实更新，哪些只是观点？",
		},
		PrecomputedAt: now.Add(-time.Hour).Format(time.RFC3339),
	}
	item := models.PulseItem{
		ID:         "legacy-valid",
		UserID:     "0",
		Date:       date,
		TopicName:  "AI Agent",
		Source:     pulseSourceTopicHot,
		Category:   "AI 产品",
		Title:      "OpenAI 发布 AgentKit 2.0，新增工作流控制",
		Summary:    "OpenAI 发布 AgentKit 2.0，新增面向生产 Agent 的工作流控制。独立报道确认这是同一次产品发布。第三句不应继续展示。",
		HeatScore:  88,
		DetailJSON: mustJSON(legacyDetail),
		CreatedAt:  now,
		UpdatedAt:  now,
	}
	if err := database.DB.Create(&item).Error; err != nil {
		t.Fatalf("seed legacy pulse item: %v", err)
	}
	seedPulseCacheTestModules(t, date, now)

	handler := NewPulseHandler()
	healthy, err := handler.hasCurrentPulseShape(date, "0")
	if err != nil {
		t.Fatalf("check legacy cache shape: %v", err)
	}
	if !healthy {
		t.Fatal("expected valid legacy cache to remain healthy while it is upgraded")
	}
	router := gin.New()
	router.GET("/api/pulse", handler.Get)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/api/pulse?date="+date, nil))
	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected get status %d: %s", recorder.Code, recorder.Body.String())
	}
	var response struct {
		Items []pulseItemResponse `json:"items"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("decode pulse response: %v", err)
	}
	if len(response.Items) != 1 {
		t.Fatalf("expected valid legacy cache to remain visible, got %#v", response.Items)
	}
	got := response.Items[0]
	if got.Detail.ContentVersion != pulseContentVersion {
		t.Fatalf("expected content version %d, got %#v", pulseContentVersion, got.Detail)
	}
	if strings.Contains(got.Summary, "第三句") {
		t.Fatalf("expected legacy summary to be compacted, got %q", got.Summary)
	}
	if len(got.Detail.SuggestedQuestions) != pulseSuggestedQuestionLimit {
		t.Fatalf("expected %d current questions, got %#v", pulseSuggestedQuestionLimit, got.Detail.SuggestedQuestions)
	}
	for _, question := range got.Detail.SuggestedQuestions {
		if strings.Contains(question, "用 5 分钟") ||
			len([]rune(question)) > pulseSuggestedQuestionMaxRunes {
			t.Fatalf("legacy question was not normalized: %q", question)
		}
	}

	var saved models.PulseItem
	if err := database.DB.First(&saved, "id = ? AND user_id = ?", item.ID, item.UserID).Error; err != nil {
		t.Fatalf("reload upgraded cache: %v", err)
	}
	var savedDetail pulseItemDetail
	if err := json.Unmarshal([]byte(saved.DetailJSON), &savedDetail); err != nil {
		t.Fatalf("decode upgraded cache detail: %v", err)
	}
	if savedDetail.ContentVersion != pulseContentVersion || saved.Summary != got.Summary {
		t.Fatalf("expected normalized cache to persist, item=%#v detail=%#v", saved, savedDetail)
	}
}

func TestPulseGetHidesUnsupportedFutureCacheVersion(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	const date = "2026-07-27"
	now := time.Now().UTC()
	detail := pulseItemDetail{
		ContentVersion:       pulseContentVersion + 1,
		RecommendationReason: "与你订阅的 Agent 产品发布相关。",
		NewsSources: []pulseNewsSource{
			{Title: "OpenAI releases AgentKit 2.0", URL: "https://openai.com/news/agentkit-2", Snippet: "OpenAI released AgentKit 2.0.", PublishedAt: "2026-07-26"},
			{Title: "AgentKit 2.0 launch confirmed", URL: "https://reuters.com/technology/agentkit-2", Snippet: "The AgentKit 2.0 launch was confirmed.", PublishedAt: "2026-07-26"},
		},
		SuggestedQuestions: []string{"AgentKit 2.0 发布了什么？"},
	}
	item := models.PulseItem{
		ID:         "future-version",
		UserID:     "0",
		Date:       date,
		Source:     pulseSourceTopicHot,
		Title:      "OpenAI 发布 AgentKit 2.0",
		Summary:    "OpenAI 发布 AgentKit 2.0，增加生产工作流控制。",
		DetailJSON: mustJSON(detail),
		CreatedAt:  now,
		UpdatedAt:  now,
	}
	if err := database.DB.Create(&item).Error; err != nil {
		t.Fatalf("seed future-version pulse item: %v", err)
	}
	seedPulseCacheTestModules(t, date, now)

	handler := NewPulseHandler()
	healthy, err := handler.hasCurrentPulseShape(date, "0")
	if err != nil {
		t.Fatalf("check future cache shape: %v", err)
	}
	if healthy {
		t.Fatal("expected unsupported cache version to request regeneration")
	}
	router := gin.New()
	router.GET("/api/pulse", handler.Get)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/api/pulse?date="+date, nil))
	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected get status %d: %s", recorder.Code, recorder.Body.String())
	}
	var response struct {
		Items []pulseItemResponse `json:"items"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("decode pulse response: %v", err)
	}
	if len(response.Items) != 0 {
		t.Fatalf("expected unsupported cache version to be hidden, got %#v", response.Items)
	}
}

func TestPulseGeneratedItemsCarryCurrentContentVersion(t *testing.T) {
	item := searchFallbackClusterItem("2026-07-27", pulseSearchEvidence{
		Module: pulseSourceTopicHot,
		Query:  "OpenAI AgentKit 2.0 release",
		Results: []pulseSearchResult{
			{Title: "OpenAI releases AgentKit 2.0", URL: "https://openai.com/news/agentkit-2", Snippet: "OpenAI released AgentKit 2.0.", PublishedAt: "2026-07-26"},
			{Title: "AgentKit 2.0 launch confirmed", URL: "https://reuters.com/technology/agentkit-2", Snippet: "The AgentKit 2.0 launch was confirmed.", PublishedAt: "2026-07-26"},
		},
	}, 0)
	var detail pulseItemDetail
	if err := json.Unmarshal([]byte(item.DetailJSON), &detail); err != nil {
		t.Fatalf("decode generated detail: %v", err)
	}
	if detail.ContentVersion != pulseContentVersion {
		t.Fatalf("expected generated content version %d, got %#v", pulseContentVersion, detail)
	}
}

func seedPulseCacheTestModules(t *testing.T, date string, now time.Time) {
	t.Helper()
	modules := make([]models.PulseModule, 0, len(pulseModuleOrder))
	for _, key := range pulseModuleOrder {
		modules = append(modules, models.PulseModule{
			ID:        pulseItemID(date, "module", key),
			UserID:    "0",
			Date:      date,
			Key:       key,
			Title:     key,
			Summary:   key,
			CreatedAt: now,
			UpdatedAt: now,
		})
	}
	if err := database.DB.Create(&modules).Error; err != nil {
		t.Fatalf("seed pulse modules: %v", err)
	}
}
