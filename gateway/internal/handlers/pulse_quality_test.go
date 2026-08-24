package handlers

import (
	"encoding/json"
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

func TestPulseQualitySearchBudgetPreservesAllModules(t *testing.T) {
	topics := []models.PulseTopic{
		{ID: "topic-ai", Name: "AI", Keywords: `["agent","model"]`, Enabled: true},
		{ID: "topic-engineering", Name: "工程效率", Keywords: `["devops","toolchain"]`, Enabled: true},
		{ID: "topic-models", Name: "大模型产品", Keywords: `["llm","release"]`, Enabled: true},
		{ID: "topic-investing", Name: "投资研究", Keywords: `["market","earnings"]`, Enabled: true},
		{ID: "topic-travel", Name: "旅行规划", Keywords: `["route","hotel"]`, Enabled: true},
	}
	signals := []memoryPulseSignal{
		{Theme: "代码质量", Focus: "后端代码质量与测试", Keywords: []string{"testing", "quality"}},
		{Theme: "研究工作流", Focus: "投资研究工作流", Keywords: []string{"research", "workflow"}},
	}

	queries := buildPulseSearchQueries("2026-07-27", topics, signals)
	if len(queries) > pulseSearchQueryLimit {
		t.Fatalf("query budget exceeded: got %d, limit %d", len(queries), pulseSearchQueryLimit)
	}

	moduleCounts := map[string]int{}
	coveredTopics := map[string]bool{}
	for _, query := range queries {
		moduleCounts[normalizePulseModuleKey(query.Module)]++
		if query.TopicID != "" {
			coveredTopics[query.TopicID] = true
		}
	}
	for _, module := range pulseModuleOrder {
		if moduleCounts[module] < 2 {
			t.Errorf("expected at least two reserved queries for %s, got %d (all counts: %#v)", module, moduleCounts[module], moduleCounts)
		}
	}
	for _, topic := range topics {
		if !coveredTopics[topic.ID] {
			t.Errorf("enabled topic %q received no query within the shared budget", topic.Name)
		}
	}
	for _, query := range queries {
		if query.TopicID == "topic-ai" && strings.Contains(query.Query, "agent") &&
			strings.Contains(query.Query, "model") {
			t.Fatalf("topic query should focus on one keyword angle instead of stacking every keyword: %q", query.Query)
		}
	}
}

func TestPulseQualitySkipsFollowupForAlreadyVerifiedCluster(t *testing.T) {
	evidence := pulseSearchEvidence{
		Module:    pulseSourceTopicHot,
		Query:     "OpenAI GPT-5.6 coding agent latest news 2026",
		TopicName: "AI",
		Results: []pulseSearchResult{
			{
				Title:       "OpenAI launches GPT-5.6 coding agent with terminal controls",
				Snippet:     "OpenAI released GPT-5.6 with a coding agent and new terminal controls.",
				URL:         "https://openai.com/news/gpt-5-6-coding-agent",
				PublishedAt: "2026-07-26",
			},
			{
				Title:       "OpenAI releases GPT-5.6 coding agent and terminal controls",
				Snippet:     "The GPT-5.6 release adds a coding agent with terminal controls.",
				URL:         "https://technology.example.com/openai-gpt-5-6-agent",
				PublishedAt: "2026-07-25",
			},
		},
	}

	if pulseSearchEvidenceNeedsFollowup("2026-07-27", evidence) {
		t.Fatal("already corroborated, recent evidence should not trigger another search round")
	}
	if seeds := pulseSearchFollowupSeeds("2026-07-27", []pulseSearchEvidence{evidence}); len(seeds) != 0 {
		t.Fatalf("expected no follow-up seeds for verified evidence, got %#v", seeds)
	}
}

func TestPulseQualityGetSelfHealsEmptyCachedModules(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}
	date := "2026-07-27"
	now := time.Now()
	modules := make([]models.PulseModule, 0, len(pulseModuleOrder))
	for _, key := range pulseModuleOrder {
		modules = append(modules, models.PulseModule{
			ID:        pulseItemID(date, "module", key),
			UserID:    "0",
			Date:      date,
			Key:       key,
			Title:     "旧空模块",
			Summary:   "没有任何合格信息簇。",
			CreatedAt: now,
			UpdatedAt: now,
		})
	}
	if err := database.DB.Create(&modules).Error; err != nil {
		t.Fatalf("seed empty modules: %v", err)
	}

	generationStarted := make(chan struct{}, 1)
	releaseGeneration := make(chan struct{})
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/agent/chat" {
			http.NotFound(w, r)
			return
		}
		select {
		case generationStarted <- struct{}{}:
		default:
		}
		<-releaseGeneration
		http.Error(w, "generation unavailable", http.StatusServiceUnavailable)
	}))
	defer agentServer.Close()

	handler := NewPulseHandler(bridge.NewAgentClient(agentServer.URL, time.Second))
	router := gin.New()
	router.GET("/api/pulse", handler.Get)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/api/pulse?date="+date, nil))
	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected get status %d: %s", recorder.Code, recorder.Body.String())
	}
	var response struct {
		Refreshing       bool   `json:"refreshing"`
		RefreshStage     string `json:"refresh_stage"`
		RefreshStartedAt string `json:"refresh_started_at"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("decode pulse response: %v", err)
	}
	if !response.Refreshing {
		t.Fatal("expected cached modules without verified items to trigger background self-healing")
	}
	if response.RefreshStage == "" || response.RefreshStartedAt == "" {
		t.Fatalf("expected live refresh progress metadata, got %#v", response)
	}
	select {
	case <-generationStarted:
	case <-time.After(time.Second):
		t.Fatal("background generation did not start")
	}
	close(releaseGeneration)
	deadline := time.Now().Add(2 * time.Second)
	for handler.pulseGenerationActive(date, "0") && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if handler.pulseGenerationActive(date, "0") {
		t.Fatal("background generation did not finish")
	}
}

func TestPulseQualityFallbackNeverEmitsSingletonClusters(t *testing.T) {
	evidence := pulseSearchEvidence{
		Module:    pulseSourceTopicHot,
		Query:     "AI agent recent update 2026",
		TopicName: "AI",
		Results: []pulseSearchResult{
			{Title: "OpenAI agent platform update", Snippet: "New agent platform controls.", URL: "https://openai.com/news/agents"},
			{Title: "Local hotel summer promotion", Snippet: "A hotel booking discount.", URL: "https://travel.example/hotel"},
			{Title: "Cloud database maintenance", Snippet: "Routine database maintenance.", URL: "https://status.example.net/database"},
		},
	}

	clusters := pulseSearchFallbackClusters(evidence)
	for _, cluster := range clusters {
		if len(cluster) < 2 {
			t.Fatalf("fallback exposed a singleton cluster: %#v", cluster)
		}
		if got := pulseSearchIndependentSourceCount(cluster); got < 2 {
			t.Fatalf("fallback exposed a cluster without independent corroboration: %#v", cluster)
		}
	}
}

func TestPulseQualitySameBrandDifferentEventsDoNotCorroborate(t *testing.T) {
	evidence := pulseSearchEvidence{
		Module:    pulseSourceTopicHot,
		Query:     "OpenAI company news 2026",
		TopicName: "OpenAI",
	}
	modelRelease := pulseSearchResult{
		Title:       "OpenAI company launches GPT-5 developer API",
		Snippet:     "The company product adds coding controls for developers.",
		URL:         "https://technology.example.com/openai-gpt-5-api",
		PublishedAt: "2026-07-26",
	}
	executiveAppointment := pulseSearchResult{
		Title:       "OpenAI company appoints a new chief financial officer",
		Snippet:     "The company named a finance executive to its product leadership team.",
		URL:         "https://business.example.org/openai-cfo-appointment",
		PublishedAt: "2026-07-25",
	}

	if pulseSearchResultsCorroborate(evidence, modelRelease, executiveAppointment) {
		t.Fatal("sharing only a brand name must not make two different events corroborate")
	}
	evidence.Results = []pulseSearchResult{modelRelease, executiveAppointment}
	if clusters := pulseSearchFallbackClusters(evidence); len(clusters) != 0 {
		t.Fatalf("different OpenAI events must not become a fallback cluster: %#v", clusters)
	}

	unknownBrandEvidence := pulseSearchEvidence{
		Module:    pulseSourceTopicHot,
		Query:     "Microsoft company news 2026",
		TopicName: "Microsoft",
	}
	acquisition := pulseSearchResult{
		Title:       "Microsoft enterprise acquires a game studio",
		Snippet:     "Microsoft completed a studio acquisition.",
		URL:         "https://technology.example.com/microsoft-studio-acquisition",
		PublishedAt: "2026-07-26",
	}
	appointment := pulseSearchResult{
		Title:       "Microsoft enterprise appoints a new CFO",
		Snippet:     "Microsoft named a finance executive.",
		URL:         "https://business.example.org/microsoft-cfo-appointment",
		PublishedAt: "2026-07-25",
	}
	if pulseSearchResultsCorroborate(unknownBrandEvidence, acquisition, appointment) {
		t.Fatal("a query brand absent from the hard-coded entity list must not count as an event term")
	}
}

func TestPulseQualityCorroboratesSharedAgentHarnessEvent(t *testing.T) {
	evidence := pulseSearchEvidence{
		Module:    pulseSourceTopicHot,
		Query:     "AI 工程 Claude Code Gemini CLI 模型能力 产品发布 latest news 2026",
		TopicName: "AI 工程",
	}
	left := pulseSearchResult{
		Title:   "Anthropic launches Agent Harness 2.0 for Claude Code",
		Snippet: "The Agent Harness 2.0 release adds shared controls for Claude Code and Gemini CLI.",
		URL:     "https://github.com/example/agent-harness",
	}
	right := pulseSearchResult{
		Title:   "Agent Harness 2.0 launch adds Claude Code controls",
		Snippet: "An independent report confirms the new Agent Harness 2.0 release for Claude Code.",
		URL:     "https://research.example.org/agent-harness-claude-gemini",
	}
	if !pulseSearchResultsCorroborate(evidence, left, right) {
		t.Fatalf(
			"expected shared agent-harness event to corroborate; left=%#v right=%#v overlap=%#v subjects=%#v",
			pulseCorroborationTerms(left),
			pulseCorroborationTerms(right),
			intersectPulseTerms(pulseCorroborationTerms(left), pulseCorroborationTerms(right)),
			pulseCorroborationSubjectTermSet(evidence),
		)
	}
}

func TestPulseQualityRejectsGenericAgentTrendArticlesAsNewsEvent(t *testing.T) {
	const date = "2026-07-27"
	evidence := pulseSearchEvidence{
		Module:    pulseSourceTopicHot,
		Query:     "AI Agent Anthropic GPT RAG trend analysis 2026",
		TopicName: "AI",
		Results: []pulseSearchResult{
			{
				Title:       "2026 AI革命:世界正适应Agent新时代",
				Snippet:     "港大助理教授黄超在AIGC2026峰会上讨论如何重新设计数字世界来适应AI Agent，并提出CLI-Anything设想。",
				URL:         "https://www.sohu.com/a/1030123591_121956424",
				PublishedAt: "2026-05-31 12:31:00",
			},
			{
				Title:       "AI Agent Development Trends 2026: A Deep Dive - aimagician - 博客园",
				Snippet:     "This article explores the major trends in AI agent development for 2026, including workflows, RAG and multi-agent orchestration.",
				URL:         "https://www.cnblogs.com/aimagician/p/20844062",
				PublishedAt: "2026-06-26 16:28:00",
			},
		},
	}

	left, right := evidence.Results[0], evidence.Results[1]
	if pulseSearchResultsCorroborate(evidence, left, right) {
		t.Fatal("two broad Agent opinion/trend articles must not corroborate as one news event")
	}
	if pulseSearchClusterDescribesConcreteEvent(evidence.Results) {
		t.Fatal("broad theme overlap must not satisfy the concrete-event quality gate")
	}
	if clusters := pulseSearchFallbackClusters(evidence); len(clusters) != 0 {
		t.Fatalf("generic Agent trend articles must not produce a fallback news cluster: %#v", clusters)
	}

	// Keep the semantic assertion independent of the weak-source denylist: even
	// recent articles on otherwise accepted domains are not a news event merely
	// because they discuss the same broad trend.
	acceptedDomainCopies := append([]pulseSearchResult{}, evidence.Results...)
	acceptedDomainCopies[0].URL = "https://technology.example.com/ai-agent-era"
	acceptedDomainCopies[1].URL = "https://research.example.org/agent-development-trends"
	item := qualityTestPulseItem(date, "generic-agent-trends", newsSourcesFromSearchResults(acceptedDomainCopies, 5))
	if pulseItemMeetsQualityGate(item) {
		t.Fatalf("generic trend item passed publishing quality gate: %#v", item)
	}
}

func TestPulseQualityConcreteEventGateKeepsCorroboratedProductRelease(t *testing.T) {
	const date = "2026-07-27"
	sources := []pulseNewsSource{
		{
			Title:       "OpenAI releases AgentGuard-2 permission controls",
			URL:         "https://openai.com/news/agentguard-2-controls",
			PublishedAt: "2026-07-26",
		},
		{
			Title:       "Report confirms AgentGuard-2 permission controls release",
			URL:         "https://www.reuters.com/technology/agentguard-2-controls",
			PublishedAt: "2026-07-25",
		},
	}
	results := pulseSearchResultsFromNewsSources(sources)
	if !pulseSearchClusterDescribesConcreteEvent(results) {
		t.Fatalf("same named product release should satisfy concrete-event gate: %#v", results)
	}
	if !pulseNewsSourcesMeetQualityGate(date, pulseSourceTopicHot, sources) {
		t.Fatalf("recent independently corroborated product release should pass source quality gate: %#v", sources)
	}
}

func TestPulseQualityConcreteEventGateRejectsDifferentReleasesFromSameCompany(t *testing.T) {
	const date = "2026-07-27"
	sources := []pulseNewsSource{
		{
			Title:       "OpenAI releases GPT-5 agent controls",
			Snippet:     "The GPT-5 update adds approval controls for coding agents.",
			URL:         "https://openai.com/news/gpt-5-agent-controls",
			PublishedAt: "2026-07-26",
		},
		{
			Title:       "OpenAI launches Sora video editor",
			Snippet:     "The Sora release introduces a new timeline for video creators.",
			URL:         "https://www.reuters.com/technology/openai-sora-editor",
			PublishedAt: "2026-07-25",
		},
	}
	results := pulseSearchResultsFromNewsSources(sources)
	if pulseSearchResultsShareConcreteEvent(results[0], results[1]) {
		t.Fatal("a shared company and product-change verb must not merge two different releases")
	}
	if pulseSearchClusterDescribesConcreteEvent(results) {
		t.Fatal("different OpenAI product releases must not form one concrete event cluster")
	}
	if pulseNewsSourcesMeetQualityGate(date, pulseSourceTopicHot, sources) {
		t.Fatalf("different product releases passed source quality gate: %#v", sources)
	}
}

func TestPulseQualityIndependentSourcesUseRegistrableDomain(t *testing.T) {
	tests := []struct {
		name  string
		left  string
		right string
	}{
		{
			name:  "ordinary subdomains",
			left:  "https://news.example.com/releases/1",
			right: "https://docs.example.com/product/1",
		},
		{
			name:  "multi-label public suffix",
			left:  "https://research.example.co.uk/report",
			right: "https://news.example.co.uk/story",
		},
		{
			name:  "known publisher aliases",
			left:  "https://ones.cn/blog/devops",
			right: "https://ones.com.cn/knowledge/devops",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			left := pulseSourceDomainKey(tt.left)
			right := pulseSourceDomainKey(tt.right)
			if left == "" || right == "" {
				t.Fatalf("expected valid domain keys, got %q and %q", left, right)
			}
			if left != right {
				t.Fatalf("same publisher domain must not count as independent: %q != %q", left, right)
			}
		})
	}

	results := []pulseSearchResult{
		{URL: "https://news.example.com/releases/1"},
		{URL: "https://docs.example.com/product/1"},
		{URL: "https://independent.example.org/story"},
	}
	if got := pulseSearchIndependentSourceCount(results); got != 2 {
		t.Fatalf("expected two registrable domains, got %d", got)
	}
}

func TestPulseQualityGateRejectsHistoricalUnsafeSourceURLs(t *testing.T) {
	const date = "2026-07-27"
	unsafeURLs := []string{
		"javascript://legacy-source.example/article",
		"file://legacy-source.example/article",
		"ftp://legacy-source.example/article",
	}
	for _, unsafeURL := range unsafeURLs {
		t.Run(unsafeURL, func(t *testing.T) {
			item := qualityTestPulseItem(date, "unsafe-source", []pulseNewsSource{
				{
					Title:       "Legacy unsafe source",
					URL:         unsafeURL,
					PublishedAt: "2026-07-26",
				},
				{
					Title:       "Independent HTTPS report",
					URL:         "https://reuters.com/technology/verified-update",
					PublishedAt: "2026-07-25",
				},
			})
			if pulseItemMeetsQualityGate(item) {
				t.Fatalf("historical item containing unsafe source URL passed quality gate: %q", unsafeURL)
			}
		})
	}
}

func TestPulseQualityFreshnessRequiresRecentCorroboration(t *testing.T) {
	const date = "2026-07-27"
	recent := []pulseSearchResult{
		{
			Title:       "OpenAI releases agent controls",
			Snippet:     "OpenAI released new controls for enterprise agents.",
			URL:         "https://openai.com/news/agent-controls",
			PublishedAt: "2026-07-26",
		},
		{
			Title:       "New enterprise agent controls launch",
			Snippet:     "The new OpenAI enterprise agent controls launched this week.",
			URL:         "https://www.reuters.com/technology/openai-agent-controls",
			PublishedAt: "2026-07-25T08:00:00Z",
		},
	}
	stale := []pulseSearchResult{
		{
			Title:       "OpenAI releases agent controls",
			Snippet:     "OpenAI released controls for enterprise agents.",
			URL:         "https://openai.com/news/old-agent-controls",
			PublishedAt: "2024-02-29",
		},
		{
			Title:       "Enterprise agent controls launch",
			Snippet:     "OpenAI enterprise agent controls launched.",
			URL:         "https://www.reuters.com/technology/old-agent-controls",
			PublishedAt: "2024-03-01",
		},
	}
	oneRecentOneStale := []pulseSearchResult{recent[0], stale[1]}

	if !pulseSearchResultsFreshEnough(date, pulseSourceTopicHot, recent) {
		t.Fatal("expected two recent corroborating sources to pass freshness")
	}
	if pulseSearchResultsFreshEnough(date, pulseSourceTopicHot, stale) {
		t.Fatal("expected stale sources to fail freshness")
	}
	if pulseSearchResultsFreshEnough(date, pulseSourceTopicHot, oneRecentOneStale) {
		t.Fatal("expected a single recent source to be insufficient corroboration")
	}
}

func TestPulseQualityFreshnessUsesModuleSpecificWindows(t *testing.T) {
	const date = "2026-08-24"
	results := func(leftDate string, rightDate string) []pulseSearchResult {
		return []pulseSearchResult{
			{URL: "https://openai.com/news/update", PublishedAt: leftDate},
			{URL: "https://reuters.com/technology/update", PublishedAt: rightDate},
		}
	}

	if !pulseSearchResultsFreshEnough(date, pulseSourceTopicHot, results("2026-08-21", "2026-08-22")) {
		t.Fatal("expected Topic sources inside the 72-hour window to pass")
	}
	if pulseSearchResultsFreshEnough(date, pulseSourceInterestHot, results("2026-08-20", "2026-08-21")) {
		t.Fatal("expected hot-news sources outside the 72-hour window to fail")
	}
	if !pulseSearchResultsFreshEnough(date, pulseSourceMemory, results("2026-07-25", "2026-08-01")) {
		t.Fatal("expected Memory sources inside the 30-day window to pass")
	}
	if pulseSearchResultsFreshEnough(date, pulseSourceMemory, results("2026-07-24", "2026-07-23")) {
		t.Fatal("expected Memory sources older than 30 days to fail")
	}

	topicSuffixes := pulseSearchQuerySuffixesForDate(pulseSourceTopicHot, date)
	memorySuffixes := pulseSearchQuerySuffixesForDate(pulseSourceMemory, date)
	if !strings.Contains(strings.Join(topicSuffixes, " "), "after 2026-08-21") {
		t.Fatalf("expected Topic queries to request the 72-hour window, got %#v", topicSuffixes)
	}
	if !strings.Contains(strings.Join(memorySuffixes, " "), "after 2026-07-25") {
		t.Fatalf("expected Memory queries to request the 30-day window, got %#v", memorySuffixes)
	}
}

func TestPulseQualitySearchFallbackPreservesModuleDiversity(t *testing.T) {
	const date = "2026-07-27"
	evidence := make([]pulseSearchEvidence, 0, pulseCandidateTargetCount+2)
	for index := 0; index < pulseCandidateTargetCount; index++ {
		eventID := "topic-event-" + string(rune('a'+index))
		evidence = append(evidence, qualityFallbackEvidence(date, pulseSourceTopicHot, eventID))
	}
	evidence = append(
		evidence,
		qualityFallbackEvidence(date, pulseSourceMemory, "memory-event"),
		qualityFallbackEvidence(date, pulseSourceInterestHot, "interest-event"),
	)

	_, items := buildSearchFallbackPulse(date, nil, nil, evidence, nil)
	moduleCounts := map[string]int{}
	for _, item := range items {
		moduleCounts[normalizePulseModuleKey(item.Source)]++
	}
	for _, module := range pulseModuleOrder {
		if moduleCounts[module] == 0 {
			t.Fatalf("fallback dropped %s despite verified candidates in every module: %#v", module, moduleCounts)
		}
	}
}

func TestPulseQualityMinimumReplacementCountForEightExistingItems(t *testing.T) {
	if got := pulseMinimumReplacementCount(8); got != 6 {
		t.Fatalf("expected at least 6 verified replacements for 8 existing items, got %d", got)
	}
}

func TestPulseQualityGateRejectsWeakSameDomainAndStaleItems(t *testing.T) {
	const date = "2026-07-27"
	valid := qualityTestPulseItem(date, "valid", []pulseNewsSource{
		{Title: "OpenAI releases agent controls", URL: "https://openai.com/news/agent-controls", PublishedAt: "2026-07-26"},
		{Title: "Report confirms OpenAI agent controls release", URL: "https://www.reuters.com/technology/agent-controls", PublishedAt: "2026-07-25"},
	})
	if !pulseItemMeetsQualityGate(valid) {
		var detail pulseItemDetail
		_ = json.Unmarshal([]byte(valid.DetailJSON), &detail)
		t.Fatalf(
			"expected recent independently corroborated item to pass quality gate (copy=%v sources=%v)",
			pulseNewsCopyMeetsQualityGate(valid.Title, valid.Summary),
			pulseNewsSourcesMeetQualityGate(valid.Date, valid.Source, detail.NewsSources),
		)
	}

	tests := []struct {
		name    string
		sources []pulseNewsSource
	}{
		{
			name: "same registrable domain",
			sources: []pulseNewsSource{
				{Title: "Product post", URL: "https://news.example.com/product", PublishedAt: "2026-07-26"},
				{Title: "Product docs", URL: "https://docs.example.com/product", PublishedAt: "2026-07-25"},
			},
		},
		{
			name: "all weak sources",
			sources: []pulseNewsSource{
				{Title: "转载一", URL: "https://blog.csdn.net/example/article/details/1", PublishedAt: "2026-07-26"},
				{Title: "转载二", URL: "https://www.cnblogs.com/example/p/agent.html", PublishedAt: "2026-07-25"},
			},
		},
		{
			name: "stale sources",
			sources: []pulseNewsSource{
				{Title: "Old official post", URL: "https://openai.com/news/old-release", PublishedAt: "2024-02-29"},
				{Title: "Old independent report", URL: "https://www.reuters.com/technology/old-release", PublishedAt: "2024-03-01"},
			},
		},
		{
			name: "stale sohu plus undated csdn devops cluster",
			sources: []pulseNewsSource{
				{
					Title:       "DevOps 工具链演进与实践",
					URL:         "https://www.sohu.com/a/old-devops-toolchain",
					PublishedAt: "2024-02-29",
				},
				{
					Title: "DevOps 平台建设经验",
					URL:   "https://blog.csdn.net/example/article/details/devops",
				},
			},
		},
		{
			name: "missing publication dates",
			sources: []pulseNewsSource{
				{Title: "Undated post", URL: "https://openai.com/news/undated"},
				{Title: "Undated report", URL: "https://www.reuters.com/technology/undated"},
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			item := qualityTestPulseItem(date, tt.name, tt.sources)
			if pulseItemMeetsQualityGate(item) {
				t.Fatalf("expected low-quality item to fail gate: %#v", item)
			}
			recommended := recommendedPulseItems([]models.PulseItem{item}, emptyPulseQualityFeatureState())
			if len(recommended) != 0 {
				t.Fatalf("expected low-quality item to stay hidden, got %#v", recommended)
			}
		})
	}
}

func TestPulseQualityGateRejectsGenericPlaceholderNewsCopy(t *testing.T) {
	const date = "2026-07-27"
	item := models.PulseItem{
		ID:        "generic-agent-trend",
		Date:      date,
		Source:    pulseSourceTopicHot,
		TopicName: "AI",
		Title:     "AI 模型进展：Agent 新线索值得跟踪",
		Summary:   "2 条来源集中指向 AI 模型进展（Agent）：出现新的外部资讯信号，但具体事实仍需要打开来源核验。",
		HeatScore: 80,
		DetailJSON: mustJSON(pulseItemDetail{
			RecommendationReason: "与你订阅的「AI」直接相关。",
			NewsSources: []pulseNewsSource{
				{
					Title:       "OpenAI announces a new agent runtime",
					URL:         "https://openai.com/news/new-agent-runtime",
					PublishedAt: "2026-07-26",
				},
				{
					Title:       "Independent report covers the OpenAI agent runtime launch",
					URL:         "https://www.reuters.com/technology/openai-agent-runtime",
					PublishedAt: "2026-07-25",
				},
			},
		}),
	}

	if pulseItemMeetsQualityGate(item) {
		t.Fatalf("generic placeholder copy passed quality gate: %q / %q", item.Title, item.Summary)
	}
	if recommended := recommendedPulseItems([]models.PulseItem{item}, emptyPulseQualityFeatureState()); len(recommended) != 0 {
		t.Fatalf("generic placeholder copy remained visible: %#v", recommended)
	}
}

func TestPulseNewsCopyQualityRequiresSubjectActionAndConcreteFact(t *testing.T) {
	tests := []struct {
		name    string
		title   string
		summary string
		want    bool
	}{
		{
			name:    "specific product event",
			title:   "OpenAI 发布 GPT-5.6 并开放企业 API",
			summary: "OpenAI 于 7 月 26 日发布 GPT-5.6，首批向企业 API 客户开放。",
			want:    true,
		},
		{
			name:    "specific unknown project",
			title:   "RoboControl-7 控制器完成发布",
			summary: "RoboControl-7 完成发布，并新增机器人开发者接入能力。",
			want:    true,
		},
		{
			name:    "title has no event",
			title:   "AI Agent 行业观察",
			summary: "OpenAI 发布 GPT-5.6，并新增 Agent 工具调用能力。",
			want:    false,
		},
		{
			name:    "summary has no fact",
			title:   "OpenAI 发布 GPT-5.6",
			summary: "AI 模型进展出现新的外部资讯信号，值得继续跟踪。",
			want:    false,
		},
		{
			name:    "generic subject",
			title:   "AI 发布新进展",
			summary: "OpenAI 发布 GPT-5.6，并新增 Agent 工具调用能力。",
			want:    false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := pulseNewsCopyMeetsQualityGate(tt.title, tt.summary); got != tt.want {
				t.Fatalf("pulseNewsCopyMeetsQualityGate(%q, %q) = %v, want %v", tt.title, tt.summary, got, tt.want)
			}
		})
	}
}

func TestPulseQualityRecommendedItemsDoNotResurrectFilteredPool(t *testing.T) {
	item := qualityTestPulseItem("2026-07-27", "downvoted", []pulseNewsSource{
		{Title: "OpenAI releases agent controls", URL: "https://openai.com/news/agent-controls", PublishedAt: "2026-07-26"},
		{Title: "Report confirms OpenAI agent controls release", URL: "https://www.reuters.com/technology/agent-controls", PublishedAt: "2026-07-25"},
	})
	state := emptyPulseQualityFeatureState()
	state.feedbackByItem[item.ID] = pulseItemFeedbackResponse{Vote: "down", DownvoteCount: 1}

	if recommended := recommendedPulseItems([]models.PulseItem{item}, state); len(recommended) != 0 {
		t.Fatalf("expected a fully filtered pool to remain empty, got %#v", recommended)
	}
}

func TestPulseQualityDownvoteCanBeUndone(t *testing.T) {
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	now := time.Now()
	item := qualityTestPulseItem("2026-07-27", "undo-downvote", []pulseNewsSource{
		{Title: "OpenAI releases agent controls", URL: "https://openai.com/news/agent-controls", PublishedAt: "2026-07-26"},
		{Title: "Report confirms OpenAI agent controls release", URL: "https://www.reuters.com/technology/agent-controls", PublishedAt: "2026-07-25"},
	})
	item.UserID = "0"
	item.CreatedAt = now
	item.UpdatedAt = now
	if err := database.DB.Create(&item).Error; err != nil {
		t.Fatalf("seed pulse item: %v", err)
	}
	events := []models.PulseEvent{
		{
			ID:        "downvote-on",
			UserID:    "0",
			Date:      item.Date,
			ItemID:    item.ID,
			Source:    item.Source,
			EventType: pulseEventDownvote,
			Value:     1,
			CreatedAt: now,
		},
		{
			ID:        "downvote-off",
			UserID:    "0",
			Date:      item.Date,
			ItemID:    item.ID,
			Source:    item.Source,
			EventType: pulseEventDownvote,
			Value:     0,
			CreatedAt: now.Add(time.Second),
		},
	}
	if err := database.DB.Create(&events).Error; err != nil {
		t.Fatalf("seed pulse events: %v", err)
	}

	state, err := loadPulseFeatureState("0", item.Date, []models.PulseItem{item})
	if err != nil {
		t.Fatalf("load feature state: %v", err)
	}
	feedback := state.feedbackFor(item.ID)
	if feedback.Vote != "" || feedback.DownvoteCount != 0 {
		t.Fatalf("expected downvote undo to clear current feedback, got %#v", feedback)
	}
	if state.shouldFilter(item) {
		t.Fatalf("an undone downvote must not keep filtering item: %#v", feedback)
	}
}

func TestPulseQualityGeneratedItemsMustReferenceSearchEvidence(t *testing.T) {
	const date = "2026-07-27"
	evidence := []pulseSearchEvidence{
		{
			Module:    pulseSourceTopicHot,
			Query:     "OpenAI agent controls latest news",
			TopicName: "AI",
			Results: []pulseSearchResult{
				{
					Title:       "OpenAI releases agent controls",
					Snippet:     "OpenAI released new controls for enterprise agents.",
					URL:         "https://openai.com/news/agent-controls",
					PublishedAt: "2026-07-26",
				},
				{
					Title:       "Independent report confirms OpenAI agent controls",
					Snippet:     "The OpenAI enterprise agent controls launched this week.",
					URL:         "https://www.reuters.com/technology/openai-agent-controls",
					PublishedAt: "2026-07-25",
				},
				{
					Title:       "OpenAI appoints a new finance executive",
					Snippet:     "The company named a new finance leader in a separate event.",
					URL:         "https://business.example.org/openai-finance-appointment",
					PublishedAt: "2026-07-25",
				},
			},
		},
	}
	payload := generatedPulsePayload{Modules: []generatedPulseModule{
		{
			Key:     pulseSourceTopicHot,
			Title:   "AI 更新",
			Summary: "近期可信更新。",
			Items: []generatedPulseItem{
				{
					Title:   "OpenAI 发布企业 Agent 权限控制",
					Summary: "OpenAI 发布企业 Agent 权限控制，并开放管理员配置。",
					NewsSources: []pulseNewsSource{
						{URL: "https://openai.com/news/agent-controls"},
						{URL: "https://www.reuters.com/technology/openai-agent-controls"},
						{URL: "https://business.example.org/openai-finance-appointment"},
					},
				},
				{
					Title:   "Anthropic 发布 Claude 企业控制台",
					Summary: "Anthropic 发布 Claude 企业控制台，并开放管理员接入。",
					NewsSources: []pulseNewsSource{
						{URL: "https://hallucinated.example/fake-news"},
						{URL: "https://another-hallucinated.example/fake-news"},
					},
				},
			},
		},
	}}

	filtered, rejected := filterGeneratedPulsePayloadByEvidence(date, payload, evidence)
	if rejected != 1 {
		t.Fatalf("expected one hallucinated item to be rejected, got %d", rejected)
	}
	if got := generatedPulseItemCount(filtered); got != 1 {
		t.Fatalf("expected only the grounded item to remain, got %d: %#v", got, filtered)
	}
	sources := filtered.Modules[0].Items[0].NewsSources
	if len(sources) != 2 || sources[0].PublishedAt == "" || sources[1].PublishedAt == "" {
		t.Fatalf("expected only the corroborating source component to be copied from evidence, got %#v", sources)
	}
}

func TestPulseQualityFeedbackWeightDecaysOverTime(t *testing.T) {
	reference := time.Date(2026, 7, 27, 12, 0, 0, 0, time.UTC)
	event := models.PulseEvent{
		EventType: pulseEventOpen,
		Value:     1,
		CreatedAt: reference.Add(-10 * 24 * time.Hour),
	}
	if got := pulseTimeDecayedEventWeight(event, reference); got != pulseEventFeatureWeight(event)/2 {
		t.Fatalf("expected 10-day-old feedback to be halved, got %d", got)
	}
	event.CreatedAt = reference.Add(-100 * 24 * time.Hour)
	if got := pulseTimeDecayedEventWeight(event, reference); got != 0 {
		t.Fatalf("expected feedback older than 90 days to expire, got %d", got)
	}

	upvote := models.PulseEvent{
		EventType: pulseEventUpvote,
		Value:     1,
		CreatedAt: reference.Add(-100 * 24 * time.Hour),
	}
	undo := upvote
	undo.Value = 0
	undo.CreatedAt = reference
	if total := pulseTimeDecayedEventWeight(upvote, reference) + pulseTimeDecayedEventWeight(undo, reference); total != 0 {
		t.Fatalf("expected explicit preference undo to cancel across decay windows, got %d", total)
	}
}

func TestPulseQualityVoteSwitchUsesFinalStateWeight(t *testing.T) {
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}
	date := "2026-07-27"
	now := time.Now()
	items := []models.PulseItem{
		qualityTestPulseItem(date, "down-to-up", []pulseNewsSource{
			{Title: "OpenAI agent controls launch", URL: "https://openai.com/news/agent-controls", PublishedAt: date},
			{Title: "Report confirms agent controls launch", URL: "https://reuters.com/technology/agent-controls", PublishedAt: date},
		}),
		qualityTestPulseItem(date, "up-to-down", []pulseNewsSource{
			{Title: "OpenAI agent controls launch", URL: "https://openai.com/news/agent-controls", PublishedAt: date},
			{Title: "Report confirms agent controls launch", URL: "https://reuters.com/technology/agent-controls", PublishedAt: date},
		}),
	}
	for index := range items {
		items[index].UserID = "0"
		items[index].TopicID = "topic-" + items[index].ID
	}
	if err := database.DB.Create(&items).Error; err != nil {
		t.Fatalf("seed items: %v", err)
	}
	events := []models.PulseEvent{
		{ID: "vote-1", UserID: "0", Date: date, ItemID: items[0].ID, TopicID: items[0].TopicID, Source: items[0].Source, EventType: pulseEventDownvote, Value: 1, CreatedAt: now},
		{ID: "vote-2", UserID: "0", Date: date, ItemID: items[0].ID, TopicID: items[0].TopicID, Source: items[0].Source, EventType: pulseEventUpvote, Value: 1, CreatedAt: now.Add(time.Second)},
		{ID: "vote-3", UserID: "0", Date: date, ItemID: items[1].ID, TopicID: items[1].TopicID, Source: items[1].Source, EventType: pulseEventUpvote, Value: 1, CreatedAt: now.Add(2 * time.Second)},
		{ID: "vote-4", UserID: "0", Date: date, ItemID: items[1].ID, TopicID: items[1].TopicID, Source: items[1].Source, EventType: pulseEventDownvote, Value: 1, CreatedAt: now.Add(3 * time.Second)},
	}
	if err := database.DB.Create(&events).Error; err != nil {
		t.Fatalf("seed vote events: %v", err)
	}

	state, err := loadPulseFeatureState("0", date, items)
	if err != nil {
		t.Fatalf("load feature state: %v", err)
	}
	if feedback := state.feedbackFor(items[0].ID); feedback.Vote != "up" {
		t.Fatalf("expected final upvote state, got %#v", feedback)
	}
	if got := state.directScores[items[0].ID]; got != 22 {
		t.Fatalf("expected down-to-up score to equal final upvote weight 22, got %d", got)
	}
	if feedback := state.feedbackFor(items[1].ID); feedback.Vote != "down" {
		t.Fatalf("expected final downvote state, got %#v", feedback)
	}
	if got := state.directScores[items[1].ID]; got != -28 {
		t.Fatalf("expected up-to-down score to equal final downvote weight -28, got %d", got)
	}
}

func TestPulseQualityVisibleFeedReservesModuleDiversity(t *testing.T) {
	items := []models.PulseItem{}
	for moduleIndex, module := range pulseModuleOrder {
		for itemIndex := 0; itemIndex < 3; itemIndex++ {
			items = append(items, models.PulseItem{
				ID:        module + "-" + string(rune('a'+itemIndex)),
				Source:    module,
				TopicID:   "topic-" + module + "-" + string(rune('a'+itemIndex)),
				HeatScore: 100 - moduleIndex*10 - itemIndex,
			})
		}
	}

	selected := diversifyPulseItems(items, 6)
	if len(selected) != 6 {
		t.Fatalf("expected six selected items, got %#v", selected)
	}
	counts := map[string]int{}
	for _, item := range selected {
		counts[item.Source]++
	}
	for _, module := range pulseModuleOrder {
		if counts[module] != 2 {
			t.Fatalf("expected two items from %s, got %#v", module, counts)
		}
	}
}

func TestPulseQualityGenerationPromptRequiresCompactNonRepeatingCopy(t *testing.T) {
	prompt := pulseGenerationPrompt()
	required := []string{
		`summary 是卡片唯一的“新闻簇内容”字段`,
		"recommendation_reason 只解释“为什么与这个用户相关”",
		"必须是一句短句",
		"恰好生成 3 个 suggested_questions",
		"不超过 32 个中文字符",
		"禁止“用 5 分钟帮我读懂",
		"可识别主体",
		"具体动作/事件",
		"无法提取具体事实，不要生成这个 item",
	}
	for _, fragment := range required {
		if !strings.Contains(prompt, fragment) {
			t.Fatalf("generation prompt omitted compact-copy rule %q", fragment)
		}
	}
}

func TestPulseQualitySuggestedQuestionsAreShortAndCapped(t *testing.T) {
	questions := personalizedPulseSuggestedQuestions([]string{
		"用 5 分钟帮我读懂「RoboControl-7 控制器发布」：发生了什么、证据是什么、我该关注哪一点？",
		"请逐条核验 RoboControl-7 控制器发布涉及的全部来源并给出一份非常详细的时间线和事实清单。",
		"RoboControl-7 控制器发布后要关注哪些指标？",
		"RoboControl-7 的开放范围有哪些变化？",
	}, pulseQuestionContext{
		Title:     "RoboControl-7 控制器发布",
		Summary:   "RoboControl-7 完成发布，并开放首批开发者接入。",
		Module:    pulseSourceTopicHot,
		TopicName: "具身智能",
		KeyPoints: []string{"开放范围", "开发者接入"},
		Sources: []pulseNewsSource{
			{Title: "RoboControl-7 官方发布"},
			{Title: "RoboControl-7 独立报道"},
		},
	})

	if len(questions) != pulseSuggestedQuestionLimit {
		t.Fatalf("expected exactly %d suggested questions, got %#v", pulseSuggestedQuestionLimit, questions)
	}
	for _, question := range questions {
		if len([]rune(question)) > pulseSuggestedQuestionMaxRunes {
			t.Fatalf("suggested question exceeds %d runes: %q", pulseSuggestedQuestionMaxRunes, question)
		}
		if strings.Contains(question, "用 5 分钟") || strings.Contains(question, "用5分钟") || strings.Contains(question, "…") {
			t.Fatalf("long read-it-for-me template leaked into suggestions: %q", question)
		}
	}
}

func TestPulseQualityDeterministicFallbackDetailIsCompactAndDeduplicated(t *testing.T) {
	const snippetMarker = "FULL_SOURCE_SNIPPET_MUST_NOT_APPEAR"
	item := searchFallbackClusterItem("2026-07-27", pulseSearchEvidence{
		Module:    pulseSourceTopicHot,
		Query:     "RoboControl-7 controller release 2026",
		TopicName: "具身智能",
		Results: []pulseSearchResult{
			{
				Title:       "RoboControl-7 controller launches for robot developers",
				Snippet:     snippetMarker + " with a very long description of the launch, rollout, access policy and every quoted source detail.",
				URL:         "https://robotics.example.com/news/robocontrol-7",
				Source:      "official",
				PublishedAt: "2026-07-26",
			},
			{
				Title:       "Independent report confirms RoboControl-7 controller launch",
				Snippet:     snippetMarker + " repeated by an independent report with another long block of source copy.",
				URL:         "https://industry.example.org/reports/robocontrol-7",
				Source:      "web",
				PublishedAt: "2026-07-25",
			},
		},
	}, 0)

	var detail pulseItemDetail
	if err := json.Unmarshal([]byte(item.DetailJSON), &detail); err != nil {
		t.Fatalf("decode fallback detail: %v", err)
	}
	if strings.Contains(detail.QuickContext, snippetMarker) ||
		strings.Contains(detail.QuickContext, "来源线索") ||
		strings.Contains(detail.QuickContext, "RoboControl-7 controller launches") {
		t.Fatalf("quick context leaked source copy: %q", detail.QuickContext)
	}
	if len(detail.Signals) != 0 {
		t.Fatalf("fallback signals should not duplicate query or news_sources: %#v", detail.Signals)
	}
	for _, point := range detail.KeyPoints {
		if pulseTextHasAny(strings.ToLower(point), "推荐理由", "核验动作", "搜索来源", "http://", "https://") {
			t.Fatalf("fallback key point repeats recommendation or source data: %q", point)
		}
	}
	if len([]rune(detail.RecommendationReason)) > pulseRecommendationMaxRunes ||
		strings.Count(detail.RecommendationReason, "。") > 1 {
		t.Fatalf("recommendation reason is not one short sentence: %q", detail.RecommendationReason)
	}
	if len(detail.SuggestedQuestions) != pulseSuggestedQuestionLimit {
		t.Fatalf("expected exactly three fallback questions, got %#v", detail.SuggestedQuestions)
	}
	for _, question := range detail.SuggestedQuestions {
		if len([]rune(question)) > pulseSuggestedQuestionMaxRunes || strings.Contains(question, "用 5 分钟") {
			t.Fatalf("fallback question is too long or templated: %q", question)
		}
	}
	if strings.Contains(item.Summary, "推荐") || strings.Contains(item.Summary, "打开原文核验") {
		t.Fatalf("summary should be the news content only, got %q", item.Summary)
	}
}

func qualityFallbackEvidence(date string, module string, eventID string) pulseSearchEvidence {
	return pulseSearchEvidence{
		Module:    module,
		Query:     "OpenAI GPT-5 agent controls " + eventID,
		TopicName: "AI",
		Results: []pulseSearchResult{
			{
				Title:       "OpenAI GPT-5 agent controls released " + eventID,
				Snippet:     "The release adds verified agent controls for " + eventID + ".",
				URL:         "https://official.example.com/news/" + eventID,
				Source:      "official",
				PublishedAt: date,
			},
			{
				Title:       "Independent report confirms GPT-5 agent controls " + eventID,
				Snippet:     "A separate report confirms the same OpenAI release for " + eventID + ".",
				URL:         "https://independent.example.org/reports/" + eventID,
				Source:      "web",
				PublishedAt: date,
			},
		},
	}
}

func qualityTestPulseItem(date string, id string, sources []pulseNewsSource) models.PulseItem {
	return models.PulseItem{
		ID:        id,
		Date:      date,
		Source:    pulseSourceTopicHot,
		TopicName: "AI",
		Title:     "OpenAI released enterprise agent controls",
		Summary:   "OpenAI released enterprise agent controls and opened them to business customers.",
		HeatScore: 80,
		DetailJSON: mustJSON(pulseItemDetail{
			RecommendationReason: "近期独立来源共同确认这项产品更新。",
			QuickContext:         "发布范围、时间和企业控制能力均有可核验来源。",
			KeyPoints:            []string{"官方发布", "独立报道", "近期更新"},
			NewsSources:          sources,
		}),
	}
}

func emptyPulseQualityFeatureState() pulseFeatureState {
	return pulseFeatureState{
		feedbackByItem: map[string]pulseItemFeedbackResponse{},
		feedbackByKey:  map[string]pulseItemFeedbackResponse{},
		directScores:   map[string]int{},
		clusterScores:  map[string]int{},
		topicScores:    map[string]int{},
		sourceScores:   map[string]int{},
	}
}
