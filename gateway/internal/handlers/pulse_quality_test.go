package handlers

import (
	"bytes"
	"encoding/json"
	"fmt"
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

func TestPulseQualityGenerationBudgetIsThreeMinutes(t *testing.T) {
	if pulseGenerationBudget != 180*time.Second {
		t.Fatalf("expected a 180-second Pulse budget, got %s", pulseGenerationBudget)
	}
	if pulseSearchBudget != 85*time.Second {
		t.Fatalf("expected an 85-second retrieval sub-budget, got %s", pulseSearchBudget)
	}
}

func TestPulseQualityUsesLightweightDiscoveryForLargeQuerySets(t *testing.T) {
	lightweight, concurrency := pulseInitialSearchMode(pulseSearchFullModeQueryLimit + 1)
	if !lightweight || concurrency != pulseSearchLightConcurrency {
		t.Fatalf("expected large query sets to use lightweight discovery at concurrency %d, got lightweight=%v concurrency=%d", pulseSearchLightConcurrency, lightweight, concurrency)
	}

	lightweight, concurrency = pulseInitialSearchMode(pulseSearchFullModeQueryLimit)
	if lightweight || concurrency != pulseSearchConcurrency {
		t.Fatalf("expected small query sets to retain full rewrite and rerank at concurrency %d, got lightweight=%v concurrency=%d", pulseSearchConcurrency, lightweight, concurrency)
	}
}

func TestPulseQualityBuildsLatestAndHotQueriesForEveryKeyword(t *testing.T) {
	topics := []models.PulseTopic{
		{ID: "topic-ai", Name: "AI", Keywords: `["agent","model"]`},
		{ID: "topic-engineering", Name: "工程效率", Keywords: `["devops","toolchain"]`},
		{ID: "topic-models", Name: "大模型产品", Keywords: `["llm","release"]`},
		{ID: "topic-investing", Name: "投资研究", Keywords: `["market","earnings"]`},
		{ID: "topic-travel", Name: "旅行规划", Keywords: `["route","hotel"]`},
	}
	signals := []memoryPulseSignal{
		{Theme: "代码质量", Focus: "后端代码质量与测试", Keywords: []string{"testing", "quality"}},
		{Theme: "研究工作流", Focus: "投资研究工作流", Keywords: []string{"research", "workflow"}},
	}

	queries := buildPulseSearchQueries("2026-07-27", topics, signals)
	moduleCounts := map[string]int{}
	coveredTopics := map[string]bool{}
	variants := map[string]map[string]bool{}
	for _, query := range queries {
		moduleCounts[normalizePulseModuleKey(query.Module)]++
		if query.TopicID != "" {
			coveredTopics[query.TopicID] = true
		}
		if variants[query.Keyword] == nil {
			variants[query.Keyword] = map[string]bool{}
		}
		variants[query.Keyword][query.Intent] = true
	}
	if moduleCounts[pulseSourceTopicHot] != 20 || moduleCounts[pulseSourceMemory] != 8 || moduleCounts[pulseSourceInterestHot] != 0 {
		t.Fatalf("expected two queries for every topic and memory keyword, got %#v", moduleCounts)
	}
	for _, topic := range topics {
		if !coveredTopics[topic.ID] {
			t.Errorf("enabled topic %q received no query within the shared budget", topic.Name)
		}
	}
	for keyword, keywordVariants := range variants {
		if !keywordVariants["keyword_latest"] || !keywordVariants["keyword_hot"] {
			t.Fatalf("keyword %q did not receive both discovery variants: %#v", keyword, keywordVariants)
		}
	}
	if queries[0].Query != "agent 智能体 最新进展" || queries[1].Query != "agent 智能体 近期热点" {
		t.Fatalf("expected the Agent alias and two fixed templates, got %#v", queries[:2])
	}
}

func TestPulseQualityDoesNotTruncateStoredKeywordDiscoveryQueries(t *testing.T) {
	topics := []models.PulseTopic{
		{
			ID:       "vendors",
			Name:     "AI 厂商与产品动态",
			Keywords: `["Anthropic","Claude","DeepSeek","GPT","Gemini","Grok","OpenAI"]`,
		},
		{
			ID:       "agents",
			Name:     "AI 应用与 Agent",
			Keywords: `["Agent","Function Calling","RAG","Structured Output","vLLM"]`,
		},
		{
			ID:       "markets",
			Name:     "AI 行业研究与估值",
			Keywords: `["AI 公司","IPO","S-1","估值","商业化","招股书"]`,
		},
	}

	queries := buildPulseSearchQueries("2026-08-27", topics, nil)
	expectedKeywordCount := 7 + 5 + 6
	if len(queries) != expectedKeywordCount*2 {
		t.Fatalf("expected every stored keyword to receive two queries, got %d queries", len(queries))
	}
	seen := map[string]map[string]bool{}
	for _, query := range queries {
		key := query.TopicID + ":" + query.Keyword
		if seen[key] == nil {
			seen[key] = map[string]bool{}
		}
		seen[key][query.Intent] = true
	}
	for key, variants := range seen {
		if len(variants) != 2 || !variants["keyword_latest"] || !variants["keyword_hot"] {
			t.Fatalf("stored keyword %q was truncated or lost a variant: %#v", key, variants)
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

func TestPulseQualityFollowupTargetsUnsupportedSeedInsidePartlyVerifiedQuery(t *testing.T) {
	evidence := pulseSearchEvidence{
		Module:    pulseSourceTopicHot,
		Query:     "OpenAI Anthropic agent controls latest news 2026",
		TopicName: "AI Agent",
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
				URL:         "https://www.reuters.com/technology/openai-gpt-5-6-agent",
				PublishedAt: "2026-07-25",
			},
			{
				Title:       "Anthropic launches Claude Guardrail 2.0 with policy controls",
				Snippet:     "Anthropic launched Claude Guardrail 2.0 and added enterprise policy controls.",
				URL:         "https://anthropic.com/news/claude-guardrail-2",
				PublishedAt: "2026-07-26",
			},
		},
	}

	seeds := pulseSearchFollowupSeeds("2026-07-27", []pulseSearchEvidence{evidence})
	if len(seeds) != 1 || !strings.Contains(seeds[0].Result.Title, "Guardrail 2.0") {
		orphan := evidence.Results[2]
		t.Fatalf(
			"expected only the unsupported event to receive a second-stage search, got %#v (eligible=%v supported=%v score=%d terms=%#v families=%#v)",
			seeds,
			pulseSearchResultCanSeedFollowup("2026-07-27", evidence, orphan),
			pulseSearchResultHasVerifiedSupport("2026-07-27", evidence, orphan),
			pulseSearchResultRelevanceScore(pulseSearchQueryFromEvidence(evidence), orphan),
			pulseCorroborationTerms(orphan),
			pulseConcreteEventFamilies(orphan),
		)
	}
}

func TestPulseQualityFollowupSelectsOneEventAndOneQueryPerKeyword(t *testing.T) {
	evidence := []pulseSearchEvidence{}
	for index := 0; index < 4; index++ {
		name := fmt.Sprintf("ModelCo%d", index)
		evidence = append(evidence, pulseSearchEvidence{
			QueryID: "q" + fmt.Sprint(index+1), Module: pulseSourceTopicHot, TopicID: "topic-ai", TopicName: "AI",
			Keyword: name, Query: name + " 最新进展",
			Results: []pulseSearchResult{{
				Title:       fmt.Sprintf("%s acquires SafeLab%d in $%dM deal", name, index, 100+index),
				Snippet:     fmt.Sprintf("%s acquired SafeLab%d for $%dM to expand its AI safety research.", name, index, 100+index),
				URL:         fmt.Sprintf("https://%s.example.com/news/safelab-%d", strings.ToLower(name), index),
				PublishedAt: "2026-07-26",
			}},
		})
	}

	seeds := pulseSearchFollowupSeeds("2026-07-27", evidence)
	if len(seeds) != len(evidence) {
		t.Fatalf("expected one event per keyword, got %d", len(seeds))
	}
	plans := pulseSearchFollowupPlans("2026-07-27", evidence)
	if len(plans) != len(evidence) {
		t.Fatalf("expected one event-verification query per keyword, got %#v", plans)
	}
	for _, plan := range plans {
		if plan.Kind != "event_verification" || plan.Query.Keyword == "" {
			t.Fatalf("unexpected follow-up plan: %#v", plan)
		}
		if !strings.Contains(plan.Query.Query, "2026") {
			t.Fatalf("expected the result-derived year in the event query, got %q", plan.Query.Query)
		}
	}
}

func TestPulseQualityFollowupUsesConcreteEventTitleInsteadOfDigestAnchor(t *testing.T) {
	evidence := pulseSearchEvidence{
		Module:    pulseSourceTopicHot,
		Query:     "Anthropic Claude Agent latest news 2026",
		TopicName: "AI",
		Results: []pulseSearchResult{
			{
				Title:       "AI Daily Digest: Anthropic and OpenAI updates",
				Snippet:     "The daily digest covers several unrelated model and agent launches.",
				URL:         "https://digest.example.com/ai-daily",
				PublishedAt: "2026-08-23",
			},
			{
				Title:       "Anthropic launches browser use and Agent Skills GA — Example News",
				Snippet:     "Anthropic launched browser use, computer use, Files API, and Agent Skills as generally available on August 19, 2026.",
				URL:         "https://event.example.com/anthropic-agent-tools-ga",
				PublishedAt: "2026-08-22",
			},
		},
	}

	seeds := pulseSearchFollowupSeeds("2026-08-27", []pulseSearchEvidence{evidence})
	if len(seeds) != 1 || strings.Contains(strings.ToLower(seeds[0].Result.Title), "digest") {
		t.Fatalf("expected only the concrete event page to seed verification, got %#v", seeds)
	}
	plans := pulseSearchFollowupPlans("2026-08-27", []pulseSearchEvidence{evidence})
	if len(plans) != 1 || plans[0].Kind != "event_verification" {
		t.Fatalf("expected one event-verification follow-up, got %#v", plans)
	}
	for _, plan := range plans {
		if !strings.Contains(plan.Query.Query, "Anthropic launches browser use and Agent Skills GA") ||
			strings.Contains(plan.Query.Query, "Example News") {
			t.Fatalf("expected the clean concrete title to anchor follow-up search, got %q", plan.Query.Query)
		}
	}
}

func TestPulseQualityRanksPrimaryAndAuthoritativeSourcesFirst(t *testing.T) {
	query := pulseSearchQuery{Query: "OpenAI GPT-5.6 agent controls", TopicName: "AI"}
	results := []pulseSearchResult{
		{Title: "OpenAI GPT-5.6 agent controls", URL: "https://blog.csdn.net/example/gpt-5-6", Snippet: "OpenAI launched GPT-5.6 agent controls."},
		{Title: "OpenAI GPT-5.6 agent controls", URL: "https://www.reuters.com/technology/openai-gpt-5-6", Snippet: "OpenAI launched GPT-5.6 agent controls."},
		{Title: "OpenAI GPT-5.6 agent controls", URL: "https://openai.com/news/gpt-5-6", Snippet: "OpenAI launched GPT-5.6 agent controls."},
	}

	ranked := pulseRankSearchResults(query, results, len(results))
	if len(ranked) != 3 || !strings.Contains(ranked[0].URL, "openai.com") || !strings.Contains(ranked[1].URL, "reuters.com") {
		t.Fatalf("expected primary source then authoritative reporting, got %#v", ranked)
	}
}

func TestPulseQualityVerifiedClustersMergeSameEventAcrossQueries(t *testing.T) {
	const date = "2026-07-27"
	evidence := []pulseSearchEvidence{
		{
			QueryID: "q1", Module: pulseSourceTopicHot, TopicID: "topic-ai", TopicName: "AI",
			Query: "OpenAI GPT-5.6 official release",
			Results: []pulseSearchResult{{
				Title: "OpenAI launches GPT-5.6 coding agent controls", Snippet: "OpenAI released GPT-5.6 with new coding agent controls.",
				URL: "https://openai.com/news/gpt-5-6-agent", PublishedAt: "2026-07-26",
			}},
		},
		{
			QueryID: "q2", Module: pulseSourceTopicHot, TopicID: "topic-ai", TopicName: "AI",
			Query: "GPT-5.6 independent report",
			Results: []pulseSearchResult{{
				Title: "GPT-5.6 coding agent controls launch", Snippet: "An independent report confirms OpenAI launched GPT-5.6 coding agent controls.",
				URL: "https://www.reuters.com/technology/openai-gpt-5-6", PublishedAt: "2026-07-25",
			}},
		},
	}

	clusters := pulseVerifiedSearchClusters(date, evidence)
	if len(clusters) != 1 || len(clusters[0].Results) != 2 {
		t.Fatalf("expected cross-query results to form one verified event cluster, got %#v", clusters)
	}
}

func TestPulseQualityTrustedFirstStageEventPublishesWithoutFollowupSupport(t *testing.T) {
	const date = "2026-08-28"
	result := pulseSearchResult{
		Title:       "OpenAI 发布 GPT-5.6 AgentKit-2.0 企业权限控制",
		Snippet:     "OpenAI 于 8 月 27 日发布 GPT-5.6 AgentKit-2.0，新增企业审批、工具调用范围和运行记录控制，并开始向企业开发者开放。",
		URL:         "https://openai.com/news/agentkit-2-enterprise-controls",
		Source:      "official",
		PublishedAt: "2026-08-27",
	}
	evidence := []pulseSearchEvidence{{
		QueryID:   "q-agentkit-latest",
		Stage:     "initial",
		Module:    pulseSourceTopicHot,
		Keyword:   "GPT",
		Query:     "GPT 最新进展",
		Intent:    "keyword_latest",
		TopicID:   "topic-ai",
		TopicName: "AI",
		Results:   []pulseSearchResult{result},
	}}

	clusters := pulseVerifiedSearchClusters(date, evidence)
	if len(clusters) != 1 || len(clusters[0].Results) != 1 {
		t.Fatalf("expected one publishable first-stage event, got %#v", clusters)
	}
	if !strings.Contains(clusters[0].Intent, "二次检索仅用于内容扩展") {
		t.Fatalf("expected optional follow-up semantics, got %q", clusters[0].Intent)
	}
	if !pulseNewsSourcesMeetQualityGate(date, pulseSourceTopicHot, newsSourcesFromSearchResults([]pulseSearchResult{result}, 5)) {
		t.Fatalf("recent official event should pass without follow-up support: %#v", pulseNewsSourceQualityIssues(date, pulseSourceTopicHot, newsSourcesFromSearchResults([]pulseSearchResult{result}, 5)))
	}
	if plans := pulseSearchFollowupPlans(date, evidence); len(plans) != 1 {
		t.Fatalf("follow-up should still be scheduled as enrichment, got %#v", plans)
	}

	payload := generatedPulsePayload{Modules: []generatedPulseModule{{
		Key: pulseSourceTopicHot,
		Items: []generatedPulseItem{{
			Title:       "OpenAI 发布 GPT-5.6 AgentKit-2.0，新增企业级 Agent 权限控制",
			Summary:     "OpenAI 于 8 月 27 日发布 GPT-5.6 AgentKit-2.0，并开始向企业开发者开放新的 Agent 权限控制。官方发布页显示，此次更新覆盖管理员审批、工具调用范围和运行记录查看，让企业能够限制智能体可执行的操作及可访问的数据。新版本还调整了企业接入流程和控制入口，重点面向需要审计与治理能力的生产环境。当前可以确认的变化来自 OpenAI 发布材料；后续二次检索只用于补充外部评价和使用反馈，不影响这条发布信息进入 Pulse。",
			NewsSources: []pulseNewsSource{{URL: result.URL}},
		}},
	}}}
	filtered, rejections := filterGeneratedPulsePayloadByEvidenceWithDiagnostics(date, payload, clusters)
	if len(rejections) != 0 || generatedPulseItemCount(filtered) != 1 {
		t.Fatalf("trusted singleton should remain grounded, filtered=%#v rejections=%#v", filtered, rejections)
	}
	_, converted := generatedPayloadToModels(date, filtered, []models.PulseTopic{{ID: "topic-ai", Name: "AI"}})
	published, publishingRejections := filterPulseItemsForPublishingWithDiagnostics(converted)
	if len(published) != 1 || len(publishingRejections) != 0 {
		t.Fatalf("trusted singleton should publish, published=%#v rejected=%#v", published, publishingRejections)
	}

	// Models sometimes preserve the verified claim while dropping or rewriting
	// its URL. The short evidence id should recover the canonical official source
	// without relaxing the source-quality gate.
	payload.Modules[0].Items[0].EvidenceID = clusters[0].QueryID
	payload.Modules[0].Items[0].NewsSources = nil
	filtered, rejections = filterGeneratedPulsePayloadByEvidenceWithDiagnostics(date, payload, clusters)
	if len(rejections) != 0 || generatedPulseItemCount(filtered) != 1 {
		t.Fatalf("trusted evidence id should recover a dropped official URL, filtered=%#v rejections=%#v", filtered, rejections)
	}
	if got := filtered.Modules[0].Items[0].NewsSources; len(got) != 1 || got[0].URL != result.URL {
		t.Fatalf("expected the canonical official source to be restored, got %#v", got)
	}

	duplicatePayload := generatedPulsePayload{Modules: []generatedPulseModule{
		{Key: pulseSourceTopicHot, Items: []generatedPulseItem{payload.Modules[0].Items[0]}},
		{Key: pulseSourceMemory, Items: []generatedPulseItem{payload.Modules[0].Items[0]}},
	}}
	filtered, rejections = filterGeneratedPulsePayloadByEvidenceWithDiagnostics(date, duplicatePayload, clusters)
	if generatedPulseItemCount(filtered) != 1 || len(rejections) != 1 ||
		!containsString(rejections[0].Reasons, "duplicate_evidence_cluster") {
		t.Fatalf("one verified cluster must publish at most once, filtered=%#v rejections=%#v", filtered, rejections)
	}
	duplicateCachedItem := converted[0]
	duplicateCachedItem.ID = "duplicate-cache-item"
	duplicateCachedItem.Source = pulseSourceMemory
	revalidated, _ := revalidatePulseCachedItems([]models.PulseItem{converted[0], duplicateCachedItem})
	if len(revalidated) != 1 {
		t.Fatalf("cached Pulse items must also deduplicate the same grounded cluster, got %#v", revalidated)
	}
}

func TestPulseQualityOrdinaryFirstStageSingletonStillNeedsCorroboration(t *testing.T) {
	const date = "2026-08-28"
	result := pulseSearchResult{
		Title:       "AgentKit-2.0 发布企业权限控制",
		Snippet:     "一篇普通站点文章称 AgentKit-2.0 已发布，并介绍企业审批、工具调用范围和运行记录控制。",
		URL:         "https://ordinary.example.com/agentkit-2-controls",
		PublishedAt: "2026-08-27",
	}
	evidence := []pulseSearchEvidence{{
		Stage: "initial", Module: pulseSourceTopicHot, Keyword: "AgentKit", Query: "AgentKit 最新进展", Results: []pulseSearchResult{result},
	}}
	if clusters := pulseVerifiedSearchClusters(date, evidence); len(clusters) != 0 {
		t.Fatalf("ordinary singleton must still require corroboration, got %#v", clusters)
	}
	if pulseNewsSourcesMeetQualityGate(date, pulseSourceTopicHot, newsSourcesFromSearchResults([]pulseSearchResult{result}, 5)) {
		t.Fatal("ordinary singleton unexpectedly passed the publication gate")
	}
}

func TestPulseQualityKeywordDigestPublishesWithoutEventFollowup(t *testing.T) {
	const date = "2026-08-28"
	results := []pulseSearchResult{
		{
			Title:       "Ingest-Time Compilation Takes On Query-Time RAG",
			Snippet:     "A recent RAG review compares ingest-time compilation with query-time retrieval and explains where agentic retrieval reaches its limits.",
			URL:         "https://dev.to/example/ingest-time-rag",
			PublishedAt: "2026-08-25",
		},
		{
			Title:   "Trends and Transitions in RAG: From Naive Pipelines to Agentic Retrieval",
			Snippet: "The report describes RAG moving from fixed vector pipelines toward graph retrieval, adaptive routing, memory systems, and agent-driven retrieval.",
			URL:     "https://research.example.org/rag-transitions",
		},
	}
	evidence := []pulseSearchEvidence{
		{QueryID: "rag-latest", Stage: "initial", Module: pulseSourceTopicHot, Keyword: "RAG", Query: "RAG 最新进展", TopicID: "topic-ai", TopicName: "AI", Results: results[:1]},
		{QueryID: "rag-hot", Stage: "initial", Module: pulseSourceTopicHot, Keyword: "RAG", Query: "RAG 近期热点", TopicID: "topic-ai", TopicName: "AI", Results: results[1:]},
	}
	clusters := pulseVerifiedSearchClusters(date, evidence)
	if len(clusters) != 1 || clusters[0].Intent != "keyword_digest" || len(clusters[0].Results) != 2 {
		t.Fatalf("expected a first-stage keyword digest, got %#v", clusters)
	}

	payload := generatedPulsePayload{Modules: []generatedPulseModule{{
		Key: pulseSourceTopicHot,
		Items: []generatedPulseItem{{
			Title:       "RAG 从固定检索管线转向编译式与 Agentic Retrieval",
			Summary:     "近期 RAG 讨论的重点正在从传统向量检索管线，转向摄取阶段编译、图检索、自适应路由与 Agentic Retrieval。两份材料分别从处理时机和系统架构解释这一变化：前者把部分查询成本前移到数据摄取阶段，后者强调由智能体根据任务动态选择检索策略。它们共同指出，固定的 query-time RAG 在复杂任务、长期记忆和多步推理中存在边界。这里归纳的是同一关键词下的技术方向，不代表两份来源报道了同一个产品发布。",
			NewsSources: []pulseNewsSource{{URL: results[0].URL}, {URL: results[1].URL}},
		}},
	}}}
	filtered, rejections := filterGeneratedPulsePayloadByEvidenceWithDiagnostics(date, payload, clusters)
	if len(rejections) != 0 || generatedPulseItemCount(filtered) != 1 {
		t.Fatalf("keyword digest should remain grounded, filtered=%#v rejections=%#v", filtered, rejections)
	}
	if filtered.Modules[0].Items[0].EvidenceMode != "keyword_digest" {
		t.Fatalf("expected grounding to retain digest mode, got %#v", filtered.Modules[0].Items[0])
	}
	_, converted := generatedPayloadToModels(date, filtered, []models.PulseTopic{{ID: "topic-ai", Name: "AI"}})
	published, publishingRejections := filterPulseItemsForPublishingWithDiagnostics(converted)
	if len(published) != 1 || len(publishingRejections) != 0 {
		t.Fatalf("keyword digest should publish, published=%#v rejected=%#v", published, publishingRejections)
	}

	// A digest can also be recovered conservatively from its copy when the model
	// omitted both URLs and evidence_id. The title must still identify a trend,
	// and the best verified cluster must be unambiguous.
	payload.Modules[0].Items[0].EvidenceID = ""
	payload.Modules[0].Items[0].Title = "Agentic RAG 路线被重点押注，固定检索管线继续转向编译式检索"
	payload.Modules[0].Items[0].NewsSources = nil
	filtered, rejections = filterGeneratedPulsePayloadByEvidenceWithDiagnostics(date, payload, clusters)
	if len(rejections) != 0 || generatedPulseItemCount(filtered) != 1 {
		t.Fatalf("unambiguous RAG digest copy should recover dropped URLs, filtered=%#v rejections=%#v", filtered, rejections)
	}
	if got := len(filtered.Modules[0].Items[0].NewsSources); got != 2 {
		t.Fatalf("expected both verified digest sources to be restored, got %d", got)
	}

	payload.Modules[0].Items[0].Title = "RAG 准确率提升 99%，Agentic 路线持续演进"
	filtered, rejections = filterGeneratedPulsePayloadByEvidenceWithDiagnostics(date, payload, clusters)
	if len(rejections) != 1 || generatedPulseItemCount(filtered) != 0 ||
		!containsString(rejections[0].Reasons, "unsupported_digest_title_claim") {
		t.Fatalf("unsupported hard claim must not be rescued as a trend digest, filtered=%#v rejections=%#v", filtered, rejections)
	}

	if !pulseKeywordDigestTitleClaimsSupported("RAG 调研覆盖 32% 的复杂任务并持续演进", []pulseNewsSource{
		{Title: "RAG survey covers 32% of complex tasks", URL: "https://research.example.com/rag-32"},
		{Title: "Independent RAG report confirms 32% coverage", URL: "https://news.example.org/rag-coverage"},
	}) {
		t.Fatal("a quantitative digest claim supported by two independent sources should remain publishable")
	}
	if !pulseKeywordDigestTitleClaimsSupported("AI Agent 生态在 2026 年继续扩张", []pulseNewsSource{
		{Title: "AI Agent tools expand", URL: "https://research.example.com/agent-tools"},
		{Title: "Agent tutorials grow", URL: "https://news.example.org/agent-tutorials"},
	}) {
		t.Fatal("a calendar year must not be treated as an unsupported quantitative performance claim")
	}
}

func TestPulseQualityPromptRequiresVerifiedEvidenceID(t *testing.T) {
	prompt := pulseGenerationPrompt()
	if !strings.Contains(prompt, `"evidence_id":"vc1"`) ||
		!strings.Contains(prompt, "query_id 原样复制到 evidence_id") {
		t.Fatalf("Pulse generation prompt must bind every item to a verified cluster: %s", prompt)
	}
}

func TestPulseQualityGenerationContextKeepsVerifiedClustersBounded(t *testing.T) {
	clusters := make([]pulseSearchEvidence, 0, 20)
	for clusterIndex := 0; clusterIndex < 20; clusterIndex++ {
		cluster := pulseSearchEvidence{
			QueryID:   fmt.Sprintf("vc%d", clusterIndex+1),
			Stage:     "cluster",
			Module:    pulseSourceTopicHot,
			Query:     fmt.Sprintf("topic-%d", clusterIndex),
			Intent:    "keyword_digest",
			Keyword:   fmt.Sprintf("keyword-%d", clusterIndex),
			TopicID:   fmt.Sprintf("topic-%d", clusterIndex%6),
			TopicName: fmt.Sprintf("Topic %d", clusterIndex%6),
		}
		for sourceIndex := 0; sourceIndex < 5; sourceIndex++ {
			cluster.Results = append(cluster.Results, pulseSearchResult{
				Title:       fmt.Sprintf("Verified result %d-%d", clusterIndex, sourceIndex),
				Snippet:     strings.Repeat("可信来源正文摘录", 100),
				URL:         fmt.Sprintf("https://source-%d.example.com/article/%d?utm_source=pulse#section", sourceIndex, clusterIndex),
				PublishedAt: "2026-08-27",
			})
		}
		clusters = append(clusters, cluster)
	}

	selected := pulseSelectGenerationClusters(clusters)
	compact := pulseCompactGenerationClusters(selected)
	if len(compact) != pulseGenerationClusterLimit {
		t.Fatalf("expected %d bounded clusters, got %d", pulseGenerationClusterLimit, len(compact))
	}
	for _, cluster := range compact {
		if len(cluster.Results) > pulseGenerationSourceLimit {
			t.Fatalf("cluster exceeded source limit: %#v", cluster)
		}
		for _, result := range cluster.Results {
			if len([]rune(result.Snippet)) > pulseGenerationSnippetLimit {
				t.Fatalf("snippet exceeded compact limit: %d", len([]rune(result.Snippet)))
			}
			if strings.Contains(result.URL, "?") || strings.Contains(result.URL, "#") {
				t.Fatalf("generation URL retained tracking noise: %s", result.URL)
			}
		}
	}

	encoded, err := json.Marshal(pulseGenerationInput{
		Date:             "2026-08-28",
		UserID:           "user",
		VerifiedClusters: compact,
		RetrievalSummary: map[string]int{"query_count": 64, "verified_cluster_count": len(compact)},
	})
	if err != nil {
		t.Fatalf("marshal compact generation input: %v", err)
	}
	if runeCount := len([]rune(string(encoded))); runeCount >= 22000 {
		t.Fatalf("verified generation context must leave room below the 24k context-block cap, got %d characters", runeCount)
	}
	if bytes.Contains(encoded, []byte(`"search_evidence"`)) || bytes.Contains(encoded, []byte(`"search_queries"`)) {
		t.Fatalf("raw discovery data leaked into generation input: %s", encoded)
	}
}

func TestPulseQualityClusterRequiresTrustedSourceAndEveryPairToMatch(t *testing.T) {
	const date = "2026-07-27"
	unknownSources := []pulseNewsSource{
		{Title: "OpenAI launches GPT-5.6 agent controls", Snippet: "OpenAI released GPT-5.6 agent controls.", URL: "https://unknown-one.example/news/gpt-5-6", PublishedAt: "2026-07-26"},
		{Title: "GPT-5.6 agent controls launch", Snippet: "OpenAI launched GPT-5.6 agent controls.", URL: "https://unknown-two.example/report/gpt-5-6", PublishedAt: "2026-07-25"},
	}
	if issues := pulseNewsSourceQualityIssues(date, pulseSourceTopicHot, unknownSources); !containsString(issues, "missing_trusted_source") {
		t.Fatalf("expected unknown sites to require a trusted source, got %#v", issues)
	}

	mixed := append([]pulseNewsSource{}, unknownSources...)
	mixed[0].URL = "https://openai.com/news/gpt-5-6"
	mixed = append(mixed, pulseNewsSource{
		Title: "OpenAI launches Sora video editor", Snippet: "OpenAI released a Sora timeline editor for video creators.",
		URL: "https://www.theverge.com/ai/openai-sora-editor", PublishedAt: "2026-07-26",
	})
	if pulseNewsSourcesMeetQualityGate(date, pulseSourceTopicHot, mixed) {
		t.Fatalf("a trusted but unrelated third source must not ride along with a verified pair: %#v", mixed)
	}
}

func TestPulseQualityAcceptsThreeDatedIndependentSpecialistSources(t *testing.T) {
	const date = "2026-08-27"
	sources := []pulseNewsSource{
		{Title: "Anthropic launches browser use and Agent Skills GA", Snippet: "Anthropic launched browser use, computer use, Files API, and Agent Skills on August 19, 2026.", URL: "https://specialistone.com/anthropic-agent-tools-ga", PublishedAt: "2026-08-22"},
		{Title: "Anthropic browser use and Agent Skills reach GA", Snippet: "The August 19 Anthropic launch made browser use, computer use, Files API, and Agent Skills generally available.", URL: "https://specialisttwo.net/claude-agent-tools", PublishedAt: "2026-08-21"},
		{Title: "Anthropic ships browser use, Files API, and Agent Skills GA", Snippet: "Anthropic launched browser use, computer use, Files API, and Agent Skills as generally available on August 19.", URL: "https://specialistthree.org/anthropic-ga", PublishedAt: "2026-08-20"},
	}
	if !pulseNewsSourcesMeetQualityGate(date, pulseSourceTopicHot, sources) {
		t.Fatalf("expected three dated independent specialist sources describing one event to pass, issues=%#v", pulseNewsSourceQualityIssues(date, pulseSourceTopicHot, sources))
	}
	if pulseNewsSourcesMeetQualityGate(date, pulseSourceTopicHot, sources[:2]) {
		t.Fatal("two untrusted specialist sources must still require an official or authoritative source")
	}
}

func TestPulseQualityCorroboratesAnthropicAgentToolsGAFromLiveRetrievalShape(t *testing.T) {
	const date = "2026-08-27"
	if !pulseCopyContainsConcreteEvent("Anthropic把Browser Use与Agent Skills推向GA") {
		t.Fatal("expected a compact GA headline from the live summarizer to count as a concrete product event")
	}
	sources := []pulseNewsSource{
		{
			Title:       "Anthropic Makes AI Agent Tools Production-Ready — Enterprise DNA",
			Snippet:     "Anthropic's August 19 update moves browser use, computer use, and Agent Skills to GA. The Files API and Agent Skills API moved out of beta on the same day.",
			URL:         "https://enterprisedna.co/resources/news/anthropic-browser-use-computer-use-skills-api-enterprise-ga-august-2026/",
			PublishedAt: "2026-08-22",
		},
		{
			Title:       "Claude Platform: Computer Use Skills API Files API 正式 GA — Anthropic's agent stack is now production-ready",
			Snippet:     "On August 20, Anthropic pushed computer use, browser use, the Skills API, and the Files API out of beta in one launch.",
			URL:         "https://topaiproduct.com/2026/08/22/claude-platform-computer-use-skills-api-files-api/",
			PublishedAt: "2026-08-23",
		},
		{
			Title:       "Claude Agent Stack Goes GA: Computer Use, Skills, Files — Web Pulse",
			Snippet:     "Anthropic made computer use, browser use, the Skills API, and the Files API generally available on August 20, 2026.",
			URL:         "https://wpnews.pro/news/claude-agent-stack-goes-ga-computer-use-skills-files",
			PublishedAt: "2026-08-23",
		},
	}
	results := pulseSearchResultsFromNewsSources(sources)
	if !pulseNewsSourcesMeetQualityGate(date, pulseSourceTopicHot, sources) {
		t.Fatalf(
			"expected the live Anthropic GA retrieval shape to corroborate, issues=%#v terms=%#v/%#v/%#v pairs=%v/%v/%v",
			pulseNewsSourceQualityIssues(date, pulseSourceTopicHot, sources),
			pulseCorroborationTerms(results[0]), pulseCorroborationTerms(results[1]), pulseCorroborationTerms(results[2]),
			pulseSearchResultsShareConcreteEvent(results[0], results[1]),
			pulseSearchResultsShareConcreteEvent(results[0], results[2]),
			pulseSearchResultsShareConcreteEvent(results[1], results[2]),
		)
	}
	evidence := pulseSearchEvidence{
		Module:  pulseSourceTopicHot,
		Query:   "Anthropic Makes AI Agent Tools Production-Ready independent news report after 2026-07-28",
		Results: results,
	}
	for left := range results {
		for right := left + 1; right < len(results); right++ {
			if !pulseSearchResultsCorroborate(evidence, results[left], results[right]) {
				t.Fatalf("expected live follow-up pair %d/%d to corroborate", left, right)
			}
		}
	}
	seen := map[string]bool{}
	for _, result := range results[:2] {
		seen[pulseSearchResultDedupeKey(result)] = true
	}
	expanded := pulseExpandGeneratedItemSources(sources[:2], []pulseSearchEvidence{evidence}, seen)
	if len(expanded) != 3 {
		t.Fatalf("expected grounding to attach the third corroborating follow-up source, got %#v", expanded)
	}
}

func TestPulseQualitySearchEvidenceEmptyStateDoesNotClaimSearchUnavailable(t *testing.T) {
	const date = "2026-08-27"
	evidence := []pulseSearchEvidence{{
		Module: pulseSourceTopicHot,
		Query:  "Anthropic latest news",
		Results: []pulseSearchResult{{
			Title:       "Anthropic agent platform commentary",
			Snippet:     "A single source discusses Anthropic agent platform changes.",
			URL:         "https://commentary.example.com/anthropic-agent",
			PublishedAt: "2026-08-26",
		}},
	}}
	modules, items := buildSearchFallbackPulse(date, []models.PulseTopic{{ID: "ai", Name: "AI"}}, nil, evidence, nil)
	if len(items) != 0 {
		t.Fatalf("expected uncorroborated evidence to remain unpublished, got %#v", items)
	}
	for _, module := range modules {
		if strings.Contains(module.Summary, "外网搜索暂不可用") {
			t.Fatalf("retrieval-aware empty state must not claim search was unavailable: %#v", module)
		}
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

	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.NotFound(w, r)
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

func TestPulseQualitySyndicatedHeadlineDoesNotCountAsIndependentCoverage(t *testing.T) {
	const headline = "智能体的下一站，不在聊天框里"
	results := []pulseSearchResult{
		{
			Title:       headline,
			Snippet:     "同一篇稿件介绍智能体调度从线程转向意图与任务。",
			URL:         "https://new.qq.com/rain/a/20260827A01",
			PublishedAt: "2026-08-27",
		},
		{
			Title:       "智能体的下一站, 不在聊天框里",
			Snippet:     "同一篇稿件介绍智能体调度从线程转向意图与任务。",
			URL:         "https://www.toutiao.com/article/123456",
			PublishedAt: "2026-08-27",
		},
	}

	if got := pulseSearchIndependentSourceCount(results); got != 1 {
		t.Fatalf("syndicated copies must count as one publication, got %d", got)
	}
	if pulseClusterAddsIndependentSource(results[:1], results[1]) {
		t.Fatal("a verbatim syndicated headline must not extend a corroborated cluster")
	}
	if pulseSearchResultsShareConcreteEvent(results[0], results[1]) {
		t.Fatal("syndicated copies must not pass the independent same-event check")
	}
	sources := newsSourcesFromSearchResults(results, 5)
	if pulseNewsSourcesMeetQualityGate("2026-08-28", pulseSourceTopicHot, sources) {
		t.Fatalf("syndicated copies passed the publishing quality gate: %#v", sources)
	}
}

func TestPulseQualityDistinctHeadlinesRemainIndependent(t *testing.T) {
	results := []pulseSearchResult{
		{
			Title: "OpenAI 发布 AgentGuard-2 权限控制",
			URL:   "https://openai.com/news/agentguard-2-controls",
		},
		{
			Title: "独立报道确认 AgentGuard-2 已向开发者开放",
			URL:   "https://www.reuters.com/technology/agentguard-2-controls",
		},
	}
	if got := pulseSearchIndependentSourceCount(results); got != 2 {
		t.Fatalf("distinct independently written headlines should remain independent, got %d", got)
	}
	if !pulseClusterAddsIndependentSource(results[:1], results[1]) {
		t.Fatal("distinct independently written coverage should extend the cluster")
	}
}

func TestPulseQualityFallbackPrefersConcreteChineseSourceHeadline(t *testing.T) {
	results := []pulseSearchResult{
		{
			Title:       "OpenAI 公布 GPT-5.6 AgentGuard-2 权限控制",
			Snippet:     "OpenAI 于2026年8月27日发布 GPT-5.6 AgentGuard-2，并向开发者开放新的权限控制。",
			URL:         "https://openai.com/news/gpt-56-agentguard-2",
			PublishedAt: "2026-08-27",
		},
		{
			Title:       "GPT-5.6 AgentGuard-2 权限控制已向开发者开放",
			Snippet:     "独立报道确认 OpenAI 已发布 GPT-5.6 AgentGuard-2 权限控制。",
			URL:         "https://www.reuters.com/technology/gpt-56-agentguard-2",
			PublishedAt: "2026-08-27",
		},
	}
	if got := searchFallbackClusterPreferredHeadline(results); got != results[0].Title {
		t.Fatalf("expected primary-source headline, got %q", got)
	}
	item := searchFallbackClusterItem("2026-08-28", pulseSearchEvidence{
		Module:    pulseSourceTopicHot,
		Query:     "GPT 最新进展",
		Keyword:   "GPT",
		TopicName: "AI",
		Results:   results,
	}, 0)
	if item.Title != results[0].Title {
		t.Fatalf("fallback title should retain the concrete event headline, got %q", item.Title)
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
	oneRecentOneUndated := []pulseSearchResult{
		recent[0],
		{
			Title:   "Independent report confirms OpenAI enterprise agent controls",
			Snippet: "The report describes the same OpenAI enterprise agent controls release.",
			URL:     "https://www.reuters.com/technology/openai-agent-controls-undated",
		},
	}

	if !pulseSearchResultsFreshEnough(date, pulseSourceTopicHot, recent) {
		t.Fatal("expected two recent corroborating sources to pass freshness")
	}
	if pulseSearchResultsFreshEnough(date, pulseSourceTopicHot, stale) {
		t.Fatal("expected stale sources to fail freshness")
	}
	if pulseSearchResultsFreshEnough(date, pulseSourceTopicHot, oneRecentOneStale) {
		t.Fatal("expected a single recent source to be insufficient corroboration")
	}
	if !pulseSearchResultsFreshEnough(date, pulseSourceTopicHot, oneRecentOneUndated) {
		t.Fatal("expected one recent source plus an undated independent corroborating source to pass")
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

	if !pulseSearchResultsFreshEnough(date, pulseSourceTopicHot, results("2026-07-25", "2026-08-22")) {
		t.Fatal("expected Topic sources inside the 30-day window to pass")
	}
	if pulseSearchResultsFreshEnough(date, pulseSourceInterestHot, results("2026-07-24", "2026-08-21")) {
		t.Fatal("expected hot-news sources outside the 30-day window to fail")
	}
	if !pulseSearchResultsFreshEnough(date, pulseSourceMemory, results("2026-07-25", "2026-08-01")) {
		t.Fatal("expected Memory sources inside the 30-day window to pass")
	}
	if pulseSearchResultsFreshEnough(date, pulseSourceMemory, results("2026-07-24", "2026-07-23")) {
		t.Fatal("expected Memory sources older than 30 days to fail")
	}

	topicSuffixes := pulseSearchQuerySuffixesForDate(pulseSourceTopicHot, date)
	memorySuffixes := pulseSearchQuerySuffixesForDate(pulseSourceMemory, date)
	if !strings.Contains(strings.Join(topicSuffixes, " "), "after 2026-07-25") {
		t.Fatalf("expected Topic queries to request the 30-day window, got %#v", topicSuffixes)
	}
	if !strings.Contains(strings.Join(memorySuffixes, " "), "after 2026-07-25") {
		t.Fatalf("expected Memory queries to request the 30-day window, got %#v", memorySuffixes)
	}
}

func TestPulseQualityRecoversPublishedDateFromSearchSnippet(t *testing.T) {
	result := pulseSearchResult{
		Title:   "Claude in Chrome launches for all users",
		Snippet: "Anthropic announced the general availability release on August 26, 2026.",
		URL:     "https://claude.com/blog/claude-in-chrome",
	}
	publishedAt, ok := pulseSearchResultPublishedAt(result)
	if !ok || publishedAt.Format("2006-01-02") != "2026-08-26" {
		t.Fatalf("expected embedded English publication date to be recovered, got %v, %v", publishedAt, ok)
	}
	normalized := normalizePulseSearchResults(
		"2026-08-27",
		pulseSearchQuery{Module: pulseSourceTopicHot, Query: "Claude Chrome launch", TopicName: "Claude"},
		[]bridge.SearchResult{{
			Title:   result.Title,
			Snippet: result.Snippet,
			URL:     result.URL,
			Source:  "web",
		}},
		1,
	)
	if len(normalized) != 1 || normalized[0].PublishedAt != "2026-08-26" {
		t.Fatalf("expected normalized evidence to expose the inferred date to the summarizer, got %#v", normalized)
	}
}

func TestPulseQualityClaudeFollowupUsesCurrentAnnouncementDomain(t *testing.T) {
	if got := pulseOfficialDomainForAnchor([]string{"Anthropic", "Claude", "Chrome"}); got != "claude.com" {
		t.Fatalf("expected Claude product follow-up to use claude.com, got %q", got)
	}
	if !pulseAuthoritativeSearchSource(pulseSearchResult{URL: "https://new.qq.com/rain/a/20260819A02YB300"}) {
		t.Fatal("expected a Tencent News report used by the reference trace to count as authoritative")
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

func TestValidateGeneratedPulsePayloadAllowsMissingModuleCopy(t *testing.T) {
	payload := generatedPulsePayload{Modules: []generatedPulseModule{
		{Key: pulseSourceTopicHot, Items: []generatedPulseItem{{Title: "OpenAI 发布 GPT-5.6"}}},
		{Key: pulseSourceMemory},
		{Key: pulseSourceInterestHot},
	}}

	if err := validateGeneratedPulsePayload(payload, false); err != nil {
		t.Fatalf("module copy should be optional because model conversion supplies defaults: %v", err)
	}

	modules, _ := generatedPayloadToModels("2026-08-27", payload, nil)
	if len(modules) != 3 {
		t.Fatalf("expected all modules, got %#v", modules)
	}
	for _, module := range modules {
		if strings.TrimSpace(module.Title) == "" || strings.TrimSpace(module.Summary) == "" {
			t.Fatalf("expected default copy for %q, got %#v", module.Key, module)
		}
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
					Summary: "OpenAI 发布企业 Agent 权限控制，并向企业管理员开放新的配置入口。官方材料显示，这次更新覆盖权限审批、工具调用范围和运行记录查看，目标是让企业能够限制 Agent 可执行的操作。独立报道确认了相同的发布时间与产品名称，并补充说明首批能力将面向企业客户逐步开放。两份来源对核心功能和开放对象的描述一致，但对后续扩展范围尚未给出更多细节。",
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

	verifiedClusters := pulseVerifiedSearchClusters(date, evidence)
	if len(verifiedClusters) != 1 {
		t.Fatalf("expected one verified OpenAI cluster, got %#v", verifiedClusters)
	}
	// Even an exact evidence id cannot rescue unrelated copy.
	payload.Modules[0].Items[1].EvidenceID = verifiedClusters[0].QueryID
	groundingEvidence := append(append([]pulseSearchEvidence{}, evidence...), verifiedClusters...)
	filtered, rejections := filterGeneratedPulsePayloadByEvidenceWithDiagnostics(date, payload, groundingEvidence)
	if len(rejections) != 1 {
		t.Fatalf("expected one hallucinated item to be rejected, got %#v", rejections)
	}
	if !strings.Contains(strings.Join(rejections[0].Reasons, ","), "no_matching_search_source") {
		t.Fatalf("expected a specific grounding rejection reason, got %#v", rejections[0])
	}
	if got := generatedPulseItemCount(filtered); got != 1 {
		t.Fatalf("expected only the grounded item to remain, got %d: %#v", got, filtered)
	}
	sources := filtered.Modules[0].Items[0].NewsSources
	if len(sources) != 2 || sources[0].PublishedAt == "" || sources[1].PublishedAt == "" {
		t.Fatalf("expected only the corroborating source component to be copied from evidence, got %#v", sources)
	}
	_, converted := generatedPayloadToModels(date, filtered, nil)
	published, publishingRejections := filterPulseItemsForPublishingWithDiagnostics(converted)
	if len(published) != 1 || len(publishingRejections) != 0 {
		t.Fatalf("grounded valid copy must remain publishable after model conversion, published=%#v rejected=%#v", published, publishingRejections)
	}
}

func TestPulseQualityGroundingCanCorroborateAcrossPresentationModules(t *testing.T) {
	const date = "2026-08-27"
	results := []pulseSearchResult{
		{Title: "Anthropic Makes AI Agent Tools Production-Ready", Snippet: "Anthropic moved browser use, computer use, Files API, and Agent Skills to GA on August 19.", URL: "https://enterprisedna.co/news/anthropic-agent-tools-ga", PublishedAt: "2026-08-22"},
		{Title: "Claude Platform computer use and Skills API reach GA", Snippet: "Anthropic made browser use, computer use, Files API, and Agent Skills generally available on August 20.", URL: "https://topaiproduct.com/claude-agent-tools-ga", PublishedAt: "2026-08-22"},
		{Title: "Claude Agent Stack Goes GA: Computer Use, Skills, Files", Snippet: "Anthropic shipped browser use, computer use, Files API, and Agent Skills out of beta on August 20.", URL: "https://wpnews.pro/news/claude-agent-stack-ga", PublishedAt: "2026-08-23"},
	}
	evidence := []pulseSearchEvidence{
		{Module: pulseSourceTopicHot, Query: "Anthropic Agent tools latest", Results: results[:2]},
		{Module: pulseSourceInterestHot, Query: "Anthropic Makes AI Agent Tools Production-Ready independent news report", Results: results},
	}
	payload := generatedPulsePayload{Modules: []generatedPulseModule{{
		Key: pulseSourceTopicHot,
		Items: []generatedPulseItem{{
			Title:   "Anthropic 推进 Agent 工具生产化：browser use、computer use 与 Skills 全面 GA",
			Summary: "Anthropic 在 8 月将 browser use、computer use、Files API 与 Agent Skills 推进至正式可用阶段。三个独立专业来源对产品名称、GA 状态和发布时间给出了相互一致的描述，并共同指出相关能力已经退出测试状态。现阶段可以确认的是工具与 API 的可用性变化；各来源未共同支持的性能数字、迁移成本和商业影响不纳入结论，后续仍应以官方文档更新为准。",
			NewsSources: []pulseNewsSource{
				{URL: results[0].URL},
				{URL: results[1].URL},
			},
		}},
	}}}

	filtered, rejections := filterGeneratedPulsePayloadByEvidenceWithDiagnostics(date, payload, evidence)
	if len(rejections) != 0 || generatedPulseItemCount(filtered) != 1 {
		t.Fatalf("expected cross-module evidence to ground the item, filtered=%#v rejections=%#v", filtered, rejections)
	}
	if got := len(filtered.Modules[0].Items[0].NewsSources); got != 3 {
		t.Fatalf("expected the corroborating interest result to be attached to the topic item, got %d", got)
	}
	_, converted := generatedPayloadToModels(date, filtered, nil)
	published, publishingRejections := filterPulseItemsForPublishingWithDiagnostics(converted)
	if len(published) != 1 || len(publishingRejections) != 0 {
		t.Fatalf("expected the grounded GA item to publish, published=%#v rejected=%#v", published, publishingRejections)
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
		"150-400 个中文字符",
		"verified_clusters",
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
	if length := len([]rune(item.Summary)); length < pulseSummaryMinRunes || length > pulseSummaryMaxRunes {
		t.Fatalf("fallback summary must contain %d-%d characters, got %d: %q", pulseSummaryMinRunes, pulseSummaryMaxRunes, length, item.Summary)
	}
	if strings.Contains(item.Title, "、") {
		t.Fatalf("fallback title must describe one event subject instead of joining entities: %q", item.Title)
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

func containsString(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}
