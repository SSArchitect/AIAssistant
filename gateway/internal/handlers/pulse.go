package handlers

import (
	"context"
	"encoding/json"
	"fmt"
	"hash/fnv"
	"html"
	"log/slog"
	"net"
	"net/http"
	"net/url"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"golang.org/x/net/publicsuffix"
	"gorm.io/gorm"
)

type PulseHandler struct {
	agent               *bridge.AgentClient
	syncer              *ConfigSyncer
	generationLocksMu   sync.Mutex
	generationLocks     map[string]*pulseGenerationLock
	jobsMu              sync.Mutex
	jobs                map[string]pulseGenerationJob
	automaticScheduleMu sync.Mutex
}

type pulseGenerationLock struct {
	mu         sync.Mutex
	references int
}

type pulseGenerationJob struct {
	StartedAt time.Time
	Stage     string
}

type pulseTopicRequest struct {
	Name     string   `json:"name"`
	Keywords []string `json:"keywords"`
	UserID   string   `json:"user_id,omitempty"`
}

type pulseRefreshRequest struct {
	Date   string `json:"date"`
	UserID string `json:"user_id,omitempty"`
	Wait   bool   `json:"wait,omitempty"`
}

type pulseEventRequest struct {
	Date      string                 `json:"date,omitempty"`
	ItemID    string                 `json:"item_id"`
	EventType string                 `json:"event_type"`
	Value     *int                   `json:"value,omitempty"`
	Metadata  map[string]interface{} `json:"metadata,omitempty"`
	UserID    string                 `json:"user_id,omitempty"`
}

type pulseNewsSource struct {
	Title       string `json:"title"`
	URL         string `json:"url"`
	Source      string `json:"source,omitempty"`
	Snippet     string `json:"snippet,omitempty"`
	PublishedAt string `json:"published_at,omitempty"`
}

type pulseTopicResponse struct {
	ID        string    `json:"id"`
	Name      string    `json:"name"`
	Keywords  []string  `json:"keywords"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
}

type pulseSuggestedTopicResponse struct {
	Name      string   `json:"name"`
	Keywords  []string `json:"keywords"`
	Reason    string   `json:"reason"`
	Source    string   `json:"source"`
	HeatScore int      `json:"heat_score"`
}

type pulseRelatedClusterResponse struct {
	ID        string `json:"id"`
	Source    string `json:"source"`
	TopicName string `json:"topic_name,omitempty"`
	Title     string `json:"title"`
	Summary   string `json:"summary"`
	Reason    string `json:"reason"`
	HeatScore int    `json:"heat_score"`
}

type pulseItemFeedbackResponse struct {
	Liked         bool   `json:"liked"`
	Vote          string `json:"vote,omitempty"`
	LikeCount     int    `json:"like_count"`
	UpvoteCount   int    `json:"upvote_count"`
	DownvoteCount int    `json:"downvote_count"`
	OpenCount     int    `json:"open_count"`
	ExposureCount int    `json:"exposure_count"`
}

type pulseItemDetail struct {
	ContentVersion       int               `json:"content_version,omitempty"`
	EvidenceMode         string            `json:"evidence_mode,omitempty"`
	RecommendationReason string            `json:"recommendation_reason"`
	Signals              []string          `json:"signals"`
	QuickContext         string            `json:"quick_context"`
	KeyPoints            []string          `json:"key_points"`
	NewsSources          []pulseNewsSource `json:"news_sources,omitempty"`
	SuggestedQuestions   []string          `json:"suggested_questions"`
	PrecomputedAt        string            `json:"precomputed_at"`
}

type pulseItemResponse struct {
	ID                 string                        `json:"id"`
	ClusterKey         string                        `json:"cluster_key,omitempty"`
	Date               string                        `json:"date"`
	TopicID            string                        `json:"topic_id,omitempty"`
	TopicName          string                        `json:"topic_name,omitempty"`
	Source             string                        `json:"source"`
	Category           string                        `json:"category,omitempty"`
	Title              string                        `json:"title"`
	Summary            string                        `json:"summary"`
	HeatScore          int                           `json:"heat_score"`
	Detail             pulseItemDetail               `json:"detail"`
	ExplorePrompt      string                        `json:"explore_prompt,omitempty"`
	RelatedClusters    []pulseRelatedClusterResponse `json:"related_clusters,omitempty"`
	Feedback           pulseItemFeedbackResponse     `json:"feedback"`
	FeatureScore       int                           `json:"feature_score"`
	RecommendationNote string                        `json:"recommendation_note,omitempty"`
	CreatedAt          time.Time                     `json:"created_at"`
	UpdatedAt          time.Time                     `json:"updated_at"`
}

type pulseModuleResponse struct {
	Key     string              `json:"key"`
	Title   string              `json:"title"`
	Summary string              `json:"summary"`
	Items   []pulseItemResponse `json:"items"`
}

type memoryPulseSignal struct {
	Theme    string
	Focus    string
	Count    int
	Keywords []string
	Snippets []string
}

type generatedPulsePayload struct {
	Modules []generatedPulseModule `json:"modules"`
}

type pulseGenerationInput struct {
	Date             string                `json:"date"`
	UserID           string                `json:"user_id"`
	VerifiedClusters []pulseSearchEvidence `json:"verified_clusters"`
	MemorySignals    []memoryPulseSignal   `json:"memory_signals"`
	RetrievalSummary map[string]int        `json:"retrieval_summary"`
}

type generatedPulseModule struct {
	Key     string               `json:"key"`
	Title   string               `json:"title"`
	Summary string               `json:"summary"`
	Items   []generatedPulseItem `json:"items"`
}

type generatedPulseItem struct {
	EvidenceID           string            `json:"evidence_id"`
	TopicID              string            `json:"topic_id"`
	TopicName            string            `json:"topic_name"`
	Category             string            `json:"category"`
	Title                string            `json:"title"`
	Summary              string            `json:"summary"`
	HeatScore            int               `json:"heat_score"`
	RecommendationReason string            `json:"recommendation_reason"`
	Signals              []string          `json:"signals"`
	QuickContext         string            `json:"quick_context"`
	KeyPoints            []string          `json:"key_points"`
	NewsSources          []pulseNewsSource `json:"news_sources"`
	Sources              []pulseNewsSource `json:"sources"`
	SuggestedQuestions   []string          `json:"suggested_questions"`
	ExplorePrompt        string            `json:"explore_prompt"`
	EvidenceMode         string            `json:"-"`
}

type pulseQuestionContext struct {
	Title     string
	Summary   string
	Module    string
	TopicName string
	Query     string
	Intent    string
	Category  string
	KeyPoints []string
	Context   string
	Sources   []pulseNewsSource
}

type pulseSearchQuery struct {
	ID        string `json:"id"`
	Module    string `json:"module"`
	Query     string `json:"query"`
	Intent    string `json:"intent"`
	Keyword   string `json:"keyword,omitempty"`
	TopicID   string `json:"topic_id,omitempty"`
	TopicName string `json:"topic_name,omitempty"`
}

type pulseSearchEvidence struct {
	QueryID          string              `json:"query_id"`
	Stage            string              `json:"stage,omitempty"`
	ParentQueryID    string              `json:"parent_query_id,omitempty"`
	Module           string              `json:"module"`
	Query            string              `json:"query"`
	Intent           string              `json:"intent"`
	Keyword          string              `json:"keyword,omitempty"`
	TopicID          string              `json:"topic_id,omitempty"`
	TopicName        string              `json:"topic_name,omitempty"`
	ProviderErrors   []string            `json:"provider_errors,omitempty"`
	RewrittenQueries []string            `json:"rewritten_queries,omitempty"`
	Results          []pulseSearchResult `json:"results"`
	Error            string              `json:"error,omitempty"`
}

type pulseSearchResult struct {
	Title       string `json:"title"`
	Snippet     string `json:"snippet,omitempty"`
	URL         string `json:"url,omitempty"`
	Source      string `json:"source,omitempty"`
	PublishedAt string `json:"published_at,omitempty"`
}

type pulseRetrievalDiagnostics struct {
	Queries             []pulseRetrievalQueryDiagnostic     `json:"queries"`
	RawCandidateCount   int                                 `json:"raw_candidate_count,omitempty"`
	GroundedItemCount   int                                 `json:"grounded_item_count,omitempty"`
	CandidateRejections []pulseCandidateRejectionDiagnostic `json:"candidate_rejections,omitempty"`
}

type pulseRetrievalQueryDiagnostic struct {
	QueryID          string                           `json:"query_id"`
	Stage            string                           `json:"stage,omitempty"`
	ParentQueryID    string                           `json:"parent_query_id,omitempty"`
	Module           string                           `json:"module"`
	Query            string                           `json:"query"`
	Intent           string                           `json:"intent"`
	Keyword          string                           `json:"keyword,omitempty"`
	TopicID          string                           `json:"topic_id,omitempty"`
	TopicName        string                           `json:"topic_name,omitempty"`
	ResultCount      int                              `json:"result_count"`
	Error            string                           `json:"error,omitempty"`
	ProviderErrors   []string                         `json:"provider_errors,omitempty"`
	RewrittenQueries []string                         `json:"rewritten_queries,omitempty"`
	Results          []pulseRetrievalResultDiagnostic `json:"results,omitempty"`
}

type pulseCandidateRejectionDiagnostic struct {
	Stage         string   `json:"stage"`
	Module        string   `json:"module,omitempty"`
	TopicID       string   `json:"topic_id,omitempty"`
	TopicName     string   `json:"topic_name,omitempty"`
	Title         string   `json:"title,omitempty"`
	Reasons       []string `json:"reasons"`
	SourceCount   int      `json:"source_count"`
	SourceDomains []string `json:"source_domains,omitempty"`
}

type pulseGenerationDiagnostics struct {
	RawCandidateCount   int
	GroundedItemCount   int
	CandidateRejections []pulseCandidateRejectionDiagnostic
}

type pulseRetrievalResultDiagnostic struct {
	Title       string `json:"title"`
	URL         string `json:"url,omitempty"`
	Source      string `json:"source,omitempty"`
	PublishedAt string `json:"published_at,omitempty"`
	Snippet     string `json:"snippet,omitempty"`
}

type pulseTopicOptimizationMetric struct {
	TopicID                   string          `json:"topic_id"`
	TopicName                 string          `json:"topic_name"`
	StoredClusters            int             `json:"stored_clusters"`
	QualityPassedAtGeneration int             `json:"quality_passed_at_generation"`
	QualityFailedAtGeneration int             `json:"quality_failed_at_generation"`
	SourceCount               int             `json:"source_count"`
	UniqueSourceDomains       []string        `json:"unique_source_domains"`
	LastClusterAt             string          `json:"last_cluster_at,omitempty"`
	Engagement                map[string]int  `json:"engagement"`
	sourceDomainSet           map[string]bool `json:"-"`
}

type pulseTopicOverlapCandidate struct {
	LeftTopicID    string   `json:"left_topic_id"`
	LeftTopicName  string   `json:"left_topic_name"`
	RightTopicID   string   `json:"right_topic_id"`
	RightTopicName string   `json:"right_topic_name"`
	SharedKeywords []string `json:"shared_keywords"`
	OverlapScore   int      `json:"overlap_score"`
}

type scoredPulseSearchResult struct {
	Result pulseSearchResult
	Score  int
	Index  int
}

type pulseSearchFollowupSeed struct {
	EvidenceIndex int
	Result        pulseSearchResult
	Score         int
	Index         int
}

type pulseSearchFollowupPlan struct {
	Seed  pulseSearchFollowupSeed
	Kind  string
	Query pulseSearchQuery
}

const (
	pulseSourceTopicHot    = "topic_hot"
	pulseSourceMemory      = "memory"
	pulseSourceInterestHot = "interest_hot"

	pulseEventExposure = "exposure"
	pulseEventOpen     = "open"
	pulseEventLike     = "like"
	pulseEventUpvote   = "upvote"
	pulseEventDownvote = "downvote"

	pulseSchedulerTickInterval       = 30 * time.Minute
	pulseScheduledRefreshInterval    = 6 * time.Hour
	pulseActiveAccountWindow         = 7 * 24 * time.Hour
	pulseAutomaticFailureRetryBase   = 12 * time.Hour
	pulseAutomaticFailureRetryLimit  = 24 * time.Hour
	pulseSearchConcurrency           = 4
	pulseSearchLightConcurrency      = 16
	pulseSearchFullModeQueryLimit    = 16
	pulseSearchFollowupConcurrency   = 8
	pulseSearchResultLimit           = 6
	pulseSearchRawResultLimit        = 10
	pulseSearchFollowupResultLimit   = 6
	pulseSearchExpandedResultLimit   = 10
	pulseSearchClusterCandidateLimit = 36
	pulseSearchClusterMaxSources     = 5
	pulseGenerationClusterLimit      = 12
	pulseGenerationSourceLimit       = 3
	pulseGenerationSnippetLimit      = 360
	pulseCandidateTargetCount        = 12
	pulseCandidateMaxCount           = 18
	pulseVisibleItemLimit            = 12
	pulseOpenFilterThreshold         = 3
	pulseExposureFilterThreshold     = 8
	pulseFeatureEventLimit           = 1000
	pulseTopicFreshnessWindow        = 30 * 24 * time.Hour
	pulseMemoryFreshnessWindow       = 30 * 24 * time.Hour
	pulseWelcomeSuggestionMaxAge     = 7 * 24 * time.Hour
	pulseRetrievalHistoryRetention   = 90 * 24 * time.Hour
	pulseFutureDateTolerance         = 48 * time.Hour
	pulseSearchBudget                = 85 * time.Second
	pulseGenerationBudget            = 180 * time.Second
	pulseSuggestedQuestionLimit      = 3
	pulseSuggestedQuestionMaxRunes   = 32
	pulseRecommendationMaxRunes      = 56
	pulseSummaryMinRunes             = 150
	pulseSummaryMaxRunes             = 400
	pulseContentVersion              = 3
	pulseGenerationStagePreparing    = "preparing"
	pulseGenerationStageSearching    = "searching"
	pulseGenerationStageSummarizing  = "summarizing"
	pulseGenerationStageSaving       = "saving"
)

var pulseModuleOrder = []string{
	pulseSourceTopicHot,
	pulseSourceMemory,
	pulseSourceInterestHot,
}

var pulseBackgroundDisabledTools = []string{
	"search",
	"get_pulse",
	"refresh_pulse",
	"list_pulse_topics",
	"optimize_pulse_topics",
	"upsert_pulse_topic",
	"delete_pulse_topic",
}

var pulseModelEntityPattern = regexp.MustCompile(`(?i)\b(?:gpt|claude|gemini|llama|grok|fable|mythos|deepseek|qwen|kimi|mistral|sora|dall-e|o[0-9])(?:[-\s]?[a-z0-9.]+)?\b`)
var pulseCapitalizedTermPattern = regexp.MustCompile(`\b[A-Z][A-Za-z0-9.-]{2,}\b`)
var pulseSearchAnchorTokenPattern = regexp.MustCompile(`[A-Za-z][A-Za-z0-9]*(?:[._-][A-Za-z0-9]+)*|[\p{Han}]{2,12}`)
var pulseISODatePattern = regexp.MustCompile(`\b(20[0-9]{2})[-/.](0?[1-9]|1[0-2])[-/.](0?[1-9]|[12][0-9]|3[01])\b`)
var pulseChineseDatePattern = regexp.MustCompile(`(20[0-9]{2})年(0?[1-9]|1[0-2])月(0?[1-9]|[12][0-9]|3[01])日`)
var pulseEnglishMonthDatePattern = regexp.MustCompile(`(?i)\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+[0-3]?[0-9],?\s+20[0-9]{2}\b`)
var pulseEnglishDayMonthDatePattern = regexp.MustCompile(`(?i)\b[0-3]?[0-9]\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+20[0-9]{2}\b`)
var pulseGeneralAvailabilityPattern = regexp.MustCompile(`(?i)(?:\bga\b|general availability|generally available|out of beta|生产化|正式可用)`)
var pulseArabicQuantitativeClaimPattern = regexp.MustCompile(`(?i)[0-9]+(?:\.[0-9]+)?\s*(?:%|％|倍|万|亿|家|款|个|项|起|年|月|日|million|billion|percent|x)?`)
var pulseChineseQuantitativeClaimPattern = regexp.MustCompile(`[零一二三四五六七八九十百千万亿两]+(?:%|％|倍|万|亿|家|款|个|项|起|年|月|日)`)

var pulseKnownEntities = []string{
	"GPT-5.6", "GPT-5", "GPT-4.5", "GPT-4o", "ChatGPT", "OpenAI",
	"Claude", "Anthropic", "Gemini", "DeepMind", "Google", "Llama",
	"Meta", "Grok", "xAI", "DeepSeek", "Qwen", "Kimi", "Mistral",
	"Sora", "Fable", "Mythos", "具身智能", "机器人",
}

var pulseConcreteEventTerms = []string{
	"发布", "推出", "上线", "开放", "开源", "宣布", "公布", "披露",
	"更新", "升级", "新增", "支持", "接入", "集成", "扩展", "部署",
	"收购", "融资", "合作", "签署", "获批", "通过", "完成", "测试",
	"停售", "停用", "下线", "下架", "关闭", "召回", "修复", "转向",
	"走向", "采用", "引入", "计划", "申请", "提交", "任命", "离职",
	"起诉", "调查", "裁员", "限制", "禁止", "要求", "增长", "下降",
	"提升", "降低", "增加", "减少", "扩至", "增至", "升至", "降至",
	"达到", "超过", "突破", "缩短", "延长", "翻倍",
	"生产化", "正式可用", "全面 GA", "进入 GA", "退出测试",
	"released", "releases", "release", "launched", "launches", "launch",
	"announced", "announces", "announce", "unveiled", "unveils", "unveil",
	"updated", "updates", "upgraded", "acquired", "acquires", "acquire",
	"funded", "funding", "partnered", "partners", "deployed", "deploys",
	"expanded", "expands", "integrated", "integrates", "discontinued",
	"generally available", "general availability", "production-ready", "out of beta",
	"shut down", "recalled", "fixed", "increased", "decreased", "grew",
	"fell", "rose", "reached", "exceeded",
}

var pulseGenericNewsCopyFragments = []string{
	"近期资讯聚合",
	"新线索值得跟踪",
	"值得继续跟踪",
	"值得关注",
	"待核验线索",
	"待核验",
	"仍待确认",
	"需要核验",
	"新动向",
	"有新信息",
	"有新进展",
	"新的外部资讯信号",
	"新的资讯信号",
	"发布与开放信号待核验",
	"发布时间与版本细节待核验",
	"能力表现和评测口径待核验",
	"具体事实仍需要打开",
	"具体事实、发布时间和上下文",
	"搜索摘要聚合",
	"适合作为今日快速了解入口",
	"主要涉及事实更新",
	"不足以判断明确变化",
}

func NewPulseHandler(agents ...*bridge.AgentClient) *PulseHandler {
	var agent *bridge.AgentClient
	if len(agents) > 0 {
		agent = agents[0]
	}
	return &PulseHandler{agent: agent, jobs: map[string]pulseGenerationJob{}}
}

func NewPulseHandlerWithSyncer(agent *bridge.AgentClient, syncer *ConfigSyncer) *PulseHandler {
	return &PulseHandler{agent: agent, syncer: syncer, jobs: map[string]pulseGenerationJob{}}
}

func (h *PulseHandler) StartScheduler() {
	go func() {
		ticker := time.NewTicker(pulseSchedulerTickInterval)
		defer ticker.Stop()
		for range ticker.C {
			h.runScheduledPulse("tick")
		}
	}()
}

func (h *PulseHandler) runScheduledPulse(reason string) {
	// Automatic work is deliberately serialized. A manual refresh or another
	// account's generation gets priority and the next scheduler tick will pick
	// up anything still due.
	if h.pulseGenerationAnyActive() {
		return
	}
	date := time.Now().Format("2006-01-02")
	for _, userID := range h.scheduledPulseUserIDs() {
		needsRefresh, err := h.needsScheduledRefresh(date, userID)
		if err != nil {
			slog.Warn("Pulse scheduled check failed", "reason", reason, "user_id", userID, "error", err)
			continue
		}
		if !needsRefresh {
			continue
		}
		if ok := h.startPulseGeneration(date, userID, true, "scheduled:"+reason); ok {
			// Start at most one expensive automatic generation per scheduler tick.
			return
		}
	}
}

func (h *PulseHandler) scheduledPulseUserIDs() []string {
	var sessions []models.AccountSession
	cutoff := time.Now().Add(-pulseActiveAccountWindow)
	if err := database.DB.
		Where("last_used_at >= ?", cutoff).
		Order("last_used_at desc").
		Find(&sessions).Error; err != nil {
		slog.Warn("Pulse active account load failed", "error", err)
		return nil
	}
	userIDs := make([]string, 0, len(sessions))
	seen := map[string]bool{}
	for _, session := range sessions {
		userID := normalizedUserID(session.UserID)
		if seen[userID] {
			continue
		}
		seen[userID] = true
		userIDs = append(userIDs, userID)
	}
	return userIDs
}

func (h *PulseHandler) needsScheduledRefresh(date string, userID string) (bool, error) {
	ok, err := h.hasCurrentPulseShape(date, userID)
	if err != nil || !ok {
		return !ok, err
	}

	var item models.PulseItem
	if err := database.DB.Where("date = ? AND user_id = ?", date, normalizedUserID(userID)).Order("updated_at desc").First(&item).Error; err != nil {
		return true, nil
	}
	return time.Since(item.UpdatedAt) >= pulseScheduledRefreshInterval, nil
}

func (h *PulseHandler) Get(c *gin.Context) {
	userID := requestUserID(c)
	date, ok := requestedPulseDate(c.Query("date"))
	if !ok {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid date, expected YYYY-MM-DD"})
		return
	}
	hasHealthyContent, err := h.hasCurrentPulseShape(date, userID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to prepare pulse: " + err.Error()})
		return
	}
	if !hasHealthyContent && h.agent != nil {
		h.startPulseGeneration(date, userID, false, "get_quality_refresh")
	}
	h.writePulseWithStatus(c, date, userID, h.pulseGenerationActive(date, userID))
}

func (h *PulseHandler) Refresh(c *gin.Context) {
	var req pulseRefreshRequest
	_ = c.ShouldBindJSON(&req)
	userID := requestUserIDWithBody(c, req.UserID)

	dateText := req.Date
	if dateText == "" {
		dateText = c.Query("date")
	}
	date, ok := requestedPulseDate(dateText)
	if !ok {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid date, expected YYYY-MM-DD"})
		return
	}
	if req.Wait || c.Query("wait") == "true" {
		if err := h.ensureDailyPulse(date, userID, true); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to refresh pulse: " + err.Error()})
			return
		}
		h.writePulse(c, date, userID)
		return
	}
	h.startPulseGeneration(date, userID, true, "manual_refresh")
	h.writePulseWithStatus(c, date, userID, h.pulseGenerationActive(date, userID))
}

func (h *PulseHandler) ListTopics(c *gin.Context) {
	userID := requestUserID(c)
	topics, err := h.loadTopics(userID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load topics"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"topics": topicResponses(topics)})
}

func (h *PulseHandler) TopicOptimizationContext(c *gin.Context) {
	userID := requestUserID(c)
	lookbackDays := pulseTopicOptimizationLookbackDays(c.Query("lookback_days"))
	cutoff := time.Now().Add(-time.Duration(lookbackDays) * 24 * time.Hour)

	topics, err := h.loadTopics(userID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load topics"})
		return
	}
	memorySignals, err := h.loadMemorySignals(userID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load recent memory signals"})
		return
	}

	var messages []models.Message
	if err := database.DB.
		Where("user_id = ? AND role = ? AND created_at >= ?", normalizedUserID(userID), "user", cutoff).
		Order(messageReverseChronologicalOrder).
		Limit(80).
		Find(&messages).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load recent user context"})
		return
	}

	cutoffDate := cutoff.Format("2006-01-02")
	var items []models.PulseItem
	if err := database.DB.
		Where("user_id = ? AND date >= ?", normalizedUserID(userID), cutoffDate).
		Order("created_at desc").
		Limit(200).
		Find(&items).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load pulse history"})
		return
	}
	var modules []models.PulseModule
	if err := database.DB.
		Where("user_id = ? AND date >= ?", normalizedUserID(userID), cutoffDate).
		Order("created_at desc").
		Limit(60).
		Find(&modules).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load pulse module history"})
		return
	}
	var events []models.PulseEvent
	if err := database.DB.
		Where("user_id = ? AND created_at >= ?", normalizedUserID(userID), cutoff).
		Order("created_at desc").
		Limit(pulseFeatureEventLimit).
		Find(&events).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load pulse feedback history"})
		return
	}
	var retrievalRuns []models.PulseRetrievalRun
	if err := database.DB.
		Where("user_id = ? AND created_at >= ?", normalizedUserID(userID), cutoff).
		Order("created_at desc").
		Limit(12).
		Find(&retrievalRuns).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load pulse retrieval history"})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"generated_at":               time.Now().Format(time.RFC3339),
		"lookback_days":              lookbackDays,
		"current_topics":             topicResponses(topics),
		"candidate_interest_signals": pulseTopicOptimizationMemorySignals(memorySignals),
		"recent_user_intents":        pulseTopicOptimizationRecentIntents(messages),
		"history":                    buildPulseTopicOptimizationHistory(topics, items, modules, events, retrievalRuns),
		"topic_semantics": gin.H{
			"existing_topics_source":                         "current_topics_only",
			"candidate_interest_signals_are_existing_topics": false,
			"historical_clusters_are_existing_topics":        false,
			"management_actions":                             []string{"add", "update", "delete"},
		},
		"workflow": gin.H{
			"analysis_only": true,
			"instruction":   "只有 current_topics 是现有 Topic；candidate_interest_signals 和历史信息簇只是证据，绝不能称为现有 Topic。结合证据提出 Topic 合并、保留、改名、删除和关键词调整方案；先向用户展示理由与变更，再在用户明确确认后调用 upsert_pulse_topic 或 delete_pulse_topic。",
		},
	})
}

func (h *PulseHandler) CreateTopic(c *gin.Context) {
	var req pulseTopicRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}
	userID := requestUserIDWithBody(c, req.UserID)

	name := normalizeTopicName(req.Name)
	if name == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "topic name is required"})
		return
	}

	keywordsJSON := encodeKeywords(expandPulseTopicKeywords(name, req.Keywords))
	var existing models.PulseTopic
	err := database.DB.Where("user_id = ? AND lower(name) = lower(?)", userID, name).First(&existing).Error
	if err == nil {
		existing.Keywords = keywordsJSON
		existing.UpdatedAt = time.Now()
		if err := database.DB.Save(&existing).Error; err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to save topic"})
			return
		}
		c.JSON(http.StatusOK, gin.H{"topic": topicResponse(existing)})
		return
	}

	topic := models.PulseTopic{
		ID:        uuid.NewString(),
		UserID:    userID,
		Name:      name,
		Keywords:  keywordsJSON,
		CreatedAt: time.Now(),
		UpdatedAt: time.Now(),
	}
	if err := database.DB.Create(&topic).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to create topic"})
		return
	}
	c.JSON(http.StatusCreated, gin.H{"topic": topicResponse(topic)})
}

func (h *PulseHandler) UpdateTopic(c *gin.Context) {
	id := c.Param("id")
	userID := requestUserID(c)
	var topic models.PulseTopic
	if err := database.DB.First(&topic, "id = ? AND user_id = ?", id, userID).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "topic not found"})
		return
	}

	var req pulseTopicRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}

	if name := normalizeTopicName(req.Name); name != "" {
		topic.Name = name
	}
	if req.Keywords != nil {
		topic.Keywords = encodeKeywords(req.Keywords)
	}
	topic.UpdatedAt = time.Now()

	if err := database.DB.Save(&topic).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to update topic"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"topic": topicResponse(topic)})
}

func (h *PulseHandler) DeleteTopic(c *gin.Context) {
	id := c.Param("id")
	userID := requestUserID(c)
	result := database.DB.Delete(&models.PulseTopic{}, "id = ? AND user_id = ?", id, userID)
	if result.Error != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to delete topic"})
		return
	}
	if result.RowsAffected == 0 {
		c.JSON(http.StatusNotFound, gin.H{"error": "topic not found"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"status": "deleted"})
}

func (h *PulseHandler) RecordEvent(c *gin.Context) {
	var req pulseEventRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}
	userID := requestUserIDWithBody(c, req.UserID)
	eventType := normalizePulseEventType(req.EventType)
	if eventType == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "unsupported pulse event type"})
		return
	}
	itemID := strings.TrimSpace(req.ItemID)
	if itemID == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "item_id is required"})
		return
	}

	var item models.PulseItem
	if err := database.DB.First(&item, "id = ? AND user_id = ?", itemID, userID).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "pulse item not found"})
		return
	}

	value := defaultPulseEventValue(eventType)
	if req.Value != nil {
		value = normalizePulseEventValue(eventType, *req.Value)
	}
	metadata := map[string]interface{}{}
	for key, value := range req.Metadata {
		metadata[key] = value
	}
	if key := pulseClusterKey(item); key != "" {
		metadata["cluster_key"] = key
	}
	metadataJSON := ""
	if len(metadata) > 0 {
		metadataJSON = limitText(mustJSON(metadata), 2000)
	}
	event := models.PulseEvent{
		ID:           uuid.NewString(),
		UserID:       userID,
		Date:         firstNonEmptyPulse(req.Date, item.Date),
		ItemID:       item.ID,
		TopicID:      item.TopicID,
		TopicName:    item.TopicName,
		Source:       item.Source,
		EventType:    eventType,
		Value:        value,
		MetadataJSON: metadataJSON,
		CreatedAt:    time.Now(),
	}
	if err := database.DB.Create(&event).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to record pulse event"})
		return
	}

	featureState, err := loadPulseFeatureState(userID, item.Date, []models.PulseItem{item})
	if err != nil {
		slog.Warn("Pulse event recorded but feature state load failed", "item_id", item.ID, "error", err)
	}
	c.JSON(http.StatusOK, gin.H{
		"status":   "recorded",
		"event_id": event.ID,
		"feedback": featureState.feedbackFor(item.ID),
	})
}

func (h *PulseHandler) writePulse(c *gin.Context, date string, userID string) {
	h.writePulseWithStatus(c, date, userID, false)
}

func (h *PulseHandler) writePulseWithStatus(c *gin.Context, date string, userID string, refreshing bool) {
	userID = normalizedUserID(userID)
	topics, err := h.loadTopics(userID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load topics"})
		return
	}

	var items []models.PulseItem
	if err := database.DB.Where("date = ? AND user_id = ?", date, userID).Order("heat_score desc, created_at asc").Find(&items).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load pulse items"})
		return
	}
	items, cacheUpgrades := revalidatePulseCachedItems(items)
	if err := persistPulseCachedItemUpgrades(cacheUpgrades); err != nil {
		slog.Warn(
			"Pulse legacy cache upgrade failed",
			"user_id", userID,
			"date", date,
			"items", len(cacheUpgrades),
			"error", err,
		)
	}
	var modules []models.PulseModule
	if err := database.DB.Where("date = ? AND user_id = ?", date, userID).Find(&modules).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load pulse modules"})
		return
	}
	featureState, err := loadPulseFeatureState(userID, date, items)
	if err != nil {
		slog.Warn("Pulse feature state load failed", "user_id", userID, "date", date, "error", err)
	}
	allItems := items
	items = recommendedPulseItems(allItems, featureState)
	suggestionItems, suggestionDate, suggestionErr := h.loadPulseWelcomeSuggestionItems(
		date,
		userID,
		items,
		allItems,
		featureState,
	)
	if suggestionErr != nil {
		slog.Warn("Pulse welcome suggestion fallback failed", "user_id", userID, "date", date, "error", suggestionErr)
	}

	memorySignals, err := h.loadMemorySignals(userID)
	if err != nil {
		slog.Warn("Pulse memory signal load failed for suggested topics", "user_id", userID, "error", err)
	}

	generatedAt := ""
	if len(modules) > 0 {
		generatedAt = modules[0].CreatedAt.Format(time.RFC3339)
	} else if len(items) > 0 {
		generatedAt = items[0].CreatedAt.Format(time.RFC3339)
	}
	refreshStage := ""
	refreshStartedAt := ""
	refreshElapsedSeconds := 0
	if refreshing {
		if job, ok := h.pulseGenerationSnapshot(date, userID); ok {
			refreshStage = job.Stage
			refreshStartedAt = job.StartedAt.Format(time.RFC3339)
			refreshElapsedSeconds = maxInt(0, int(time.Since(job.StartedAt).Seconds()))
		}
	}

	c.JSON(http.StatusOK, gin.H{
		"date":                    date,
		"user_id":                 userID,
		"generated_at":            generatedAt,
		"topics":                  topicResponses(topics),
		"suggested_topics":        buildPulseSuggestedTopics(topics, memorySignals),
		"candidate_count":         len(allItems),
		"recommended_count":       len(items),
		"filtered_count":          maxInt(0, len(allItems)-len(items)),
		"items":                   itemResponsesWithFeatures(items, items, featureState),
		"suggestion_date":         suggestionDate,
		"suggestion_items":        suggestionItems,
		"modules":                 moduleResponsesWithFeatures(modules, items, items, featureState),
		"refreshing":              refreshing,
		"refresh_stage":           refreshStage,
		"refresh_started_at":      refreshStartedAt,
		"refresh_elapsed_seconds": refreshElapsedSeconds,
	})
}

func (h *PulseHandler) loadPulseWelcomeSuggestionItems(
	date string,
	userID string,
	currentItems []models.PulseItem,
	currentAllItems []models.PulseItem,
	currentFeatureState pulseFeatureState,
) ([]pulseItemResponse, string, error) {
	currentCandidates, currentCount := pulseWelcomeSuggestionCandidates(currentItems)
	if currentCount >= pulseSuggestedQuestionLimit {
		return itemResponsesWithFeatures(currentCandidates, currentAllItems, currentFeatureState), date, nil
	}

	targetDate, err := time.ParseInLocation("2006-01-02", date, time.Local)
	if err != nil {
		return itemResponsesWithFeatures(currentCandidates, currentAllItems, currentFeatureState), date, nil
	}
	cutoffDate := targetDate.Add(-pulseWelcomeSuggestionMaxAge).Format("2006-01-02")
	var dates []string
	if err := database.DB.Model(&models.PulseItem{}).
		Distinct("date").
		Where("user_id = ? AND date < ? AND date >= ?", normalizedUserID(userID), date, cutoffDate).
		Order("date desc").
		Limit(7).
		Pluck("date", &dates).Error; err != nil {
		return itemResponsesWithFeatures(currentCandidates, currentAllItems, currentFeatureState), date, err
	}

	for _, fallbackDate := range dates {
		var fallbackItems []models.PulseItem
		if err := database.DB.
			Where("user_id = ? AND date = ?", normalizedUserID(userID), fallbackDate).
			Order("heat_score desc, created_at asc").
			Find(&fallbackItems).Error; err != nil {
			return itemResponsesWithFeatures(currentCandidates, currentAllItems, currentFeatureState), date, err
		}
		fallbackItems, cacheUpgrades := revalidatePulseCachedItems(fallbackItems)
		if err := persistPulseCachedItemUpgrades(cacheUpgrades); err != nil {
			slog.Warn("Pulse welcome cache upgrade failed", "user_id", userID, "date", fallbackDate, "error", err)
		}
		fallbackFeatureState, err := loadPulseFeatureState(userID, fallbackDate, fallbackItems)
		if err != nil {
			return itemResponsesWithFeatures(currentCandidates, currentAllItems, currentFeatureState), date, err
		}
		fallbackRecommended := recommendedPulseItems(fallbackItems, fallbackFeatureState)
		fallbackCandidates, fallbackCount := pulseWelcomeSuggestionCandidates(fallbackRecommended)
		if fallbackCount >= pulseSuggestedQuestionLimit {
			return itemResponsesWithFeatures(fallbackCandidates, fallbackItems, fallbackFeatureState), fallbackDate, nil
		}
	}

	return itemResponsesWithFeatures(currentCandidates, currentAllItems, currentFeatureState), date, nil
}

func pulseWelcomeSuggestionCandidates(items []models.PulseItem) ([]models.PulseItem, int) {
	candidates := make([]models.PulseItem, 0, len(items))
	count := 0
	seen := map[string]bool{}
	for _, item := range items {
		var detail pulseItemDetail
		_ = json.Unmarshal([]byte(item.DetailJSON), &detail)
		itemCount := 0
		prompts := append([]string{}, detail.SuggestedQuestions...)
		prompts = append(prompts, item.ExplorePrompt)
		for _, prompt := range prompts {
			cleaned := cleanSearchText(prompt)
			key := strings.ToLower(cleaned)
			if seen[key] || !pulseWelcomeSuggestionLooksUseful(cleaned) {
				continue
			}
			seen[key] = true
			itemCount++
			count++
		}
		if itemCount > 0 {
			candidates = append(candidates, item)
		}
	}
	return candidates, count
}

func pulseWelcomeSuggestionLooksUseful(value string) bool {
	value = strings.TrimSpace(value)
	runeCount := len([]rune(value))
	if runeCount < 6 || runeCount > 64 || strings.ContainsRune(value, '\uFFFD') {
		return false
	}
	if strings.Contains(value, "…") || strings.Contains(value, "...") {
		return false
	}
	return !pulseQuestionLooksGeneric(value)
}

func (h *PulseHandler) startPulseGeneration(date string, userID string, force bool, reason string) bool {
	userID = normalizedUserID(userID)
	key := pulseGenerationJobKey(date, userID)

	h.jobsMu.Lock()
	if h.jobs == nil {
		h.jobs = map[string]pulseGenerationJob{}
	}
	if _, exists := h.jobs[key]; exists {
		h.jobsMu.Unlock()
		return false
	}
	if pulseGenerationReasonIsAutomatic(reason) {
		reserved, err := h.reservePulseAutomaticAttempt(date, userID, time.Now())
		if err != nil {
			h.jobsMu.Unlock()
			slog.Warn("Pulse automatic generation throttle failed closed", "reason", reason, "date", date, "user_id", userID, "error", err)
			return false
		}
		if !reserved {
			h.jobsMu.Unlock()
			return false
		}
	}
	h.jobs[key] = pulseGenerationJob{
		StartedAt: time.Now(),
		Stage:     pulseGenerationStagePreparing,
	}
	h.jobsMu.Unlock()

	go func() {
		defer h.finishPulseGeneration(key)
		generationErr := h.ensureDailyPulse(date, userID, force)
		if generationErr == nil {
			healthy, err := h.hasCurrentPulseShape(date, userID)
			if err != nil {
				generationErr = err
			} else if !healthy {
				generationErr = fmt.Errorf("pulse generation completed without publishable items")
			}
		}
		if pulseGenerationReasonIsAutomatic(reason) {
			if err := h.finishPulseAutomaticAttempt(date, userID, generationErr, time.Now()); err != nil {
				slog.Warn("Pulse automatic generation result persistence failed", "reason", reason, "date", date, "user_id", userID, "error", err)
			}
		}
		if generationErr != nil {
			slog.Warn("Pulse background generation failed", "reason", reason, "date", date, "user_id", userID, "error", generationErr)
			return
		}
		slog.Info("Pulse background generation completed", "reason", reason, "date", date, "user_id", userID)
	}()
	return true
}

func (h *PulseHandler) pulseGenerationActive(date string, userID string) bool {
	_, ok := h.pulseGenerationSnapshot(date, userID)
	return ok
}

func (h *PulseHandler) pulseGenerationAnyActive() bool {
	h.jobsMu.Lock()
	defer h.jobsMu.Unlock()
	return len(h.jobs) > 0
}

func (h *PulseHandler) pulseGenerationSnapshot(date string, userID string) (pulseGenerationJob, bool) {
	key := pulseGenerationJobKey(date, normalizedUserID(userID))
	h.jobsMu.Lock()
	defer h.jobsMu.Unlock()
	job, exists := h.jobs[key]
	return job, exists
}

func (h *PulseHandler) updatePulseGenerationStage(date string, userID string, stage string) {
	key := pulseGenerationJobKey(date, normalizedUserID(userID))
	h.jobsMu.Lock()
	defer h.jobsMu.Unlock()
	job, exists := h.jobs[key]
	if !exists {
		return
	}
	job.Stage = stage
	h.jobs[key] = job
}

func (h *PulseHandler) finishPulseGeneration(key string) {
	h.jobsMu.Lock()
	defer h.jobsMu.Unlock()
	delete(h.jobs, key)
}

func pulseGenerationJobKey(date string, userID string) string {
	return normalizedUserID(userID) + ":" + date
}

func pulseGenerationReasonIsAutomatic(reason string) bool {
	reason = strings.TrimSpace(reason)
	return reason == "get_quality_refresh" || strings.HasPrefix(reason, "scheduled:")
}

func pulseAutomaticRetryDelay(state models.PulseScheduleState) time.Duration {
	if state.ConsecutiveFailures <= 0 {
		return pulseScheduledRefreshInterval
	}
	// Keep the accumulated failure backoff while an automatic retry is marked
	// running. If the process dies mid-run, a restart must not reset a 24-hour
	// failure cooldown to the normal six-hour refresh interval.
	if state.LastStatus != "failed" && state.LastStatus != "running" {
		return pulseScheduledRefreshInterval
	}
	delay := pulseAutomaticFailureRetryBase
	for failures := 1; failures < state.ConsecutiveFailures; failures++ {
		delay *= 2
		if delay >= pulseAutomaticFailureRetryLimit {
			return pulseAutomaticFailureRetryLimit
		}
	}
	if delay > pulseAutomaticFailureRetryLimit {
		return pulseAutomaticFailureRetryLimit
	}
	return delay
}

func (h *PulseHandler) reservePulseAutomaticAttempt(date string, userID string, now time.Time) (bool, error) {
	h.automaticScheduleMu.Lock()
	defer h.automaticScheduleMu.Unlock()

	userID = normalizedUserID(userID)
	var state models.PulseScheduleState
	err := database.DB.First(&state, "user_id = ?", userID).Error
	if err != nil && err != gorm.ErrRecordNotFound {
		return false, err
	}
	if err == nil && !state.LastAttemptAt.IsZero() && now.Sub(state.LastAttemptAt) < pulseAutomaticRetryDelay(state) {
		return false, nil
	}
	state.UserID = userID
	state.LastDate = date
	state.LastAttemptAt = now
	state.LastStatus = "running"
	state.LastError = ""
	state.UpdatedAt = now
	if err := database.DB.Save(&state).Error; err != nil {
		return false, err
	}
	return true, nil
}

func (h *PulseHandler) finishPulseAutomaticAttempt(date string, userID string, generationErr error, now time.Time) error {
	h.automaticScheduleMu.Lock()
	defer h.automaticScheduleMu.Unlock()

	userID = normalizedUserID(userID)
	var state models.PulseScheduleState
	err := database.DB.First(&state, "user_id = ?", userID).Error
	if err != nil && err != gorm.ErrRecordNotFound {
		return err
	}
	state.UserID = userID
	state.LastDate = date
	if state.LastAttemptAt.IsZero() {
		state.LastAttemptAt = now
	}
	state.UpdatedAt = now
	if generationErr == nil {
		state.LastStatus = "succeeded"
		state.LastSuccessAt = &now
		state.ConsecutiveFailures = 0
		state.LastError = ""
	} else {
		state.LastStatus = "failed"
		state.ConsecutiveFailures++
		state.LastError = limitText(generationErr.Error(), 500)
	}
	return database.DB.Save(&state).Error
}

func (h *PulseHandler) ensureDailyPulse(date string, userID string, force bool) error {
	userID = normalizedUserID(userID)
	unlock := h.lockPulseGeneration(date, userID)
	defer unlock()
	ctx, cancel := context.WithTimeout(context.Background(), pulseGenerationBudget)
	defer cancel()

	h.updatePulseGenerationStage(date, userID, pulseGenerationStagePreparing)
	if err := h.syncConfigToAgent(); err != nil {
		return fmt.Errorf("sync pulse config to agent: %w", err)
	}

	replaceExisting := force
	if !force {
		ok, err := h.hasCurrentPulseShape(date, userID)
		if err != nil {
			return err
		}
		if ok {
			return nil
		}
		replaceExisting = true
	}

	topics, err := h.loadTopics(userID)
	if err != nil {
		return err
	}
	memorySignals, err := h.loadMemorySignals(userID)
	if err != nil {
		return err
	}

	h.updatePulseGenerationStage(date, userID, pulseGenerationStageSearching)
	searchCtx, searchCancel := context.WithTimeout(ctx, pulseSearchBudget)
	searchEvidence, searchErrors := h.collectPulseSearchEvidence(searchCtx, date, topics, memorySignals)
	searchCancel()
	h.updatePulseGenerationStage(date, userID, pulseGenerationStageSummarizing)
	modules, items, generationDiagnostics, err := h.generatePulse(ctx, date, userID, topics, memorySignals, searchEvidence, searchErrors)
	agentGenerationErr := err
	usedFallback := err != nil
	if err != nil {
		slog.Warn("Pulse agent generation failed; using signal fallback", "date", date, "error", err)
		if hasSearchResults(searchEvidence) {
			modules, items = buildSearchFallbackPulse(date, topics, memorySignals, searchEvidence, searchErrors)
		} else {
			modules, items = buildFallbackPulse(date, topics, memorySignals, searchErrors)
		}
	}
	scopePulseModels(userID, modules, items)
	originalItemCount := len(items)
	var publishingRejections []pulseCandidateRejectionDiagnostic
	items, publishingRejections = filterPulseItemsForPublishingWithDiagnostics(items)
	generationDiagnostics.CandidateRejections = append(
		generationDiagnostics.CandidateRejections,
		publishingRejections...,
	)
	if len(items) != originalItemCount {
		slog.Warn(
			"Pulse quality gate removed unverified items",
			"date", date,
			"user_id", userID,
			"removed", originalItemCount-len(items),
			"remaining", len(items),
			"reasons", pulseRejectionReasonCounts(publishingRejections),
		)
	}
	if err := persistPulseRetrievalRun(
		date,
		userID,
		searchEvidence,
		searchErrors,
		originalItemCount,
		len(items),
		usedFallback,
		generationDiagnostics,
		agentGenerationErr,
	); err != nil {
		slog.Warn("Pulse retrieval diagnostics persistence failed", "date", date, "user_id", userID, "error", err)
	}
	var existingItems []models.PulseItem
	if replaceExisting {
		if err := database.DB.
			Where("date = ? AND user_id = ?", date, userID).
			Find(&existingItems).Error; err != nil {
			return err
		}
	}
	existingCurrentItems, _ := revalidatePulseCachedItems(existingItems)
	existingVerifiedCount := len(existingCurrentItems)
	minimumReplacementCount := pulseMinimumReplacementCount(existingVerifiedCount)
	if len(existingItems) > 0 &&
		(len(items) == 0 || (existingVerifiedCount > 0 && len(items) < minimumReplacementCount)) {
		slog.Warn(
			"Pulse refresh did not meet replacement quality; keeping existing pulse",
			"date", date,
			"user_id", userID,
			"new_verified_items", len(items),
			"existing_verified_items", existingVerifiedCount,
			"minimum_replacement_items", minimumReplacementCount,
		)
		return fmt.Errorf(
			"pulse refresh produced %d verified items; at least %d required to replace the existing pulse",
			len(items),
			minimumReplacementCount,
		)
	}
	if len(modules) == 0 && len(items) == 0 {
		slog.Warn("Pulse generation returned no content; keeping existing pulse", "date", date, "user_id", userID)
		return nil
	}

	h.updatePulseGenerationStage(date, userID, pulseGenerationStageSaving)
	return database.DB.Transaction(func(tx *gorm.DB) error {
		if replaceExisting {
			if err := tx.Delete(&models.PulseItem{}, "date = ? AND user_id = ?", date, userID).Error; err != nil {
				return err
			}
			if err := tx.Delete(&models.PulseModule{}, "date = ? AND user_id = ?", date, userID).Error; err != nil {
				return err
			}
		}
		if len(modules) > 0 {
			if err := tx.Create(&modules).Error; err != nil {
				return err
			}
		}
		if len(items) > 0 {
			if err := tx.Create(&items).Error; err != nil {
				return err
			}
		}
		return nil
	})
}

func (h *PulseHandler) lockPulseGeneration(date string, userID string) func() {
	key := pulseGenerationJobKey(date, normalizedUserID(userID))
	h.generationLocksMu.Lock()
	if h.generationLocks == nil {
		h.generationLocks = map[string]*pulseGenerationLock{}
	}
	lock := h.generationLocks[key]
	if lock == nil {
		lock = &pulseGenerationLock{}
		h.generationLocks[key] = lock
	}
	lock.references++
	h.generationLocksMu.Unlock()

	lock.mu.Lock()
	return func() {
		lock.mu.Unlock()
		h.generationLocksMu.Lock()
		lock.references--
		if lock.references == 0 && h.generationLocks[key] == lock {
			delete(h.generationLocks, key)
		}
		h.generationLocksMu.Unlock()
	}
}

func (h *PulseHandler) syncConfigToAgent() error {
	if h.syncer == nil {
		return nil
	}
	return h.syncer.SyncToAgent()
}

func (h *PulseHandler) hasCurrentPulseShape(date string, userID string) (bool, error) {
	userID = normalizedUserID(userID)
	var items []models.PulseItem
	if err := database.DB.Where("date = ? AND user_id = ?", date, userID).Find(&items).Error; err != nil {
		return false, err
	}
	if len(items) == 0 {
		return false, nil
	}
	currentItems, _ := revalidatePulseCachedItems(items)
	if len(currentItems) == 0 {
		return false, nil
	}
	var modules []models.PulseModule
	if err := database.DB.Where("date = ? AND user_id = ?", date, userID).Find(&modules).Error; err != nil {
		return false, err
	}

	moduleKeys := map[string]bool{}
	for _, module := range modules {
		moduleKeys[module.Key] = true
	}
	return moduleKeys[pulseSourceTopicHot] &&
		moduleKeys[pulseSourceMemory] &&
		moduleKeys[pulseSourceInterestHot], nil
}

func (h *PulseHandler) loadTopics(userID string) ([]models.PulseTopic, error) {
	var topics []models.PulseTopic
	err := database.DB.Where("user_id = ?", normalizedUserID(userID)).Order("created_at asc").Find(&topics).Error
	return topics, err
}

func (h *PulseHandler) loadMemorySignals(userID string) ([]memoryPulseSignal, error) {
	var messages []models.Message
	cutoff := time.Now().Add(-pulseMemoryFreshnessWindow)
	if err := database.DB.
		Where("user_id = ? AND created_at >= ?", normalizedUserID(userID), cutoff).
		Order(messageReverseChronologicalOrder).
		Limit(60).
		Find(&messages).Error; err != nil {
		return nil, err
	}
	return inferMemorySignals(messages), nil
}

func pulseTopicOptimizationLookbackDays(value string) int {
	days, err := strconv.Atoi(strings.TrimSpace(value))
	if err != nil {
		return 30
	}
	return maxInt(7, minInt(days, 90))
}

func pulseTopicOptimizationMemorySignals(signals []memoryPulseSignal) []gin.H {
	result := make([]gin.H, 0, len(signals))
	for _, signal := range signals {
		result = append(result, gin.H{
			"theme":    signal.Theme,
			"focus":    signal.Focus,
			"count":    signal.Count,
			"keywords": limitStringSlice(signal.Keywords, 12, 40),
			"snippets": limitStringSlice(signal.Snippets, 2, 180),
		})
	}
	return result
}

func pulseTopicOptimizationRecentIntents(messages []models.Message) []gin.H {
	intents := []gin.H{}
	seen := map[string]bool{}
	for _, message := range messages {
		content := cleanSearchText(message.Content)
		normalized := strings.ToLower(strings.Join(strings.Fields(content), " "))
		runeCount := len([]rune(content))
		if runeCount < 6 || normalized == "" || seen[normalized] {
			continue
		}
		if pulseTextHasAny(
			normalized,
			"读取我的今日 pulse",
			"结合我的 pulse",
			"刷新 pulse",
			"重新生成 pulse",
			"推荐 3 个最值得关注",
			"推荐三个最值得关注",
		) {
			continue
		}
		seen[normalized] = true
		intents = append(intents, gin.H{
			"created_at": message.CreatedAt.Format(time.RFC3339),
			"text":       limitText(content, 220),
		})
		if len(intents) >= 12 {
			break
		}
	}
	return intents
}

func buildPulseTopicOptimizationHistory(
	topics []models.PulseTopic,
	items []models.PulseItem,
	modules []models.PulseModule,
	events []models.PulseEvent,
	retrievalRuns []models.PulseRetrievalRun,
) gin.H {
	metricsByKey := map[string]*pulseTopicOptimizationMetric{}
	metricKeyByName := map[string]string{}
	itemTopicByID := map[string]string{}
	for _, topic := range topics {
		metricsByKey[topic.ID] = &pulseTopicOptimizationMetric{
			TopicID:         topic.ID,
			TopicName:       topic.Name,
			Engagement:      map[string]int{},
			sourceDomainSet: map[string]bool{},
		}
		if nameKey := normalizedPulseTopicKey(topic.Name); nameKey != "" {
			metricKeyByName[nameKey] = topic.ID
		}
	}

	recentContent := []gin.H{}
	sampledClusterCount := 0
	qualityPassed := 0
	qualityFailed := 0
	totalSources := 0
	for _, item := range items {
		metricKey := strings.TrimSpace(item.TopicID)
		metric := metricsByKey[metricKey]
		if metric == nil {
			metricKey = metricKeyByName[normalizedPulseTopicKey(item.TopicName)]
			metric = metricsByKey[metricKey]
		}
		if metric == nil {
			continue
		}
		sampledClusterCount++

		issues, sources := pulseTopicOptimizationQualityIssues(item)
		passed := len(issues) == 0
		if passed {
			qualityPassed++
		} else {
			qualityFailed++
		}
		totalSources += len(sources)

		metric.StoredClusters++
		if passed {
			metric.QualityPassedAtGeneration++
		} else {
			metric.QualityFailedAtGeneration++
		}
		metric.SourceCount += len(sources)
		if metric.LastClusterAt == "" || item.CreatedAt.Format(time.RFC3339) > metric.LastClusterAt {
			metric.LastClusterAt = item.CreatedAt.Format(time.RFC3339)
		}
		for _, source := range sources {
			if domain := pulseSourceDomainKey(source.URL); domain != "" {
				metric.sourceDomainSet[domain] = true
			}
		}
		itemTopicByID[item.ID] = metricKey

		if len(recentContent) < 24 {
			contentSources := make([]gin.H, 0, minInt(len(sources), 3))
			for _, source := range sources[:minInt(len(sources), 3)] {
				contentSources = append(contentSources, gin.H{
					"title":        source.Title,
					"url":          source.URL,
					"source":       source.Source,
					"published_at": source.PublishedAt,
				})
			}
			recentContent = append(recentContent, gin.H{
				"id":                           item.ID,
				"date":                         item.Date,
				"module":                       item.Source,
				"topic_id":                     metric.TopicID,
				"topic_name":                   metric.TopicName,
				"title":                        item.Title,
				"summary":                      item.Summary,
				"quality_passed_at_generation": passed,
				"quality_issues":               issues,
				"sources":                      contentSources,
			})
		}
	}

	for _, event := range events {
		metricKey := strings.TrimSpace(event.TopicID)
		if metricsByKey[metricKey] == nil {
			metricKey = itemTopicByID[event.ItemID]
		}
		metric := metricsByKey[metricKey]
		if metric == nil || event.Value == 0 {
			continue
		}
		metric.Engagement[event.EventType] += event.Value
	}

	metrics := make([]pulseTopicOptimizationMetric, 0, len(metricsByKey))
	for _, metric := range metricsByKey {
		for domain := range metric.sourceDomainSet {
			metric.UniqueSourceDomains = append(metric.UniqueSourceDomains, domain)
		}
		sort.Strings(metric.UniqueSourceDomains)
		metrics = append(metrics, *metric)
	}
	sort.SliceStable(metrics, func(i, j int) bool {
		if metrics[i].StoredClusters != metrics[j].StoredClusters {
			return metrics[i].StoredClusters > metrics[j].StoredClusters
		}
		return metrics[i].TopicName < metrics[j].TopicName
	})

	moduleHistory := make([]gin.H, 0, minInt(len(modules), 18))
	for _, module := range modules[:minInt(len(modules), 18)] {
		moduleHistory = append(moduleHistory, gin.H{
			"date":       module.Date,
			"module":     module.Key,
			"title":      module.Title,
			"summary":    module.Summary,
			"created_at": module.CreatedAt.Format(time.RFC3339),
		})
	}

	return gin.H{
		"summary": gin.H{
			"sampled_cluster_count":        sampledClusterCount,
			"quality_passed_at_generation": qualityPassed,
			"quality_failed_at_generation": qualityFailed,
			"source_count":                 totalSources,
			"retrieval_run_count":          len(retrievalRuns),
		},
		"current_topic_metrics": metrics,
		"overlap_candidates":    pulseTopicOverlapCandidates(topics),
		"recent_content":        recentContent,
		"module_history":        moduleHistory,
		"retrieval_runs":        pulseTopicOptimizationRetrievalRuns(retrievalRuns),
	}
}

func pulseTopicOptimizationQualityIssues(item models.PulseItem) ([]string, []pulseNewsSource) {
	var detail pulseItemDetail
	if item.DetailJSON == "" || json.Unmarshal([]byte(item.DetailJSON), &detail) != nil {
		return append(pulseNewsCopyQualityIssues(item.Title, item.Summary), "missing_or_invalid_detail"), nil
	}
	issues := append([]string{}, pulseItemCopyQualityIssues(detail.EvidenceMode, item.Title, item.Summary)...)
	if detail.ContentVersion >= pulseContentVersion {
		issues = append(issues, pulseSummaryLengthIssues(item.Summary)...)
	}
	sources := normalizeNewsSources(detail.NewsSources, pulseSearchClusterMaxSources)
	issues = append(issues, pulseItemSourceQualityIssues(item.Date, item.Source, detail.EvidenceMode, sources)...)
	return issues, sources
}

func pulseTopicOverlapCandidates(topics []models.PulseTopic) []pulseTopicOverlapCandidate {
	candidates := []pulseTopicOverlapCandidate{}
	for leftIndex := 0; leftIndex < len(topics); leftIndex++ {
		left := topics[leftIndex]
		leftTerms := pulseTopicOptimizationTermSet(left)
		for rightIndex := leftIndex + 1; rightIndex < len(topics); rightIndex++ {
			right := topics[rightIndex]
			rightTerms := pulseTopicOptimizationTermSet(right)
			shared := []string{}
			for term := range leftTerms {
				if rightTerms[term] {
					shared = append(shared, term)
				}
			}
			sort.Strings(shared)
			denominator := minInt(len(leftTerms), len(rightTerms))
			if len(shared) < 2 || denominator == 0 {
				continue
			}
			score := len(shared) * 100 / denominator
			if score < 25 {
				continue
			}
			candidates = append(candidates, pulseTopicOverlapCandidate{
				LeftTopicID:    left.ID,
				LeftTopicName:  left.Name,
				RightTopicID:   right.ID,
				RightTopicName: right.Name,
				SharedKeywords: shared,
				OverlapScore:   score,
			})
		}
	}
	sort.SliceStable(candidates, func(i, j int) bool {
		return candidates[i].OverlapScore > candidates[j].OverlapScore
	})
	return candidates
}

func pulseTopicOptimizationTermSet(topic models.PulseTopic) map[string]bool {
	terms := map[string]bool{}
	values := append(decodeKeywords(topic.Keywords), pulseKeywordsFromText(topic.Name)...)
	for _, value := range values {
		term := strings.ToLower(strings.TrimSpace(value))
		if term == "" {
			continue
		}
		terms[term] = true
	}
	return terms
}

func pulseTopicOptimizationRetrievalRuns(runs []models.PulseRetrievalRun) []gin.H {
	result := make([]gin.H, 0, minInt(len(runs), 6))
	for _, run := range runs[:minInt(len(runs), 6)] {
		var diagnostics pulseRetrievalDiagnostics
		_ = json.Unmarshal([]byte(run.DiagnosticsJSON), &diagnostics)
		queries := make([]gin.H, 0, len(diagnostics.Queries))
		for _, query := range diagnostics.Queries {
			results := make([]gin.H, 0, minInt(len(query.Results), 2))
			for _, item := range query.Results[:minInt(len(query.Results), 2)] {
				results = append(results, gin.H{
					"title":        item.Title,
					"url":          item.URL,
					"source":       item.Source,
					"published_at": item.PublishedAt,
				})
			}
			queries = append(queries, gin.H{
				"query_id":          query.QueryID,
				"stage":             query.Stage,
				"parent_query_id":   query.ParentQueryID,
				"module":            query.Module,
				"query":             query.Query,
				"intent":            query.Intent,
				"keyword":           query.Keyword,
				"topic_id":          query.TopicID,
				"topic_name":        query.TopicName,
				"result_count":      query.ResultCount,
				"error":             query.Error,
				"rewritten_queries": query.RewrittenQueries,
				"results":           results,
			})
		}
		rejections := make([]gin.H, 0, minInt(len(diagnostics.CandidateRejections), 24))
		for _, rejection := range diagnostics.CandidateRejections[:minInt(len(diagnostics.CandidateRejections), 24)] {
			rejections = append(rejections, gin.H{
				"stage":          rejection.Stage,
				"module":         rejection.Module,
				"topic_id":       rejection.TopicID,
				"topic_name":     rejection.TopicName,
				"title":          rejection.Title,
				"reasons":        rejection.Reasons,
				"source_count":   rejection.SourceCount,
				"source_domains": rejection.SourceDomains,
			})
		}
		var searchErrors []string
		_ = json.Unmarshal([]byte(run.SearchErrorsJSON), &searchErrors)
		result = append(result, gin.H{
			"id":                     run.ID,
			"date":                   run.Date,
			"created_at":             run.CreatedAt.Format(time.RFC3339),
			"query_count":            run.QueryCount,
			"successful_query_count": run.SuccessfulQueryCount,
			"result_count":           run.ResultCount,
			"generated_item_count":   run.GeneratedItemCount,
			"published_item_count":   run.PublishedItemCount,
			"used_fallback":          run.UsedFallback,
			"generation_error":       run.GenerationError,
			"raw_candidate_count":    diagnostics.RawCandidateCount,
			"grounded_item_count":    diagnostics.GroundedItemCount,
			"candidate_rejections":   rejections,
			"search_errors":          limitStringSlice(searchErrors, 6, 220),
			"queries":                queries,
		})
	}
	return result
}

func persistPulseRetrievalRun(
	date string,
	userID string,
	evidence []pulseSearchEvidence,
	searchErrors []string,
	generatedItemCount int,
	publishedItemCount int,
	usedFallback bool,
	generationDiagnostics pulseGenerationDiagnostics,
	generationErr error,
) error {
	diagnostics := pulseRetrievalDiagnostics{
		Queries:             []pulseRetrievalQueryDiagnostic{},
		RawCandidateCount:   generationDiagnostics.RawCandidateCount,
		GroundedItemCount:   generationDiagnostics.GroundedItemCount,
		CandidateRejections: generationDiagnostics.CandidateRejections,
	}
	successfulQueries := 0
	resultCount := 0
	for _, query := range evidence {
		if len(query.Results) > 0 {
			successfulQueries++
		}
		resultCount += len(query.Results)
		queryDiagnostic := pulseRetrievalQueryDiagnostic{
			QueryID:          query.QueryID,
			Stage:            query.Stage,
			ParentQueryID:    query.ParentQueryID,
			Module:           query.Module,
			Query:            limitText(query.Query, 240),
			Intent:           limitText(query.Intent, 180),
			Keyword:          limitText(query.Keyword, 100),
			TopicID:          query.TopicID,
			TopicName:        limitText(query.TopicName, 100),
			ResultCount:      len(query.Results),
			Error:            limitText(query.Error, 300),
			ProviderErrors:   limitStringSlice(query.ProviderErrors, 3, 220),
			RewrittenQueries: limitStringSlice(query.RewrittenQueries, 6, 240),
		}
		for _, result := range query.Results[:minInt(len(query.Results), 4)] {
			queryDiagnostic.Results = append(queryDiagnostic.Results, pulseRetrievalResultDiagnostic{
				Title:       limitText(result.Title, 180),
				URL:         limitText(result.URL, 600),
				Source:      limitText(result.Source, 80),
				PublishedAt: limitText(result.PublishedAt, 80),
				Snippet:     limitText(result.Snippet, 240),
			})
		}
		diagnostics.Queries = append(diagnostics.Queries, queryDiagnostic)
	}
	diagnosticsJSON, err := json.Marshal(diagnostics)
	if err != nil {
		return err
	}
	searchErrorsJSON, err := json.Marshal(limitStringSlice(searchErrors, 12, 300))
	if err != nil {
		return err
	}
	generationError := ""
	if generationErr != nil {
		generationError = limitText(generationErr.Error(), 600)
	}
	now := time.Now()
	run := models.PulseRetrievalRun{
		ID:                   uuid.NewString(),
		UserID:               normalizedUserID(userID),
		Date:                 date,
		QueryCount:           len(evidence),
		SuccessfulQueryCount: successfulQueries,
		ResultCount:          resultCount,
		GeneratedItemCount:   generatedItemCount,
		PublishedItemCount:   publishedItemCount,
		UsedFallback:         usedFallback,
		SearchErrorsJSON:     string(searchErrorsJSON),
		DiagnosticsJSON:      string(diagnosticsJSON),
		GenerationError:      generationError,
		CreatedAt:            now,
	}
	return database.DB.Transaction(func(tx *gorm.DB) error {
		if err := tx.Create(&run).Error; err != nil {
			return err
		}
		return tx.
			Where("user_id = ? AND created_at < ?", run.UserID, now.Add(-pulseRetrievalHistoryRetention)).
			Delete(&models.PulseRetrievalRun{}).Error
	})
}

func (h *PulseHandler) collectPulseSearchEvidence(ctx context.Context, date string, topics []models.PulseTopic, signals []memoryPulseSignal) ([]pulseSearchEvidence, []string) {
	queries := buildPulseSearchQueries(date, topics, signals)
	if len(queries) == 0 {
		return nil, []string{"没有可用于外网检索的 topic、关键词或 memory 信号。"}
	}
	if h.agent == nil {
		return nil, []string{"Agent search client is not configured."}
	}

	evidence := make([]pulseSearchEvidence, len(queries))
	searchErrors := []string{}
	var wg sync.WaitGroup
	lightweight, concurrency := pulseInitialSearchMode(len(queries))
	sem := make(chan struct{}, concurrency)
	var errMu sync.Mutex
	for index, query := range queries {
		wg.Add(1)
		go func(index int, query pulseSearchQuery) {
			defer wg.Done()
			item := pulseSearchEvidence{
				QueryID:   query.ID,
				Stage:     "initial",
				Module:    query.Module,
				Query:     query.Query,
				Intent:    query.Intent,
				Keyword:   query.Keyword,
				TopicID:   query.TopicID,
				TopicName: query.TopicName,
			}
			select {
			case sem <- struct{}{}:
			case <-ctx.Done():
				item.Error = ctx.Err().Error()
				evidence[index] = item
				return
			}
			defer func() { <-sem }()

			resp, err := h.agent.SearchContext(ctx, bridge.SearchRequest{
				Query:         query.Query,
				Limit:         pulseSearchRawResultLimit,
				Lightweight:   lightweight,
				OpenResults:   false,
				IncludeImages: false,
			})
			if err != nil {
				item.Error = err.Error()
				errMu.Lock()
				searchErrors = append(searchErrors, fmt.Sprintf("%s: %v", query.Query, err))
				errMu.Unlock()
				evidence[index] = item
				return
			}

			item.ProviderErrors = limitStringSlice(resp.ProviderErrors, 3, 220)
			item.RewrittenQueries = pulseSearchRewrittenQueries(resp.TraceNodes)
			item.Results = normalizePulseSearchResults(date, query, resp.Results, pulseSearchResultLimit)
			if len(item.Results) == 0 {
				item.Error = "搜索完成但没有足够相关的可用结果。"
				if len(item.ProviderErrors) > 0 {
					item.Error = "搜索完成但没有足够相关的可用结果；部分来源失败：" + strings.Join(item.ProviderErrors, "；")
				}
			}
			evidence[index] = item
		}(index, query)
	}
	wg.Wait()
	if ctx.Err() != nil {
		searchErrors = append(searchErrors, fmt.Sprintf("Pulse %s 检索阶段预算已用尽：%v", pulseSearchBudget, ctx.Err()))
	}

	nonEmpty := make([]pulseSearchEvidence, 0, len(evidence))
	for _, item := range evidence {
		if item.Query == "" {
			continue
		}
		nonEmpty = append(nonEmpty, item)
	}
	if ctx.Err() == nil {
		nonEmpty = h.enrichPulseSearchEvidence(ctx, date, nonEmpty, &searchErrors)
	}
	return nonEmpty, searchErrors
}

func pulseInitialSearchMode(queryCount int) (lightweight bool, concurrency int) {
	if queryCount > pulseSearchFullModeQueryLimit {
		return true, pulseSearchLightConcurrency
	}
	return false, pulseSearchConcurrency
}

func pulseSearchRewrittenQueries(traceNodes []map[string]interface{}) []string {
	queries := []string{}
	for _, node := range traceNodes {
		if fmt.Sprint(node["node"]) != "query_rewrite" {
			continue
		}
		switch values := node["queries"].(type) {
		case []interface{}:
			for _, value := range values {
				queries = appendUniqueStrings(queries, strings.TrimSpace(fmt.Sprint(value)))
			}
		case []string:
			queries = appendUniqueStrings(queries, values...)
		}
	}
	return limitStringSlice(queries, 6, 240)
}

func normalizePulseSearchResults(date string, query pulseSearchQuery, results []bridge.SearchResult, maxResults int) []pulseSearchResult {
	candidates := []scoredPulseSearchResult{}
	for resultIndex, result := range results {
		title := limitText(cleanSearchText(result.Title), 180)
		snippet := cleanSearchText(result.Snippet)
		pageContent := cleanSearchText(pulseSearchPageMetadataString(result.Metadata, "content"))
		if pageContent != "" {
			snippet = strings.TrimSpace(strings.Join([]string{
				limitText(snippet, 260),
				"正文摘录：" + limitText(pageContent, 640),
			}, " "))
		}
		resultURL := strings.TrimSpace(result.URL)
		if finalURL := strings.TrimSpace(pulseSearchPageMetadataString(result.Metadata, "final_url")); pulseSafeHTTPURL(finalURL) {
			resultURL = finalURL
		}
		if title == "" || resultURL == "" {
			continue
		}
		if !pulseSearchResultLooksUseful(title, snippet, resultURL) {
			continue
		}
		publishedAt := metadataString(result.Metadata, "published_at", "publishedAt", "pub_date", "date")
		if publishedAt == "" {
			publishedAt = pulseSearchPageMetadataString(result.Metadata, "published_at")
		}
		searchResult := pulseSearchResult{
			Title:       title,
			Snippet:     limitText(snippet, 900),
			URL:         resultURL,
			Source:      limitText(cleanSearchText(result.Source), 80),
			PublishedAt: limitText(publishedAt, 80),
		}
		if strings.TrimSpace(searchResult.PublishedAt) == "" {
			if inferred, ok := pulseSearchResultPublishedAt(searchResult); ok {
				searchResult.PublishedAt = inferred.Format("2006-01-02")
			}
		}
		if pulseSearchResultHasStaleDate(date, query.Module, searchResult) {
			continue
		}
		score := pulseSearchResultRelevanceScore(query, searchResult)
		if score <= 0 {
			continue
		}
		candidates = append(candidates, scoredPulseSearchResult{
			Result: searchResult,
			Score:  score,
			Index:  resultIndex,
		})
	}
	return pulseSearchResultsFromScored(candidates, maxResults)
}

func (h *PulseHandler) enrichPulseSearchEvidence(ctx context.Context, date string, evidence []pulseSearchEvidence, searchErrors *[]string) []pulseSearchEvidence {
	if h.agent == nil || len(evidence) == 0 || ctx.Err() != nil {
		return evidence
	}
	plans := pulseSearchFollowupPlans(date, evidence)
	if len(plans) == 0 {
		return evidence
	}

	followups := make([]pulseSearchEvidence, len(plans))
	followupErrors := []string{}
	var wg sync.WaitGroup
	var mu sync.Mutex
	sem := make(chan struct{}, pulseSearchFollowupConcurrency)
	for planPosition, plan := range plans {
		seed := plan.Seed
		if seed.EvidenceIndex < 0 || seed.EvidenceIndex >= len(evidence) {
			continue
		}
		followupQuery := plan.Query
		followupQuery.ID = fmt.Sprintf("%s:followup:%s:%d", evidence[seed.EvidenceIndex].QueryID, plan.Kind, planPosition+1)
		wg.Add(1)
		go func(planPosition int, plan pulseSearchFollowupPlan, followupQuery pulseSearchQuery) {
			defer wg.Done()
			select {
			case sem <- struct{}{}:
			case <-ctx.Done():
				followups[planPosition] = pulseSearchEvidence{
					QueryID: followupQuery.ID, Stage: "followup", ParentQueryID: evidence[plan.Seed.EvidenceIndex].QueryID,
					Module: followupQuery.Module, Query: followupQuery.Query, Intent: followupQuery.Intent,
					Keyword: followupQuery.Keyword, TopicID: followupQuery.TopicID, TopicName: followupQuery.TopicName,
					Error: ctx.Err().Error(),
				}
				return
			}
			defer func() { <-sem }()
			seed := plan.Seed
			item := pulseSearchEvidence{
				QueryID:       followupQuery.ID,
				Stage:         "followup",
				ParentQueryID: evidence[seed.EvidenceIndex].QueryID,
				Module:        followupQuery.Module,
				Query:         followupQuery.Query,
				Intent:        followupQuery.Intent,
				Keyword:       followupQuery.Keyword,
				TopicID:       followupQuery.TopicID,
				TopicName:     followupQuery.TopicName,
			}

			resp, err := h.agent.SearchContext(ctx, bridge.SearchRequest{
				Query:         followupQuery.Query,
				Limit:         pulseSearchFollowupResultLimit,
				OpenResults:   true,
				IncludeImages: false,
				OpenLimit:     2,
				PageChars:     1400,
			})
			if err != nil {
				item.Error = err.Error()
				followups[planPosition] = item
				mu.Lock()
				followupErrors = append(followupErrors, fmt.Sprintf("二次检索 %s: %v", followupQuery.Query, err))
				mu.Unlock()
				return
			}

			item.ProviderErrors = limitStringSlice(resp.ProviderErrors, 3, 220)
			item.RewrittenQueries = pulseSearchRewrittenQueries(resp.TraceNodes)
			normalized := normalizePulseSearchResults(date, followupQuery, resp.Results, pulseSearchFollowupResultLimit)
			supporting := pulseSupportingFollowupResults(evidence[seed.EvidenceIndex], seed.Result, normalized)
			if len(supporting) == 0 {
				item.Error = fmt.Sprintf("%s补充检索未找到与首轮候选相互印证的来源。", pulseFollowupKindLabel(plan.Kind))
				followups[planPosition] = item
				return
			}
			item.Results = append([]pulseSearchResult{seed.Result}, supporting...)
			item.Results = pulseRankSearchResults(followupQuery, item.Results, pulseSearchExpandedResultLimit)
			followups[planPosition] = item
		}(planPosition, plan, followupQuery)
	}
	wg.Wait()

	if len(followupErrors) > 0 && searchErrors != nil {
		*searchErrors = append(*searchErrors, limitStringSlice(followupErrors, 4, 220)...)
	}
	for _, item := range followups {
		if item.QueryID != "" {
			evidence = append(evidence, item)
		}
	}
	return evidence
}

func pulseSearchQueryFromEvidence(item pulseSearchEvidence) pulseSearchQuery {
	return pulseSearchQuery{
		ID:        item.QueryID,
		Module:    item.Module,
		Query:     item.Query,
		Intent:    item.Intent,
		Keyword:   item.Keyword,
		TopicID:   item.TopicID,
		TopicName: item.TopicName,
	}
}

func pulseSearchResultsFromScored(candidates []scoredPulseSearchResult, maxResults int) []pulseSearchResult {
	sort.SliceStable(candidates, func(i, j int) bool {
		if candidates[i].Score == candidates[j].Score {
			return candidates[i].Index < candidates[j].Index
		}
		return candidates[i].Score > candidates[j].Score
	})
	results := make([]pulseSearchResult, 0, minInt(len(candidates), maxResults))
	for _, candidate := range candidates[:minInt(len(candidates), maxResults)] {
		results = append(results, candidate.Result)
	}
	return results
}

func pulseRankSearchResults(query pulseSearchQuery, results []pulseSearchResult, maxResults int) []pulseSearchResult {
	candidates := make([]scoredPulseSearchResult, 0, len(results))
	seen := map[string]bool{}
	for index, result := range results {
		key := pulseSearchResultDedupeKey(result)
		if key != "" {
			if seen[key] {
				continue
			}
			seen[key] = true
		}
		score := pulseSearchResultRelevanceScore(query, result)
		if pulsePrimarySearchSource(result) {
			score += 12
		} else if pulseAuthoritativeSearchSource(result) {
			score += 7
		} else if !pulseWeakSearchSource(result) {
			score += 3
		}
		if strings.TrimSpace(result.PublishedAt) != "" {
			score += 2
		}
		candidates = append(candidates, scoredPulseSearchResult{
			Result: result,
			Score:  score,
			Index:  index,
		})
	}
	return pulseSearchResultsFromScored(candidates, maxResults)
}

func pulseSearchFollowupSeeds(date string, evidence []pulseSearchEvidence) []pulseSearchFollowupSeed {
	seeds := []pulseSearchFollowupSeed{}
	seen := map[string]bool{}
	verified := map[string]bool{}
	for _, cluster := range pulseVerifiedSearchClusters(date, evidence) {
		// A trusted first-stage singleton is publishable, but still benefits from
		// the optional enrichment search. Only skip seeds that already have real
		// multi-source support.
		if len(cluster.Results) < 2 || cluster.Intent == "keyword_digest" {
			continue
		}
		for _, result := range cluster.Results {
			if key := pulseSearchResultDedupeKey(result); key != "" {
				verified[key] = true
			}
		}
	}
	seedIndex := 0
	for evidenceIndex, item := range evidence {
		query := pulseSearchQueryFromEvidence(item)
		for _, result := range item.Results {
			// Digests and broad editorial overviews are useful for discovery, but
			// make poor verification anchors: their titles mix several unrelated
			// events and produce follow-up queries that cannot corroborate any one
			// claim. Prefer a concrete event page from the same discovery result.
			if pulseSearchResultLooksEditorialOverview(result) {
				continue
			}
			resultKey := pulseSearchResultDedupeKey(result)
			if !pulseSearchResultCanSeedFollowup(date, item, result) ||
				pulseSearchResultHasVerifiedSupport(date, item, result) ||
				verified[resultKey] {
				continue
			}
			key := resultKey
			if key != "" {
				if seen[key] {
					continue
				}
				seen[key] = true
			}
			score := pulseSearchResultRelevanceScore(query, result)
			if score <= 0 {
				continue
			}
			if !pulseWeakSearchSource(result) {
				score += 8
			}
			if pulsePrimarySearchSource(result) {
				score += 12
			} else if pulseAuthoritativeSearchSource(result) {
				score += 6
			}
			if strings.TrimSpace(result.PublishedAt) != "" {
				score += 3
			}
			seeds = append(seeds, pulseSearchFollowupSeed{
				EvidenceIndex: evidenceIndex,
				Result:        result,
				Score:         score,
				Index:         seedIndex,
			})
			seedIndex++
		}
	}
	sort.SliceStable(seeds, func(i, j int) bool {
		if seeds[i].Score == seeds[j].Score {
			return seeds[i].Index < seeds[j].Index
		}
		return seeds[i].Score > seeds[j].Score
	})
	selected := make([]pulseSearchFollowupSeed, 0, len(seeds))
	groups := map[string]bool{}
	for _, seed := range seeds {
		item := evidence[seed.EvidenceIndex]
		keyword := strings.ToLower(strings.TrimSpace(item.Keyword))
		if keyword == "" {
			keyword = firstNonEmptyPulse(item.TopicID, strings.ToLower(strings.TrimSpace(item.TopicName)), "general")
		}
		group := normalizePulseModuleKey(item.Module) + ":" + firstNonEmptyPulse(item.TopicID, "general") + ":" + keyword
		if groups[group] {
			continue
		}
		groups[group] = true
		selected = append(selected, seed)
	}
	return selected
}

func pulseSearchEvidenceNeedsFollowup(date string, evidence pulseSearchEvidence) bool {
	for _, result := range evidence.Results {
		if pulseSearchResultCanSeedFollowup(date, evidence, result) &&
			!pulseSearchResultHasVerifiedSupport(date, evidence, result) {
			return true
		}
	}
	return false
}

func pulseSearchResultCanSeedFollowup(date string, evidence pulseSearchEvidence, result pulseSearchResult) bool {
	if !pulseSafeHTTPURL(result.URL) ||
		pulseSearchResultHasStaleDate(date, evidence.Module, result) ||
		pulseSearchResultLooksThinHomepage(result) ||
		len(pulseConcreteEventFamilies(result)) == 0 {
		return false
	}
	return len(pulseCorroborationTerms(result)) >= 2
}

func pulseSearchResultHasVerifiedSupport(date string, evidence pulseSearchEvidence, seed pulseSearchResult) bool {
	seedKey := pulseSearchResultDedupeKey(seed)
	for _, cluster := range pulseCorroboratedSearchClusters(evidence, evidence.Results) {
		containsSeed := false
		for _, result := range cluster {
			if pulseSearchResultDedupeKey(result) == seedKey {
				containsSeed = true
				break
			}
		}
		if containsSeed && pulseNewsSourcesMeetQualityGate(
			date,
			evidence.Module,
			newsSourcesFromSearchResults(cluster, pulseSearchClusterMaxSources),
		) {
			return true
		}
	}
	return false
}

func pulseSearchFollowupPlans(date string, evidence []pulseSearchEvidence) []pulseSearchFollowupPlan {
	plans := []pulseSearchFollowupPlan{}
	for _, seed := range pulseSearchFollowupSeeds(date, evidence) {
		if seed.EvidenceIndex < 0 || seed.EvidenceIndex >= len(evidence) {
			continue
		}
		for _, query := range pulseSearchFollowupQueries(date, evidence[seed.EvidenceIndex], seed.Result) {
			plans = append(plans, pulseSearchFollowupPlan{Seed: seed, Kind: query.Intent, Query: query})
		}
	}
	return plans
}

func pulseSearchFollowupQueries(_ string, queryEvidence pulseSearchEvidence, seed pulseSearchResult) []pulseSearchQuery {
	anchor := pulseSearchEventAnchorTerms(seed)
	anchorText := pulseSearchEventAnchorText(seed)
	if len(anchor) == 0 || anchorText == "" {
		return nil
	}
	if publishedAt, ok := pulseSearchResultPublishedAt(seed); ok {
		year := publishedAt.Format("2006")
		if !strings.Contains(anchorText, year) {
			anchorText += " " + year
		}
	}
	return []pulseSearchQuery{
		{
			ID:        queryEvidence.QueryID + ":followup:event",
			Module:    queryEvidence.Module,
			Query:     anchorText,
			Intent:    "event_verification",
			Keyword:   queryEvidence.Keyword,
			TopicID:   queryEvidence.TopicID,
			TopicName: queryEvidence.TopicName,
		},
	}
}

func pulseSearchEventAnchorText(seed pulseSearchResult) string {
	title := cleanSearchText(seed.Title)
	for _, separator := range []string{" — ", " | ", " – "} {
		if index := strings.Index(title, separator); index > 0 {
			title = strings.TrimSpace(title[:index])
		}
	}
	return limitText(title, 140)
}

func pulseFollowupKindLabel(kind string) string {
	if kind == "event_verification" {
		return "事件定向"
	}
	return "二次"
}

func pulseSearchEventAnchorTerms(seed pulseSearchResult) []string {
	title := cleanSearchText(seed.Title)
	terms := []string{}
	for _, entity := range pulseKnownEntities {
		if pulseTextContainsFold(title, entity) {
			terms = appendUniqueStrings(terms, entity)
		}
	}
	tokens := pulseSearchAnchorTokenPattern.FindAllString(title, -1)
	for _, requireDistinctive := range []bool{true, false} {
		for _, token := range tokens {
			token = strings.TrimFunc(strings.TrimSpace(token), unicode.IsPunct)
			if !pulseSearchAnchorTermLooksUseful(token) || strings.ContainsAny(token, "，。！？；：") {
				continue
			}
			distinctive := strings.ContainsAny(token, "0123456789-._")
			if distinctive != requireDistinctive {
				continue
			}
			terms = appendUniqueStrings(terms, token)
			if len(terms) >= 4 {
				return terms
			}
		}
	}
	return limitStringSlice(terms, 4, 32)
}

func pulseSearchAnchorTermLooksUseful(term string) bool {
	normalized := strings.ToLower(strings.TrimSpace(term))
	if normalized == "" || pulseSearchTermLooksGeneric(normalized) || pulseCorroborationTermLooksGeneric(normalized) {
		return false
	}
	if len([]rune(normalized)) < 2 || len([]rune(normalized)) > 24 {
		return false
	}
	noise := []string{
		"this", "that", "with", "from", "gets", "unveils", "confirms", "says", "week", "brief",
		"newsroom", "officially", "reportedly", "today", "latest", "update", "updates",
		"宣布", "确认", "上线", "推出", "正式", "今日", "本周", "动态", "消息",
	}
	for _, value := range noise {
		if normalized == value {
			return false
		}
	}
	return true
}

func pulseOfficialDomainForAnchor(anchor []string) string {
	joined := strings.ToLower(strings.Join(anchor, " "))
	known := []struct{ term, domain string }{
		{"openai", "openai.com"}, {"chatgpt", "openai.com"},
		// Claude product announcements moved to claude.com/blog. Check this
		// before the broader Anthropic corporate/news domain so product seeds
		// do not get trapped behind the wrong site: filter.
		{"claude", "claude.com"}, {"anthropic", "anthropic.com"},
		{"deepseek", "deepseek.com"}, {"gemini", "blog.google"}, {"deepmind", "deepmind.google"},
		{"qwen", "qwenlm.ai"}, {"mistral", "mistral.ai"}, {"nvidia", "nvidia.com"},
		{"uipath", "uipath.com"}, {"openrouter", "openrouter.ai"},
	}
	for _, item := range known {
		if strings.Contains(joined, item.term) {
			return item.domain
		}
	}
	return ""
}

func pulseSupportingFollowupResults(queryEvidence pulseSearchEvidence, seed pulseSearchResult, results []pulseSearchResult) []pulseSearchResult {
	supporting := []pulseSearchResult{}
	seedKey := pulseSearchResultDedupeKey(seed)
	for _, result := range results {
		if key := pulseSearchResultDedupeKey(result); key != "" && key == seedKey {
			continue
		}
		if !pulseSearchResultsCorroborate(queryEvidence, seed, result) {
			continue
		}
		supporting = append(supporting, result)
	}
	return supporting
}

func buildPulseSearchQueries(_ string, topics []models.PulseTopic, signals []memoryPulseSignal) []pulseSearchQuery {
	queries := []pulseSearchQuery{}
	seen := map[string]bool{}
	addKeywordQueries := func(module string, topicID string, topicName string, keyword string) {
		terms := cleanPulseSearchTerms([]string{keyword})
		if len(terms) != 1 {
			return
		}
		keyword = terms[0]
		subject := pulseSearchQuerySubject(topicName, keyword)
		variants := []struct {
			Suffix string
			Intent string
		}{
			{Suffix: "最新进展", Intent: "keyword_latest"},
			{Suffix: "近期热点", Intent: "keyword_hot"},
		}
		for _, variant := range variants {
			query := strings.TrimSpace(subject + " " + variant.Suffix)
			key := strings.ToLower(strings.Join([]string{module, topicID, topicName, keyword, variant.Intent}, ":"))
			if seen[key] {
				continue
			}
			seen[key] = true
			queries = append(queries, pulseSearchQuery{
				Module:    module,
				Query:     query,
				Intent:    variant.Intent,
				Keyword:   keyword,
				TopicID:   topicID,
				TopicName: topicName,
			})
		}
	}

	for _, topic := range topics {
		terms := cleanPulseSearchTerms(decodeKeywords(topic.Keywords))
		if len(terms) == 0 {
			terms = []string{topic.Name}
		}
		for _, keyword := range terms {
			addKeywordQueries(pulseSourceTopicHot, topic.ID, topic.Name, keyword)
		}
	}
	for _, signal := range signals {
		terms := cleanPulseSearchTerms(signal.Keywords)
		if len(terms) == 0 {
			terms = pulseKeywordsFromText(firstNonEmptyPulse(signal.Focus, signal.Theme))
		}
		for _, keyword := range cleanPulseSearchTerms(terms) {
			addKeywordQueries(pulseSourceMemory, "", "", keyword)
		}
	}

	for index := range queries {
		queries[index].ID = fmt.Sprintf("q%d", index+1)
	}
	return queries
}

func pulseSearchKeywordSubject(keyword string) string {
	keyword = strings.TrimSpace(keyword)
	if strings.EqualFold(keyword, "agent") {
		return keyword + " 智能体"
	}
	return keyword
}

func pulseSearchQuerySubject(topicName string, keyword string) string {
	topicTerms := cleanPulseSearchTerms([]string{topicName})
	subject := pulseSearchKeywordSubject(keyword)
	if len(topicTerms) != 1 {
		return subject
	}
	topicName = topicTerms[0]
	if subject == "" {
		return topicName
	}
	if pulseSearchTextContainsTerm(topicName, keyword) {
		// Some keyword aliases add useful retrieval language even when the raw
		// keyword is already present in the topic name. Keep only that extra
		// context instead of emitting duplicated text such as "Agent Agent".
		extra := subject
		if len(subject) >= len(keyword) && strings.EqualFold(subject[:len(keyword)], keyword) {
			extra = strings.TrimSpace(subject[len(keyword):])
		}
		if extra != "" && !pulseSearchTextContainsTerm(topicName, extra) {
			return strings.TrimSpace(topicName + " " + extra)
		}
		return topicName
	}
	if pulseSearchTextContainsTerm(subject, topicName) {
		return subject
	}
	return strings.TrimSpace(topicName + " " + subject)
}

func pulseTopicDiscoveryTerms(topic models.PulseTopic) []string {
	keywords := cleanPulseSearchTerms(expandPulseTopicKeywords(topic.Name, decodeKeywords(topic.Keywords)))
	terms := make([]string, 0, 5)
	for _, keyword := range keywords {
		if strings.EqualFold(strings.TrimSpace(keyword), strings.TrimSpace(topic.Name)) {
			continue
		}
		terms = append(terms, keyword)
		if len(terms) >= 5 {
			return terms
		}
	}
	if len(terms) < 3 {
		terms = append([]string{topic.Name}, terms...)
	}
	terms = cleanPulseSearchTerms(terms)
	return terms[:minInt(len(terms), 5)]
}

func pulseSearchPeriodSuffix(date string) string {
	reference, err := time.Parse("2006-01-02", date)
	if err != nil {
		year := strings.TrimSpace(date)
		if len(year) > 4 {
			year = year[:4]
		}
		return strings.TrimSpace(year + " latest news")
	}
	return fmt.Sprintf("%d %s latest news", reference.Year(), reference.Month().String())
}

func pulseFocusedSearchTermGroups(primary string, keywords []string, maxGroups int) [][]string {
	primaryTerms := cleanPulseSearchTerms([]string{primary})
	primary = ""
	if len(primaryTerms) > 0 {
		primary = primaryTerms[0]
	}
	keywords = cleanPulseSearchTerms(keywords)
	groups := [][]string{}
	seen := map[string]bool{}
	appendGroup := func(values ...string) {
		cleaned := cleanPulseSearchTerms(values)
		if len(cleaned) == 0 {
			return
		}
		key := strings.ToLower(strings.Join(cleaned, "\x00"))
		if seen[key] {
			return
		}
		seen[key] = true
		groups = append(groups, cleaned)
	}
	for index, keyword := range keywords {
		if primary != "" && strings.EqualFold(primary, keyword) {
			continue
		}
		if primary != "" {
			appendGroup(primary, keyword)
		} else {
			nextKeyword := ""
			if len(keywords) > 1 {
				nextKeyword = keywords[(index+1)%len(keywords)]
			}
			appendGroup(keyword, nextKeyword)
		}
		if maxGroups > 0 && len(groups) >= maxGroups {
			return groups
		}
	}
	if len(groups) == 0 && primary != "" {
		appendGroup(primary)
	}
	return groups
}

func pulseSearchQuerySuffix(module string, year string) string {
	suffixes := pulseSearchQuerySuffixes(module, year)
	if len(suffixes) == 0 {
		return "recent update " + year
	}
	return suffixes[0]
}

func pulseSearchQuerySuffixes(module string, year string) []string {
	switch module {
	case pulseSourceInterestHot:
		return []string{
			"latest news " + year,
			"official update " + year,
			"independent analysis " + year,
			"industry data " + year,
		}
	case pulseSourceMemory:
		return []string{"recent update " + year, "new research " + year}
	default:
		return []string{"latest news " + year, "official release " + year, "independent report " + year}
	}
}

func pulseSearchQuerySuffixesForDate(module string, date string) []string {
	year := date
	if len(year) > 4 {
		year = year[:4]
	}
	suffixes := pulseSearchQuerySuffixes(module, year)
	reference, err := time.Parse("2006-01-02", date)
	if err != nil {
		return suffixes
	}
	window := pulseFreshnessWindow(module)
	since := reference.Add(-window).Format("2006-01-02")
	result := make([]string, 0, len(suffixes))
	for _, suffix := range suffixes {
		result = append(result, suffix+" after "+since)
	}
	return result
}

func cleanPulseSearchTerms(values []string) []string {
	seen := map[string]bool{}
	terms := make([]string, 0, len(values))
	for _, value := range values {
		cleaned := strings.TrimFunc(strings.Join(strings.Fields(value), " "), func(r rune) bool {
			return unicode.IsSpace(r) || r == ',' || r == '，' || r == ';' || r == '；'
		})
		if cleaned == "" {
			continue
		}
		key := strings.ToLower(cleaned)
		if seen[key] {
			continue
		}
		seen[key] = true
		terms = append(terms, cleaned)
	}
	return terms
}

func (h *PulseHandler) generatePulse(
	ctx context.Context,
	date string,
	userID string,
	topics []models.PulseTopic,
	signals []memoryPulseSignal,
	searchEvidence []pulseSearchEvidence,
	searchErrors []string,
) ([]models.PulseModule, []models.PulseItem, pulseGenerationDiagnostics, error) {
	diagnostics := pulseGenerationDiagnostics{}
	if h.agent == nil {
		return nil, nil, diagnostics, fmt.Errorf("agent client is not configured")
	}
	userID = normalizedUserID(userID)
	verifiedClusters := pulseVerifiedSearchClusters(date, searchEvidence)
	for index := range verifiedClusters {
		// Short, stable identifiers are much easier for a model to copy exactly
		// than full source URLs or the internal cluster key. Grounding still
		// validates the selected cluster against the generated copy below.
		verifiedClusters[index].QueryID = fmt.Sprintf("vc%d", index+1)
	}
	verifiedClusters = pulseSelectGenerationClusters(verifiedClusters)
	generationClusters := pulseCompactGenerationClusters(verifiedClusters)

	input := pulseGenerationInput{
		Date:             date,
		UserID:           userID,
		VerifiedClusters: generationClusters,
		MemorySignals:    signals,
		RetrievalSummary: pulseGenerationRetrievalSummary(searchEvidence, verifiedClusters),
	}
	inputJSON, _ := json.MarshalIndent(input, "", "  ")

	rawResponse, err := h.requestPulseGeneration(ctx, date, userID, string(inputJSON))
	if err != nil {
		return nil, nil, diagnostics, err
	}

	var payload generatedPulsePayload
	if err := decodePulseGeneration(rawResponse, &payload); err != nil {
		firstErr := err
		repairedResponse, repairErr := h.repairPulseGeneration(ctx, date, userID, string(inputJSON), rawResponse, err)
		if repairErr != nil {
			return nil, nil, diagnostics, fmt.Errorf("%w; repair_failed=%v; response_preview=%q", firstErr, repairErr, compactSnippet(rawResponse, 320))
		} else if err := decodePulseGeneration(repairedResponse, &payload); err != nil {
			return nil, nil, diagnostics, fmt.Errorf("%w; original_error=%v; repaired_preview=%q", err, firstErr, compactSnippet(repairedResponse, 320))
		}
	}
	if err := validateGeneratedPulsePayload(payload, false); err != nil {
		return nil, nil, diagnostics, fmt.Errorf("%w; response_preview=%q", err, compactSnippet(rawResponse, 320))
	}
	diagnostics.RawCandidateCount = generatedPulseItemCount(payload)
	filteredPayload, groundingRejections := filterGeneratedPulsePayloadByEvidenceWithDiagnostics(date, payload, verifiedClusters)
	diagnostics.CandidateRejections = append(diagnostics.CandidateRejections, groundingRejections...)
	if len(groundingRejections) > 0 {
		slog.Warn(
			"Pulse discarded generated items that failed evidence validation",
			"date", date,
			"discarded", len(groundingRejections),
			"remaining", generatedPulseItemCount(filteredPayload),
			"reasons", pulseRejectionReasonCounts(groundingRejections),
		)
	}
	if generatedPulseItemCount(filteredPayload) == 0 {
		return nil, nil, diagnostics, fmt.Errorf("agent returned no items backed by recent publishable sources")
	}
	payload = filteredPayload

	modules, items := generatedPayloadToModels(date, payload, topics)
	diagnostics.GroundedItemCount = len(items)
	if len(modules) == 0 {
		return nil, nil, diagnostics, fmt.Errorf("agent returned no pulse modules")
	}
	return modules, items, diagnostics, nil
}

func pulseGenerationRetrievalSummary(searchEvidence []pulseSearchEvidence, verifiedClusters []pulseSearchEvidence) map[string]int {
	successfulQueries := 0
	resultCount := 0
	for _, item := range searchEvidence {
		resultCount += len(item.Results)
		if len(item.Results) > 0 {
			successfulQueries++
		}
	}
	return map[string]int{
		"query_count":            len(searchEvidence),
		"successful_query_count": successfulQueries,
		"result_count":           resultCount,
		"verified_cluster_count": len(verifiedClusters),
	}
}

func pulseSelectGenerationClusters(clusters []pulseSearchEvidence) []pulseSearchEvidence {
	if len(clusters) <= pulseGenerationClusterLimit {
		return append([]pulseSearchEvidence{}, clusters...)
	}
	type rankedCluster struct {
		Evidence pulseSearchEvidence
		Score    int
		Index    int
	}
	ranked := make([]rankedCluster, 0, len(clusters))
	for index, cluster := range clusters {
		ranked = append(ranked, rankedCluster{
			Evidence: cluster,
			Score:    pulseSearchClusterScore(cluster, cluster.Results),
			Index:    index,
		})
	}
	sort.SliceStable(ranked, func(i, j int) bool {
		if ranked[i].Score == ranked[j].Score {
			return ranked[i].Index < ranked[j].Index
		}
		return ranked[i].Score > ranked[j].Score
	})

	selected := []pulseSearchEvidence{}
	deferred := []rankedCluster{}
	topicCounts := map[string]int{}
	for _, candidate := range ranked {
		topicKey := firstNonEmptyPulse(
			strings.TrimSpace(candidate.Evidence.TopicID),
			normalizedPulseTopicKey(candidate.Evidence.TopicName),
			candidate.Evidence.Module,
		)
		if topicCounts[topicKey] >= 2 {
			deferred = append(deferred, candidate)
			continue
		}
		selected = append(selected, candidate.Evidence)
		topicCounts[topicKey]++
		if len(selected) >= pulseGenerationClusterLimit {
			return selected
		}
	}
	for _, candidate := range deferred {
		selected = append(selected, candidate.Evidence)
		if len(selected) >= pulseGenerationClusterLimit {
			break
		}
	}
	return selected
}

func pulseCompactGenerationClusters(clusters []pulseSearchEvidence) []pulseSearchEvidence {
	compact := make([]pulseSearchEvidence, 0, len(clusters))
	for _, cluster := range clusters {
		item := pulseSearchEvidence{
			QueryID:   cluster.QueryID,
			Stage:     "cluster",
			Module:    cluster.Module,
			Query:     limitText(cluster.Query, 180),
			Intent:    cluster.Intent,
			Keyword:   cluster.Keyword,
			TopicID:   cluster.TopicID,
			TopicName: cluster.TopicName,
		}
		for _, result := range cluster.Results[:minInt(len(cluster.Results), pulseGenerationSourceLimit)] {
			result.Snippet = limitText(result.Snippet, pulseGenerationSnippetLimit-2)
			result.URL = pulseCompactGenerationSourceURL(result.URL)
			item.Results = append(item.Results, result)
		}
		compact = append(compact, item)
	}
	return compact
}

func pulseCompactGenerationSourceURL(rawURL string) string {
	parsed, err := url.Parse(strings.TrimSpace(rawURL))
	if err != nil || parsed.Hostname() == "" {
		return strings.TrimSpace(rawURL)
	}
	parsed.RawQuery = ""
	parsed.ForceQuery = false
	parsed.Fragment = ""
	return parsed.String()
}

func pulseGenerationEvidenceIndex(evidence []pulseSearchEvidence) []map[string]interface{} {
	index := make([]map[string]interface{}, 0, len(evidence))
	for _, item := range evidence {
		titles := make([]string, 0, minInt(len(item.Results), 2))
		for _, result := range item.Results[:minInt(len(item.Results), 2)] {
			titles = append(titles, limitText(result.Title, 140))
		}
		index = append(index, map[string]interface{}{
			"query_id":          item.QueryID,
			"stage":             item.Stage,
			"parent_query_id":   item.ParentQueryID,
			"module":            item.Module,
			"keyword":           item.Keyword,
			"query":             item.Query,
			"intent":            item.Intent,
			"topic_id":          item.TopicID,
			"topic_name":        item.TopicName,
			"rewritten_queries": item.RewrittenQueries,
			"result_count":      len(item.Results),
			"result_titles":     titles,
			"error":             item.Error,
		})
	}
	return index
}

func (h *PulseHandler) requestPulseGeneration(ctx context.Context, date string, userID string, inputJSON string) (string, error) {
	return h.requestPulseChat(
		ctx,
		fmt.Sprintf("pulse-%s-%s", normalizedUserID(userID), date),
		userID,
		pulseGenerationPrompt(),
		[]string{
			"你是 Pulse 推荐预计算器。必须只输出一个合法 JSON 对象，不要 Markdown，不要解释。",
			"你必须先阅读 verified_clusters，并且只基于其中已经达到发布条件的外网结果写新闻综述；不能只改写 topic/keyword。",
			"输入只提供已经通过发布门槛的 verified_clusters；原始 search_evidence 不会提供，禁止在这些簇之外补写事件或 URL。",
			"verified_clusters 已综合首搜与可选二搜；二搜成功与否不决定首轮可信事件是否成卡。",
			"verified_clusters 可能是一个近期官方/一手/权威事件、多个来源对同一事件的互证，也可能是 intent=keyword_digest 的首轮关键词综述；三者都可以生成 item。",
			"生成前必须先剔除和 query/topic 无关的搜索结果；如果剩余相关来源不足，不要硬生成推荐。",
			"每个 item 是一个资讯簇，必须原样复制一个 verified_clusters.query_id 到 evidence_id，并包含 news_sources 数组；signals 至少包含一个真实来源，格式为：搜索来源：标题 - URL。",
			"不得把单篇 CSDN/博客园/知乎/掘金/资源下载/转载聚合页包装成行业趋势；这类来源只能作为弱证据或辅助来源。",
			"title 必须写成中文资讯标题，并明确包含“可识别主体 + 具体动作/事件”，例如公司、产品或模型做了什么；禁止写“新线索值得跟踪”“新动向”“待核验信号”或“近期资讯聚合：...”。",
			"summary 必须在聚类完成后进一步写成 150-400 个中文字符、3-6 句的新闻综述：交代事件主体、时间、动作、产品/版本或关键数据，并总结来源一致点和有信息价值的差异；不得写推荐理由或核验套话。",
			"如果某模块没有搜索结果，items 可以为空，或明确说明搜索不足；禁止编造最新事实。",
		},
		[]string{
			"Pulse generation input JSON:\n" + string(inputJSON),
		},
	)
}

func (h *PulseHandler) repairPulseGeneration(ctx context.Context, date string, userID string, inputJSON string, brokenJSON string, parseErr error) (string, error) {
	return h.requestPulseChat(
		ctx,
		fmt.Sprintf("pulse-%s-%s-json-repair", normalizedUserID(userID), date),
		userID,
		pulseJSONRepairPrompt(parseErr),
		[]string{
			"你是 JSON 修复器。只输出一个合法 JSON 对象，不要 Markdown，不要解释。",
			"不得新增事实；只能修复语法、补齐缺失逗号/引号/括号，并按输入信号补齐缺失的必要字段。",
		},
		[]string{
			"Original Pulse input JSON:\n" + inputJSON,
			"Broken Pulse JSON:\n" + limitText(brokenJSON, 8000),
		},
	)
}

func (h *PulseHandler) requestPulseChat(ctx context.Context, conversationID string, userID string, message string, modePrompts []string, contextBlocks []string) (string, error) {
	memoryEnabled := false
	errors := []string{}
	if h.agent == nil {
		return "", fmt.Errorf("agent client is not configured")
	}
	for _, modelPreference := range h.pulseModelPreferences() {
		resp, err := h.agent.ChatContext(ctx, bridge.ChatRequest{
			ConversationID:  conversationID,
			UserID:          normalizedUserID(userID),
			Message:         message,
			Stream:          false,
			ModelPreference: modelPreference,
			AgentID:         "super_chat",
			ModePrompts:     modePrompts,
			ContextBlocks:   contextBlocks,
			MemoryEnabled:   &memoryEnabled,
			DisabledTools:   pulseBackgroundDisabledTools,
		})
		if err == nil {
			if resp == nil {
				return "", fmt.Errorf("agent returned empty response")
			}
			persistTokenUsageRecord(conversationID, userID, 0, pulseBackgroundAgentID, time.Now(), resp)
			return resp.Response, nil
		}
		errors = append(errors, fmt.Sprintf("%s: %v", pulseModelPreferenceLabel(modelPreference), err))
		slog.Warn("Pulse minimax model request failed", "conversation_id", conversationID, "model_preference", pulseModelPreferenceLabel(modelPreference), "error", err)
	}
	return "", fmt.Errorf("%s", strings.Join(errors, "; "))
}

func (h *PulseHandler) pulseModelPreferences() []*string {
	preference := "minimax"
	if h.syncer == nil {
		return []*string{stringPointer(preference)}
	}
	settings, err := h.syncer.SettingsMap()
	if err != nil {
		slog.Warn("Pulse model preference load failed", "error", err)
		return []*string{stringPointer(preference)}
	}
	if model := strings.TrimSpace(settings["llm.minimax.model"]); model != "" {
		preference = "minimax:" + model
	}
	return []*string{stringPointer(preference)}
}

func pulseModelPreferenceLabel(value *string) string {
	if value == nil || strings.TrimSpace(*value) == "" {
		return "default"
	}
	return *value
}

func stringPointer(value string) *string {
	return &value
}

func pulseGenerationPrompt() string {
	return `请根据上下文中的 Pulse generation input JSON 预计算今日 Pulse。

只输出一个 JSON 对象，禁止 Markdown、注释、尾随逗号或任何解释。结构必须是：
{"modules":[{"key":"topic_hot","title":"...","summary":"...","items":[{"evidence_id":"vc1","topic_id":"","topic_name":"","category":"...","title":"...","summary":"...","heat_score":80,"recommendation_reason":"...","signals":["..."],"quick_context":"...","key_points":["...","...","..."],"news_sources":[{"title":"...","url":"https://...","source":"...","snippet":"...","published_at":"..."}],"suggested_questions":["...","...","..."],"explore_prompt":"..."}]}]}

硬性要求：
- modules 必须且只能包含 topic_hot、memory、interest_hot 三个 key。
- 必须先阅读 verified_clusters；每个元素要么是近期官方/一手/权威来源确认的具体事件，要么是跨查询完成互证的同一事件簇，要么是 intent=keyword_digest 的首轮关键词综述。只能围绕这些结果生成 item，推荐内容必须来自其中的 title/snippet/url，而不是改写 topic/keyword。
- 每个 item 必须且只能对应一个 verified_clusters 元素，并把该元素的 query_id 原样复制到 evidence_id；不要自己生成、缩写或改写 evidence_id。
- 输入只包含已经通过发布门槛的 verified_clusters，原始 search_evidence 已有意省略；不得根据 topic、keyword 或常识新增这些簇之外的事件、来源和 URL。
- verified_clusters 已综合首搜与可选二搜；二搜只用于补充来源、正文和事件背景，没有二搜结果时不得丢弃首轮已经满足条件的可信事件。
- intent=keyword_digest 时，围绕该关键词归纳 2-3 个来源共同指向的近期方向，并明确区分“趋势综述”和“单一具体事件”；不要伪装成某家公司刚刚发布了产品。
- CSDN、博客园、知乎、掘金、资源下载页、转载聚合页只能作为弱证据；不能把单篇此类来源包装成“趋势/范式/外网热门”。如果只有弱证据，降低 heat_score 并说明“仅作待核验线索”，或不生成该 item。
- topic_hot 必须优先使用 module=topic_hot 的搜索结果；interest_hot 必须使用 module=interest_hot 的搜索结果；memory 可结合 memory_signals 和搜索结果。
- 每个 item 是一个具体资讯事件：优先聚合 2-5 条相关结果；首轮只有 1 条来源时，必须是近期官方/一手来源或权威媒体，并且标题和摘要足以识别事件主体、动作及事实。
- title 写成中文编辑标题，必须同时包含可识别主体（公司、组织、产品、模型或项目）和具体动作/事件（如发布、开放、收购、融资、更新、下线或数据变化）；保留 GPT-5、Claude、OpenAI 等必要专名即可。禁止直接复制英文搜索标题，禁止写“近期资讯聚合：来源标题...”“新线索值得跟踪”“新动向”“待核验线索”或“发布与开放信号待核验”。
- item.summary 是卡片唯一的“新闻簇内容”字段：必须在聚类后进一步总结为 150-400 个中文字符、3-6 句。先说明“谁在何时做了什么”，再写发布/开放的产品、版本、能力或关键数据，最后概括来源的一致信息和有价值的差异。不要写推荐理由、核验套话、来源数量或“出现新的外部资讯信号”；禁止拼接来源标题/snippet，禁止写“聚合 N 条来源，关键线索是...”。不足 150 字或无法提取具体事实时，不要生成这个 item。
- 如果无法提取具体事实，不要生成这个 item。
- recommendation_reason 只解释“为什么与这个用户相关”，必须是一句短句，不超过约 50 个中文字符；不得复述 summary、来源或核验提醒。
- news_sources 必须包含 1-5 个来自 verified_clusters 的来源对象，url 必须原样复制。
- news_sources 只有 1 个时，该来源必须是近期官方/一手来源或权威媒体，并明确描述一项具体事件；事件簇的多个来源必须来自独立发布机构并描述同一事件。intent=keyword_digest 时允许来源描述同一关键词下的不同进展，但标题和 summary 必须明确写成趋势综述。转载的相同标题不能算独立来源，二搜来源只负责补充内容，不是发布前置条件。
- 每个 item 的 signals 必须至少包含一个真实来源，格式为“搜索来源：标题 - URL”。
- quick_context 只补充来源之间的一致点、差异或证据强弱，不得复述 summary、recommendation_reason 或整段来源 snippet。
- key_points 只写 2-3 个简短事实标签，不得写“推荐理由”“核验动作”或重复来源。
- items 总数最多 18 条，证据充分时目标 8-12 条；质量优先，绝不为了数量复用来源或拆分同一事件。每个 item 恰好生成 3 个 suggested_questions。
- suggested_questions 必须像真实用户会点击的短任务型追问，每个尽量不超过 32 个中文字符；禁止“用 5 分钟帮我读懂……”等长模板。
- suggested_questions 里要点名具体技术、公司、地点、来源标题、数据或争议点；禁止使用“为什么值得关注/有哪些风险/这些来源说明什么趋势/对我意味着什么”这类泛化模板，也不要写成考试题或评审题。
- 所有面向用户的文本使用中文。
- 不要编造具体新闻事实；如果 verified_clusters 为空或不足，减少对应模块的 items，允许 items 为空。`
}

func pulseJSONRepairPrompt(parseErr error) string {
	return fmt.Sprintf(`上一次 Pulse 预计算输出不是合法 JSON，解析错误是：%v。

请修复 Broken Pulse JSON，返回且只返回修复后的 JSON 对象。
必须保留 modules 数组，并包含 topic_hot、memory、interest_hot 三个模块。
每个 item 必须包含 suggested_questions 数组，恰好 3 条；每条应引用具体标题、来源或关键点，并尽量不超过 32 个中文字符。
item.title 必须包含可识别主体和具体动作/事件；禁止“新线索值得跟踪”“新动向”等占位标题。
item.summary 必须保留 150-400 个中文字符、3-6 句可由同一事件簇支持的具体新闻事实；无法说明谁做了什么就删除该 item。recommendation_reason 只保留一句简短的用户相关性说明。`, parseErr)
}

func decodePulseGeneration(value string, payload *generatedPulsePayload) error {
	text := strings.TrimSpace(value)
	if err := json.Unmarshal([]byte(text), payload); err == nil {
		return nil
	}

	start := strings.Index(text, "{")
	end := strings.LastIndex(text, "}")
	if start < 0 || end <= start {
		return fmt.Errorf("agent response did not contain JSON")
	}
	if err := json.Unmarshal([]byte(text[start:end+1]), payload); err != nil {
		return fmt.Errorf("decode pulse JSON: %w", err)
	}
	return nil
}

func validateGeneratedPulsePayload(payload generatedPulsePayload, requireSearchSources bool) error {
	moduleKeys := map[string]bool{}
	itemCount := 0
	for _, module := range payload.Modules {
		key := normalizePulseModuleKey(module.Key)
		if key == "" {
			continue
		}
		moduleKeys[key] = true
		itemCount += len(module.Items)
		for _, item := range module.Items {
			if strings.TrimSpace(item.Title) == "" {
				continue
			}
			if requireSearchSources && !pulseItemHasSearchSource(item) {
				return fmt.Errorf("agent returned item %q without search sources", item.Title)
			}
		}
	}
	for _, key := range pulseModuleOrder {
		if !moduleKeys[key] {
			return fmt.Errorf("agent omitted required pulse module %q", key)
		}
	}
	if itemCount == 0 {
		return fmt.Errorf("agent returned no pulse items")
	}
	return nil
}

func pulseItemHasSearchSource(item generatedPulseItem) bool {
	for _, source := range append(item.NewsSources, item.Sources...) {
		if strings.TrimSpace(source.URL) != "" {
			return true
		}
	}
	for _, signal := range item.Signals {
		normalized := strings.ToLower(signal)
		if strings.Contains(signal, "搜索来源") || strings.Contains(normalized, "http://") || strings.Contains(normalized, "https://") {
			return true
		}
	}
	return false
}

func filterGeneratedPulsePayloadByEvidence(date string, payload generatedPulsePayload, evidence []pulseSearchEvidence) (generatedPulsePayload, int) {
	filtered, rejections := filterGeneratedPulsePayloadByEvidenceWithDiagnostics(date, payload, evidence)
	return filtered, len(rejections)
}

func filterGeneratedPulsePayloadByEvidenceWithDiagnostics(
	date string,
	payload generatedPulsePayload,
	evidence []pulseSearchEvidence,
) (generatedPulsePayload, []pulseCandidateRejectionDiagnostic) {
	allowedByModule := map[string]map[string]pulseNewsSource{}
	allowedGlobally := map[string]pulseNewsSource{}
	for _, queryEvidence := range evidence {
		module := normalizePulseModuleKey(queryEvidence.Module)
		if module == "" {
			continue
		}
		if allowedByModule[module] == nil {
			allowedByModule[module] = map[string]pulseNewsSource{}
		}
		for _, result := range queryEvidence.Results {
			key := pulseSearchResultDedupeKey(result)
			if key == "" {
				continue
			}
			source := pulseNewsSource{
				Title:       result.Title,
				URL:         result.URL,
				Source:      result.Source,
				Snippet:     result.Snippet,
				PublishedAt: result.PublishedAt,
			}
			allowedByModule[module][key] = source
			allowedGlobally[key] = source
		}
	}

	filtered := generatedPulsePayload{Modules: make([]generatedPulseModule, 0, len(payload.Modules))}
	rejections := []pulseCandidateRejectionDiagnostic{}
	usedGroundedClusters := map[string]bool{}
	for _, module := range payload.Modules {
		key := normalizePulseModuleKey(module.Key)
		allowed := allowedByModule[key]
		items := make([]generatedPulseItem, 0, len(module.Items))
		for _, item := range module.Items {
			matched := make([]pulseNewsSource, 0, pulseSearchClusterMaxSources)
			seen := map[string]bool{}
			candidates := append([]pulseNewsSource{}, item.NewsSources...)
			candidates = append(candidates, item.Sources...)
			candidates = append(candidates, newsSourcesFromSignals(item.Signals, pulseSearchClusterMaxSources)...)
			for _, candidate := range candidates {
				sourceKey := pulseSearchResultDedupeKey(pulseSearchResult{URL: candidate.URL})
				if sourceKey == "" || seen[sourceKey] {
					continue
				}
				source, ok := allowed[sourceKey]
				if !ok {
					// Modules are presentation buckets, not evidence boundaries. The
					// same event can be discovered by a topic query and corroborated by
					// an interest or memory query, so accept an explicitly cited URL
					// from any Pulse search module.
					source, ok = allowedGlobally[sourceKey]
					if !ok {
						continue
					}
				}
				seen[sourceKey] = true
				matched = append(matched, source)
				if len(matched) >= pulseSearchClusterMaxSources {
					break
				}
			}
			matched = pulseExpandGeneratedItemSources(matched, evidence, seen)
			groundedSources, evidenceMode := pulseGroundGeneratedSources(date, key, matched, evidence)
			if len(groundedSources) == 0 {
				recoveredSources, recoveredMode := pulseRecoverGeneratedItemSources(date, key, item, evidence)
				if len(recoveredSources) > 0 {
					matched = recoveredSources
					groundedSources, evidenceMode = pulseGroundGeneratedSources(date, key, recoveredSources, evidence)
					if evidenceMode == "" {
						evidenceMode = recoveredMode
					}
				}
			}
			if evidenceMode != "" {
				item.EvidenceMode = evidenceMode
			}
			reasons := []string{}
			if strings.TrimSpace(item.Title) == "" {
				reasons = append(reasons, "missing_title")
			}
			if strings.TrimSpace(item.Summary) == "" {
				reasons = append(reasons, "missing_summary")
			}
			if len(matched) == 0 {
				reasons = append(reasons, "no_matching_search_source")
			} else if len(groundedSources) == 0 {
				reasons = append(reasons, "insufficient_publishable_sources")
			}
			if item.EvidenceMode == "keyword_digest" && len(groundedSources) > 0 &&
				!pulseKeywordDigestTitleClaimsSupported(item.Title, groundedSources) {
				reasons = append(reasons, "unsupported_digest_title_claim")
			}
			groundedClusterKey := pulseGroundedSourceClusterKey(groundedSources)
			if groundedClusterKey != "" && usedGroundedClusters[groundedClusterKey] {
				reasons = append(reasons, "duplicate_evidence_cluster")
			}
			if len(reasons) > 0 {
				diagnosticSources := groundedSources
				if len(diagnosticSources) == 0 {
					diagnosticSources = matched
				}
				rejections = append(rejections, pulseCandidateRejectionDiagnostic{
					Stage:         "grounding",
					Module:        key,
					TopicID:       item.TopicID,
					TopicName:     limitText(cleanSearchText(item.TopicName), 100),
					Title:         limitText(cleanSearchText(item.Title), 180),
					Reasons:       reasons,
					SourceCount:   len(diagnosticSources),
					SourceDomains: pulseNewsSourceDomains(diagnosticSources),
				})
				continue
			}
			if groundedClusterKey != "" {
				usedGroundedClusters[groundedClusterKey] = true
			}
			item.NewsSources = groundedSources
			item.Sources = nil
			item.Signals = pulseSignalsWithVerifiedSources(item.Signals, groundedSources)
			item.HeatScore = pulseVerifiedEvidenceHeatScore(groundedSources, item.HeatScore)
			items = append(items, item)
		}
		module.Items = items
		filtered.Modules = append(filtered.Modules, module)
	}
	return filtered, rejections
}

func pulseGroundedSourceClusterKey(sources []pulseNewsSource) string {
	keys := []string{}
	for _, source := range sources {
		key := pulseSearchResultDedupeKey(pulseSearchResult{URL: source.URL})
		if key != "" {
			keys = appendUniqueStrings(keys, key)
		}
	}
	sort.Strings(keys)
	return strings.Join(keys, "|")
}

func pulseKeywordDigestTitleClaimsSupported(title string, sources []pulseNewsSource) bool {
	claims := []string{}
	claims = appendUniqueStrings(claims, pulseArabicQuantitativeClaimPattern.FindAllString(title, -1)...)
	claims = appendUniqueStrings(claims, pulseChineseQuantitativeClaimPattern.FindAllString(title, -1)...)
	for _, claim := range claims {
		normalizedClaim := strings.ToLower(strings.Join(strings.Fields(claim), ""))
		if normalizedClaim == "" || pulseQuantitativeClaimIsCalendarYear(normalizedClaim) {
			continue
		}
		matchingResults := []pulseSearchResult{}
		for _, source := range sources {
			text := strings.ToLower(strings.Join(strings.Fields(strings.Join([]string{
				source.Title,
				source.Snippet,
				source.PublishedAt,
			}, " ")), ""))
			if strings.Contains(text, normalizedClaim) {
				matchingResults = append(matchingResults, pulseSearchResult{
					Title: source.Title, Snippet: source.Snippet, URL: source.URL,
				})
			}
		}
		if pulseSearchIndependentSourceCount(matchingResults) < 2 {
			return false
		}
	}
	return true
}

func pulseQuantitativeClaimIsCalendarYear(claim string) bool {
	claim = strings.TrimSuffix(strings.TrimSpace(claim), "年")
	if len(claim) != 4 || (claim[:2] != "19" && claim[:2] != "20") {
		return false
	}
	_, err := strconv.Atoi(claim)
	return err == nil
}

func pulseGroundGeneratedSources(date string, module string, matched []pulseNewsSource, evidence []pulseSearchEvidence) ([]pulseNewsSource, string) {
	if grounded := pulseCorroboratedGeneratedSources(matched, evidence); len(grounded) > 0 {
		return grounded, ""
	}
	if grounded := pulseKeywordDigestGroundedSources(date, module, matched, evidence); len(grounded) > 0 {
		return grounded, "keyword_digest"
	}
	for _, source := range matched {
		result := pulseSearchResultsFromNewsSources([]pulseNewsSource{source})
		if len(result) == 1 && pulseTrustedSingletonMeetsQualityGate(date, module, result[0]) {
			return []pulseNewsSource{source}, ""
		}
	}
	return nil, ""
}

type pulseGeneratedClusterMatch struct {
	Evidence pulseSearchEvidence
	Score    int
}

func pulseRecoverGeneratedItemSources(
	date string,
	module string,
	item generatedPulseItem,
	evidence []pulseSearchEvidence,
) ([]pulseNewsSource, string) {
	matches := []pulseGeneratedClusterMatch{}
	for _, candidate := range evidence {
		if candidate.Stage != "cluster" || len(candidate.Results) == 0 ||
			!pulseGeneratedItemTopicMatchesCluster(item, candidate) {
			continue
		}
		sources := newsSourcesFromSearchResults(candidate.Results, pulseSearchClusterMaxSources)
		if len(pulseItemSourceQualityIssues(date, module, candidate.Intent, sources)) > 0 {
			continue
		}
		if candidate.Intent == "keyword_digest" &&
			len(pulseItemCopyQualityIssues("keyword_digest", item.Title, item.Summary)) > 0 {
			continue
		}
		score := pulseGeneratedItemClusterMatchScore(item, candidate)
		if score <= 0 {
			continue
		}
		matches = append(matches, pulseGeneratedClusterMatch{Evidence: candidate, Score: score})
	}
	if len(matches) == 0 {
		return nil, ""
	}
	sort.SliceStable(matches, func(i, j int) bool {
		return matches[i].Score > matches[j].Score
	})

	requestedEvidenceID := strings.TrimSpace(item.EvidenceID)
	if requestedEvidenceID != "" {
		for _, match := range matches {
			if match.Evidence.QueryID == requestedEvidenceID && match.Score >= 24 {
				return newsSourcesFromSearchResults(match.Evidence.Results, pulseSearchClusterMaxSources), match.Evidence.Intent
			}
		}
	}

	best := matches[0]
	if best.Score < 50 || (len(matches) > 1 && best.Score-matches[1].Score < 12) {
		return nil, ""
	}
	return newsSourcesFromSearchResults(best.Evidence.Results, pulseSearchClusterMaxSources), best.Evidence.Intent
}

func pulseGeneratedItemTopicMatchesCluster(item generatedPulseItem, cluster pulseSearchEvidence) bool {
	itemTopicID := strings.TrimSpace(item.TopicID)
	clusterTopicID := strings.TrimSpace(cluster.TopicID)
	if itemTopicID != "" && clusterTopicID != "" {
		return itemTopicID == clusterTopicID
	}
	itemTopicName := normalizedPulseTopicKey(item.TopicName)
	clusterTopicName := normalizedPulseTopicKey(cluster.TopicName)
	return itemTopicName == "" || clusterTopicName == "" || itemTopicName == clusterTopicName
}

func pulseGeneratedItemClusterMatchScore(item generatedPulseItem, cluster pulseSearchEvidence) int {
	itemText := cleanSearchText(strings.Join([]string{item.Title, item.Summary, item.Category}, " "))
	if itemText == "" {
		return 0
	}
	score := 0
	if strings.TrimSpace(item.TopicID) != "" && item.TopicID == cluster.TopicID {
		score += 6
	}
	keyword := strings.ToLower(strings.TrimSpace(cluster.Keyword))
	if keyword != "" && !pulseSearchTermLooksGeneric(keyword) && pulseSearchTextContainsTerm(itemText, keyword) {
		score += 35
	}

	bestTitleSimilarity := 0
	clusterTerms := []string{}
	for _, result := range cluster.Results {
		bestTitleSimilarity = maxInt(bestTitleSimilarity, pulseNormalizedTextSimilarity(item.Title, result.Title))
		clusterTerms = appendUniqueStrings(clusterTerms, pulseCorroborationTerms(result)...)
	}
	switch {
	case bestTitleSimilarity >= 80:
		score += 55
	case bestTitleSimilarity >= 55:
		score += 40
	case bestTitleSimilarity >= 35:
		score += 25
	case bestTitleSimilarity >= 20:
		score += 12
	}

	itemTerms := pulseCorroborationTerms(pulseSearchResult{Title: item.Title, Snippet: item.Summary})
	termScore := 0
	for _, term := range intersectPulseTerms(itemTerms, clusterTerms) {
		if pulseCorroborationTermLooksGeneric(term) {
			continue
		}
		termScore += 6
		if pulseCorroborationTermLooksStrong(term) {
			termScore += 4
		}
		if termScore >= 30 {
			termScore = 30
			break
		}
	}
	return score + termScore
}

func pulseNormalizedTextSimilarity(left string, right string) int {
	leftRunes := pulseComparableTextRunes(left)
	rightRunes := pulseComparableTextRunes(right)
	if len(leftRunes) < 2 || len(rightRunes) < 2 {
		return 0
	}
	leftText := string(leftRunes)
	rightText := string(rightRunes)
	if minInt(len(leftRunes), len(rightRunes)) >= 4 &&
		(strings.Contains(leftText, rightText) || strings.Contains(rightText, leftText)) {
		return 100
	}
	leftBigrams := pulseRuneBigrams(leftRunes)
	rightBigrams := pulseRuneBigrams(rightRunes)
	shared := 0
	for bigram := range leftBigrams {
		if rightBigrams[bigram] {
			shared++
		}
	}
	if shared == 0 {
		return 0
	}
	return 200 * shared / (len(leftBigrams) + len(rightBigrams))
}

func pulseComparableTextRunes(value string) []rune {
	runes := []rune{}
	for _, r := range strings.ToLower(cleanSearchText(value)) {
		if unicode.IsLetter(r) || unicode.IsDigit(r) {
			runes = append(runes, r)
		}
	}
	return runes
}

func pulseRuneBigrams(runes []rune) map[string]bool {
	bigrams := map[string]bool{}
	for index := 0; index+1 < len(runes); index++ {
		bigrams[string(runes[index:index+2])] = true
	}
	return bigrams
}

func pulseExpandGeneratedItemSources(matched []pulseNewsSource, evidence []pulseSearchEvidence, seen map[string]bool) []pulseNewsSource {
	if len(matched) == 0 || len(matched) >= pulseSearchClusterMaxSources {
		return matched
	}
	for _, queryEvidence := range evidence {
		var seed pulseSearchResult
		foundSeed := false
		for _, result := range queryEvidence.Results {
			key := pulseSearchResultDedupeKey(result)
			if key != "" && seen[key] {
				seed = result
				foundSeed = true
				break
			}
		}
		if !foundSeed {
			continue
		}
		for _, result := range queryEvidence.Results {
			key := pulseSearchResultDedupeKey(result)
			if key == "" || seen[key] || !pulseSearchResultsCorroborate(queryEvidence, seed, result) {
				continue
			}
			seen[key] = true
			matched = append(matched, pulseNewsSource{
				Title:       result.Title,
				URL:         result.URL,
				Source:      result.Source,
				Snippet:     result.Snippet,
				PublishedAt: result.PublishedAt,
			})
			if len(matched) >= pulseSearchClusterMaxSources {
				return matched
			}
		}
	}
	return matched
}

func pulseGeneratedSourcesAreCorroborated(sources []pulseNewsSource, evidence []pulseSearchEvidence) bool {
	return len(pulseCorroboratedGeneratedSources(sources, evidence)) >= 2
}

func pulseKeywordDigestGroundedSources(
	date string,
	module string,
	sources []pulseNewsSource,
	evidence []pulseSearchEvidence,
) []pulseNewsSource {
	if len(sources) < 2 {
		return nil
	}
	matchedByKey := map[string]pulseNewsSource{}
	for _, source := range sources {
		if key := pulseSearchResultDedupeKey(pulseSearchResult{URL: source.URL}); key != "" {
			matchedByKey[key] = source
		}
	}
	for _, item := range evidence {
		if item.Intent != "keyword_digest" || normalizePulseModuleKey(item.Module) != normalizePulseModuleKey(module) {
			continue
		}
		digestSources := []pulseNewsSource{}
		for _, result := range item.Results {
			key := pulseSearchResultDedupeKey(result)
			if source, ok := matchedByKey[key]; ok {
				digestSources = append(digestSources, source)
			}
		}
		if pulseKeywordDigestSourcesMeetQualityGate(date, module, digestSources) {
			return normalizeNewsSources(digestSources, pulseSearchClusterMaxSources)
		}
	}
	return nil
}

func pulseCorroboratedGeneratedSources(sources []pulseNewsSource, evidence []pulseSearchEvidence) []pulseNewsSource {
	if len(sources) < 2 {
		return nil
	}
	sourceIndexes := map[string]int{}
	for index, source := range sources {
		if key := pulseSearchResultDedupeKey(pulseSearchResult{URL: source.URL}); key != "" {
			sourceIndexes[key] = index
		}
	}
	edges := make([]map[int]bool, len(sources))
	for index := range edges {
		edges[index] = map[int]bool{}
	}
	for _, queryEvidence := range evidence {
		matchedResults := map[int]pulseSearchResult{}
		for _, result := range queryEvidence.Results {
			if index, ok := sourceIndexes[pulseSearchResultDedupeKey(result)]; ok {
				matchedResults[index] = result
			}
		}
		indexes := make([]int, 0, len(matchedResults))
		for index := range matchedResults {
			indexes = append(indexes, index)
		}
		sort.Ints(indexes)
		for leftPosition, leftIndex := range indexes {
			for _, rightIndex := range indexes[leftPosition+1:] {
				if pulseSearchResultsCorroborate(queryEvidence, matchedResults[leftIndex], matchedResults[rightIndex]) {
					edges[leftIndex][rightIndex] = true
					edges[rightIndex][leftIndex] = true
				}
			}
		}
	}

	best := pulseLargestFullyCorroboratedSourceSet(edges)
	if len(best) < 2 {
		return nil
	}
	sort.Ints(best)
	corroborated := make([]pulseNewsSource, 0, len(best))
	for _, index := range best {
		corroborated = append(corroborated, sources[index])
	}
	if pulseSearchIndependentSourceCount(pulseSearchResultsFromNewsSources(corroborated)) < 2 {
		return nil
	}
	return corroborated
}

func pulseLargestFullyCorroboratedSourceSet(edges []map[int]bool) []int {
	best := []int{}
	if len(edges) < 2 || len(edges) > pulseSearchClusterMaxSources {
		return best
	}
	for mask := 1; mask < (1 << len(edges)); mask++ {
		indexes := []int{}
		for index := range edges {
			if mask&(1<<index) != 0 {
				indexes = append(indexes, index)
			}
		}
		if len(indexes) < 2 || len(indexes) <= len(best) {
			continue
		}
		complete := true
		for leftPosition, left := range indexes {
			for _, right := range indexes[leftPosition+1:] {
				if !edges[left][right] {
					complete = false
					break
				}
			}
			if !complete {
				break
			}
		}
		if complete {
			best = indexes
		}
	}
	return best
}

func generatedPulseItemCount(payload generatedPulsePayload) int {
	count := 0
	for _, module := range payload.Modules {
		count += len(module.Items)
	}
	return count
}

func pulseSignalsWithVerifiedSources(signals []string, sources []pulseNewsSource) []string {
	verified := make([]string, 0, len(signals)+len(sources))
	for _, signal := range signals {
		if !strings.Contains(strings.ToLower(signal), "http://") &&
			!strings.Contains(strings.ToLower(signal), "https://") {
			verified = append(verified, signal)
		}
	}
	for _, source := range sources {
		verified = append(
			verified,
			fmt.Sprintf("搜索来源：%s - %s", firstNonEmptyPulse(source.Title, source.Source, "外网结果"), source.URL),
		)
	}
	return limitStringSlice(verified, 6, 220)
}

func pulseVerifiedEvidenceHeatScore(sources []pulseNewsSource, editorialScore int) int {
	results := pulseSearchResultsFromNewsSources(sources)
	independentSources := pulseSearchIndependentSourceCount(results)
	weakSources := 0
	for _, result := range results {
		if pulseWeakSearchSource(result) {
			weakSources++
		}
	}
	score := 58 + independentSources*7 + minInt(maxInt(editorialScore, 0)/12, 8) - weakSources*3
	return maxInt(55, minInt(score, 95))
}

func generatedPayloadToModels(date string, payload generatedPulsePayload, topics []models.PulseTopic) ([]models.PulseModule, []models.PulseItem) {
	topicByID := map[string]models.PulseTopic{}
	topicByName := map[string]models.PulseTopic{}
	for _, topic := range topics {
		topicByID[topic.ID] = topic
		topicByName[strings.ToLower(topic.Name)] = topic
	}

	now := time.Now()
	modules := make([]models.PulseModule, 0, len(pulseModuleOrder))
	items := []models.PulseItem{}
	seenModules := map[string]bool{}
	for _, generated := range payload.Modules {
		key := normalizePulseModuleKey(generated.Key)
		if key == "" || seenModules[key] {
			continue
		}
		seenModules[key] = true
		title, summary := defaultPulseModuleCopy(key)
		if strings.TrimSpace(generated.Title) != "" {
			title = strings.TrimSpace(generated.Title)
		}
		if strings.TrimSpace(generated.Summary) != "" {
			summary = strings.TrimSpace(generated.Summary)
		}
		modules = append(modules, models.PulseModule{
			ID:        pulseItemID(date, "module", key),
			Date:      date,
			Key:       key,
			Title:     title,
			Summary:   summary,
			CreatedAt: now,
			UpdatedAt: now,
		})
		for index, generatedItem := range generated.Items {
			if len(items) >= pulseCandidateMaxCount {
				break
			}
			if strings.TrimSpace(generatedItem.Title) == "" {
				continue
			}
			topicID := strings.TrimSpace(generatedItem.TopicID)
			topicName := strings.TrimSpace(generatedItem.TopicName)
			if topicID != "" {
				if topic, ok := topicByID[topicID]; ok {
					topicName = topic.Name
				}
			} else if topicName != "" {
				if topic, ok := topicByName[strings.ToLower(topicName)]; ok {
					topicID = topic.ID
					topicName = topic.Name
				}
			}
			newsSources := normalizeNewsSources(append(generatedItem.NewsSources, generatedItem.Sources...), 5)
			if len(newsSources) == 0 {
				newsSources = newsSourcesFromSignals(generatedItem.Signals, 5)
			}
			originalTitle := cleanSearchText(generatedItem.Title)
			originalSummary := cleanSearchText(generatedItem.Summary)
			originalCopyValid := pulseNewsCopyMeetsQualityGate(originalTitle, originalSummary)
			itemTitle := originalTitle
			itemSummary := originalSummary
			fallbackResults := pulseSearchResultsFromNewsSources(newsSources)
			fallbackEvidence := pulseSearchEvidence{
				Module:    key,
				Query:     firstNonEmptyPulse(topicName, generatedItem.Category, generatedItem.Title),
				TopicID:   topicID,
				TopicName: topicName,
				Intent:    generatedItem.Category,
				Results:   fallbackResults,
			}
			if pulseItemCopyLooksLikeSearchDump(itemTitle, itemSummary) {
				if len(fallbackResults) > 0 {
					if pulseTitleLooksLikeSearchDump(itemTitle) {
						itemTitle = searchFallbackClusterTitle(key, fallbackEvidence, fallbackResults)
					}
					if pulseSummaryLooksLikeSearchDump(itemSummary) {
						itemSummary = searchFallbackClusterSummary(fallbackEvidence, fallbackResults)
					}
				}
			}
			if len([]rune(cleanSearchText(itemSummary))) < pulseSummaryMinRunes {
				if expanded := searchFallbackClusterSummary(fallbackEvidence, fallbackResults); len([]rune(expanded)) >= pulseSummaryMinRunes {
					itemSummary = expanded
				}
			}
			itemSummary = pulseCompactSummary(itemSummary)
			itemTitle = limitText(itemTitle, 120)
			if originalCopyValid && !pulseNewsCopyMeetsQualityGate(itemTitle, itemSummary) {
				itemTitle = originalTitle
				itemSummary = originalSummary
			}
			recommendationReason := pulseCompactRecommendationReason(generatedItem.RecommendationReason)
			keyPoints := pulseCompactKeyPoints(generatedItem.KeyPoints)
			questionContext := pulseQuestionContext{
				Title:     itemTitle,
				Summary:   itemSummary,
				Module:    key,
				TopicName: topicName,
				Category:  generatedItem.Category,
				KeyPoints: keyPoints,
				Context:   generatedItem.QuickContext,
				Sources:   newsSources,
			}
			detail := pulseItemDetail{
				ContentVersion:       pulseContentVersion,
				EvidenceMode:         generatedItem.EvidenceMode,
				RecommendationReason: recommendationReason,
				Signals:              limitStringSlice(generatedItem.Signals, 6, 180),
				QuickContext:         pulseCompactDetailContext(generatedItem.QuickContext, itemSummary, recommendationReason),
				KeyPoints:            keyPoints,
				NewsSources:          newsSources,
				SuggestedQuestions:   personalizedPulseSuggestedQuestions(generatedItem.SuggestedQuestions, questionContext),
				PrecomputedAt:        now.UTC().Format(time.RFC3339),
			}
			if len(detail.Signals) == 0 {
				detail.Signals = []string{"由 Pulse 预计算 Agent 根据 topic 与 memory 信号生成。"}
			}
			items = append(items, models.PulseItem{
				ID:            pulseItemID(date, key, fmt.Sprintf("%s:%d", itemTitle, index)),
				Date:          date,
				TopicID:       topicID,
				TopicName:     topicName,
				Source:        key,
				Category:      limitText(firstNonEmptyPulse(generatedItem.Category, moduleCategory(key)), 80),
				Title:         itemTitle,
				Summary:       itemSummary,
				HeatScore:     normalizeHeatScore(generatedItem.HeatScore, key, index),
				DetailJSON:    mustJSON(detail),
				ExplorePrompt: limitText(firstNonEmptyPulse(generatedItem.ExplorePrompt, fmt.Sprintf("请展开「%s」，并说明为什么推荐给我。", itemTitle)), 600),
				CreatedAt:     now,
				UpdatedAt:     now,
			})
		}
		if len(items) >= pulseCandidateMaxCount {
			break
		}
	}

	sortPulseModules(modules)
	return modules, items
}

func buildSearchFallbackPulse(date string, topics []models.PulseTopic, signals []memoryPulseSignal, evidence []pulseSearchEvidence, searchErrors []string) ([]models.PulseModule, []models.PulseItem) {
	now := time.Now()
	modules := make([]models.PulseModule, 0, len(pulseModuleOrder))
	for _, key := range pulseModuleOrder {
		count := 0
		for _, item := range evidence {
			if normalizePulseModuleKey(item.Module) == key {
				count += len(item.Results)
			}
		}
		title, summary := searchFallbackModuleCopy(key, count, searchErrors)
		modules = append(modules, models.PulseModule{
			ID:        pulseItemID(date, "module", key),
			Date:      date,
			Key:       key,
			Title:     title,
			Summary:   summary,
			CreatedAt: now,
			UpdatedAt: now,
		})
	}

	candidates := []models.PulseItem{}
	perModuleCount := map[string]int{}
	seenResultKeys := map[string]bool{}
	for _, queryEvidence := range pulseVerifiedSearchClusters(date, evidence) {
		module := normalizePulseModuleKey(queryEvidence.Module)
		if module == "" || len(queryEvidence.Results) == 0 {
			continue
		}
		clusterResults := pulseFilterNewSearchFallbackResults(queryEvidence.Results, seenResultKeys)
		if len(pulseItemSourceQualityIssues(
			date,
			module,
			queryEvidence.Intent,
			newsSourcesFromSearchResults(clusterResults, pulseSearchClusterMaxSources),
		)) > 0 {
			continue
		}
		for _, result := range clusterResults {
			if key := pulseSearchResultDedupeKey(result); key != "" {
				seenResultKeys[key] = true
			}
		}
		if perModuleCount[module] >= searchFallbackItemLimit(module) {
			continue
		}
		clusterEvidence := queryEvidence
		clusterEvidence.Results = clusterResults
		candidate := searchFallbackClusterItem(date, clusterEvidence, perModuleCount[module])
		if !pulseNewsCopyMeetsQualityGate(candidate.Title, candidate.Summary) ||
			len([]rune(candidate.Summary)) < pulseSummaryMinRunes {
			continue
		}
		candidates = append(candidates, candidate)
		perModuleCount[module]++
	}
	if len(candidates) == 0 {
		// Search did run and returned evidence, so keep the retrieval-aware module
		// copy instead of incorrectly telling the user that external search was
		// unavailable. An empty item list now means no cluster passed verification.
		return modules, []models.PulseItem{}
	}
	items := diversifyPulseItems(
		rankPulseItems(candidates, pulseFeatureState{}),
		pulseCandidateTargetCount,
	)
	sortPulseModules(modules)
	return modules, items
}

func pulseVerifiedSearchClusters(date string, evidence []pulseSearchEvidence) []pulseSearchEvidence {
	type evidenceGroup struct {
		Evidence pulseSearchEvidence
		Seen     map[string]bool
	}
	groups := []evidenceGroup{}
	groupIndexes := map[string]int{}
	for _, item := range evidence {
		module := normalizePulseModuleKey(item.Module)
		if module == "" {
			continue
		}
		topicKey := firstNonEmptyPulse(item.TopicID, strings.ToLower(strings.TrimSpace(item.TopicName)), "general")
		keywordKey := firstNonEmptyPulse(strings.ToLower(strings.TrimSpace(item.Keyword)), "general")
		groupKey := module + ":" + topicKey + ":" + keywordKey
		index, ok := groupIndexes[groupKey]
		if !ok {
			index = len(groups)
			groupIndexes[groupKey] = index
			groups = append(groups, evidenceGroup{
				Evidence: pulseSearchEvidence{
					QueryID:   "cluster:" + groupKey,
					Stage:     "cluster",
					Module:    module,
					Query:     firstNonEmptyPulse(item.Query, item.TopicName, moduleCategory(module)),
					Intent:    "跨查询合并并完成同一事件取证",
					Keyword:   item.Keyword,
					TopicID:   item.TopicID,
					TopicName: item.TopicName,
				},
				Seen: map[string]bool{},
			})
		}
		for _, result := range item.Results {
			key := pulseSearchResultDedupeKey(result)
			if key == "" || groups[index].Seen[key] {
				continue
			}
			groups[index].Seen[key] = true
			groups[index].Evidence.Results = append(groups[index].Evidence.Results, result)
		}
	}

	verified := []pulseSearchEvidence{}
	seenClusters := map[string]bool{}
	claimedGroups := map[string]bool{}
	seenResults := map[string]bool{}
	for _, group := range groups {
		for _, results := range pulseCorroboratedSearchClusters(group.Evidence, group.Evidence.Results) {
			sources := newsSourcesFromSearchResults(results, pulseSearchClusterMaxSources)
			if !pulseNewsSourcesMeetQualityGate(date, group.Evidence.Module, sources) {
				continue
			}
			keys := []string{}
			for _, result := range results {
				keys = append(keys, pulseSearchResultDedupeKey(result))
			}
			sort.Strings(keys)
			clusterKey := strings.Join(keys, "|")
			if clusterKey == "" || seenClusters[clusterKey] {
				continue
			}
			seenClusters[clusterKey] = true
			groupKey := normalizePulseModuleKey(group.Evidence.Module) + ":" +
				firstNonEmptyPulse(group.Evidence.TopicID, strings.ToLower(strings.TrimSpace(group.Evidence.TopicName)), "general") + ":" +
				firstNonEmptyPulse(strings.ToLower(strings.TrimSpace(group.Evidence.Keyword)), "general")
			claimedGroups[groupKey] = true
			for _, result := range results {
				if key := pulseSearchResultDedupeKey(result); key != "" {
					seenResults[key] = true
				}
			}
			cluster := group.Evidence
			cluster.QueryID = fmt.Sprintf("%s:%d", group.Evidence.QueryID, len(verified)+1)
			cluster.Query = strings.Join(pulseSearchEventAnchorTerms(results[0]), " ")
			cluster.Results = results
			verified = append(verified, cluster)
			if len(verified) >= pulseCandidateMaxCount {
				return verified
			}
		}
	}

	// A second search enriches a card but does not decide whether it exists.
	// Keep one concrete, recent first-stage result per keyword when it already
	// comes from an official or authoritative publication. Ordinary publishers
	// still need the multi-source path above.
	for _, item := range evidence {
		if strings.EqualFold(strings.TrimSpace(item.Stage), "followup") {
			continue
		}
		module := normalizePulseModuleKey(item.Module)
		if module == "" {
			continue
		}
		topicKey := firstNonEmptyPulse(item.TopicID, strings.ToLower(strings.TrimSpace(item.TopicName)), "general")
		keywordKey := firstNonEmptyPulse(strings.ToLower(strings.TrimSpace(item.Keyword)), "general")
		groupKey := module + ":" + topicKey + ":" + keywordKey
		if claimedGroups[groupKey] {
			continue
		}
		query := pulseSearchQueryFromEvidence(item)
		for _, result := range pulseRankSearchResults(query, item.Results, pulseSearchClusterCandidateLimit) {
			resultKey := pulseSearchResultDedupeKey(result)
			if resultKey == "" || seenResults[resultKey] ||
				pulseSearchResultRelevanceScore(query, result) <= 0 ||
				!pulseTrustedSingletonMeetsQualityGate(date, module, result) {
				continue
			}
			cluster := item
			cluster.QueryID = fmt.Sprintf("cluster-single:%s:%d", groupKey, len(verified)+1)
			cluster.Stage = "cluster"
			cluster.ParentQueryID = item.QueryID
			cluster.Intent = "首轮可信事件；二次检索仅用于内容扩展"
			cluster.Results = []pulseSearchResult{result}
			verified = append(verified, cluster)
			claimedGroups[groupKey] = true
			seenResults[resultKey] = true
			break
		}
		if len(verified) >= pulseCandidateMaxCount {
			return verified
		}
	}

	// If there is no single event worth promoting, keep a keyword-level digest
	// from the two first-stage query variants. This mirrors a direct search-tool
	// summary: it describes the converging developments for the keyword instead
	// of pretending that every source reports the exact same event.
	for _, group := range groups {
		module := normalizePulseModuleKey(group.Evidence.Module)
		topicKey := firstNonEmptyPulse(group.Evidence.TopicID, strings.ToLower(strings.TrimSpace(group.Evidence.TopicName)), "general")
		keywordKey := firstNonEmptyPulse(strings.ToLower(strings.TrimSpace(group.Evidence.Keyword)), "general")
		groupKey := module + ":" + topicKey + ":" + keywordKey
		if claimedGroups[groupKey] {
			continue
		}
		results := pulseKeywordDigestResults(date, group.Evidence, group.Evidence.Results)
		if !pulseKeywordDigestSourcesMeetQualityGate(
			date,
			module,
			newsSourcesFromSearchResults(results, pulseSearchClusterMaxSources),
		) {
			continue
		}
		cluster := group.Evidence
		cluster.QueryID = fmt.Sprintf("cluster-digest:%s:%d", groupKey, len(verified)+1)
		cluster.Stage = "cluster"
		cluster.Query = firstNonEmptyPulse(group.Evidence.Keyword, group.Evidence.Query)
		cluster.Intent = "keyword_digest"
		cluster.Results = results
		verified = append(verified, cluster)
		claimedGroups[groupKey] = true
		if len(verified) >= pulseCandidateMaxCount {
			return verified
		}
	}
	return verified
}

func pulseKeywordDigestResults(date string, evidence pulseSearchEvidence, results []pulseSearchResult) []pulseSearchResult {
	query := pulseSearchQueryFromEvidence(evidence)
	ranked := pulseRankSearchResults(query, results, pulseSearchClusterCandidateLimit)
	selected := []pulseSearchResult{}
	for _, result := range ranked {
		if !pulseSafeHTTPURL(result.URL) ||
			pulseSearchResultHasStaleDate(date, evidence.Module, result) ||
			pulseSearchResultLooksThinHomepage(result) ||
			pulseSearchResultRelevanceScore(query, result) <= 0 ||
			!pulseClusterAddsIndependentSource(selected, result) {
			continue
		}
		selected = append(selected, result)
		if len(selected) >= pulseSearchClusterMaxSources {
			break
		}
	}
	return selected
}

func searchFallbackModuleCopy(key string, resultCount int, searchErrors []string) (string, string) {
	if resultCount == 0 {
		if len(searchErrors) > 0 {
			return defaultPulseModuleCopy(key)
		}
		return defaultPulseModuleCopy(key)
	}
	switch key {
	case pulseSourceTopicHot:
		return "订阅 Topic 的外网新动向", fmt.Sprintf("已处理 %d 条与订阅 topic 相关的外网线索；首轮可信事件可直接成卡，二搜用于补充内容。", resultCount)
	case pulseSourceMemory:
		return "近日 Memory 的外网延伸", fmt.Sprintf("结合近期 memory 处理了 %d 条外网线索；首轮可信事件可直接成卡，二搜用于补充内容。", resultCount)
	case pulseSourceInterestHot:
		return "可能感兴趣的外网热门", fmt.Sprintf("从 topic 与 memory 外扩检索处理了 %d 条候选线索；二搜只扩展已发现事件。", resultCount)
	default:
		return "外网检索推荐", fmt.Sprintf("基于 %d 条外网检索结果生成；二搜仅用于内容扩展。", resultCount)
	}
}

func searchFallbackItemLimit(module string) int {
	switch module {
	case pulseSourceTopicHot:
		return 12
	case pulseSourceMemory:
		return 8
	case pulseSourceInterestHot:
		return 10
	default:
		return 8
	}
}

func pulseSearchFallbackClusters(queryEvidence pulseSearchEvidence) [][]pulseSearchResult {
	results := queryEvidence.Results
	usable := results[:minInt(len(results), pulseSearchExpandedResultLimit)]
	if len(usable) == 0 {
		return nil
	}
	return pulseCorroboratedSearchClusters(queryEvidence, usable)
}

func pulseCorroboratedSearchClusters(queryEvidence pulseSearchEvidence, results []pulseSearchResult) [][]pulseSearchResult {
	results = pulseRankSearchResults(pulseSearchQueryFromEvidence(queryEvidence), results, pulseSearchClusterCandidateLimit)
	type candidateCluster struct {
		Results []pulseSearchResult
		Score   int
		Index   int
	}
	candidates := []candidateCluster{}
	for index, seed := range results {
		cluster := []pulseSearchResult{seed}
		for otherIndex, candidate := range results {
			if otherIndex == index {
				continue
			}
			if len(cluster) >= pulseSearchClusterMaxSources {
				break
			}
			corroboratesCluster := true
			for _, existing := range cluster {
				if !pulseSearchResultsCorroborate(queryEvidence, existing, candidate) {
					corroboratesCluster = false
					break
				}
			}
			if !corroboratesCluster {
				continue
			}
			if !pulseClusterAddsIndependentSource(cluster, candidate) {
				continue
			}
			cluster = append(cluster, candidate)
		}
		if !pulseSearchClusterHasTrustSignal(cluster) {
			continue
		}
		candidates = append(candidates, candidateCluster{
			Results: cluster,
			Score:   pulseSearchClusterScore(queryEvidence, cluster),
			Index:   index,
		})
	}
	sort.SliceStable(candidates, func(i, j int) bool {
		if candidates[i].Score == candidates[j].Score {
			return candidates[i].Index < candidates[j].Index
		}
		return candidates[i].Score > candidates[j].Score
	})

	clusters := [][]pulseSearchResult{}
	used := map[string]bool{}
	for _, candidate := range candidates {
		cluster := []pulseSearchResult{}
		for _, result := range candidate.Results {
			key := pulseSearchResultDedupeKey(result)
			if key != "" && used[key] {
				continue
			}
			cluster = append(cluster, result)
		}
		if !pulseSearchClusterHasTrustSignal(cluster) {
			continue
		}
		for _, result := range cluster {
			if key := pulseSearchResultDedupeKey(result); key != "" {
				used[key] = true
			}
		}
		clusters = append(clusters, cluster)
	}
	return clusters
}

func pulseSearchClusterScore(queryEvidence pulseSearchEvidence, results []pulseSearchResult) int {
	score := pulseSearchIndependentSourceCount(results) * 30
	score += len(results) * 8
	if !pulseAllWeakSearchSources(results) {
		score += 20
	}
	query := pulseSearchQueryFromEvidence(queryEvidence)
	for _, result := range results {
		score += pulseSearchResultRelevanceScore(query, result)
	}
	return score
}

func pulseSearchClusterHasTrustSignal(results []pulseSearchResult) bool {
	if pulseSearchIndependentSourceCount(results) < 2 {
		return false
	}
	if pulseSearchClusterHasTrustedSource(results) {
		return true
	}
	// A precise event is sometimes indexed by several specialist publications
	// before the vendor page or a major newsroom appears in search. Permit that
	// path only with stronger consensus than the normal two-source rule: three
	// independent, non-weak domains and dates on at least two of them. The later
	// freshness and same-event gates still apply to the complete cluster.
	if pulseSearchIndependentSourceCount(results) < 3 || pulseAllWeakSearchSources(results) {
		return false
	}
	datedDomains := map[string]bool{}
	for _, result := range results {
		if _, ok := pulseSearchResultPublishedAt(result); !ok {
			continue
		}
		if domain := pulseSourceDomainKey(result.URL); domain != "" {
			datedDomains[domain] = true
		}
	}
	return len(datedDomains) >= 2
}

func pulseSearchClusterHasTrustedSource(results []pulseSearchResult) bool {
	for _, result := range results {
		if pulsePrimarySearchSource(result) || pulseAuthoritativeSearchSource(result) {
			return true
		}
	}
	return false
}

func pulseTrustedSingletonCopyReady(result pulseSearchResult) bool {
	title := cleanSearchText(result.Title)
	combined := cleanSearchText(strings.Join([]string{result.Title, result.Snippet}, " "))
	return pulseSafeHTTPURL(result.URL) &&
		(pulsePrimarySearchSource(result) || pulseAuthoritativeSearchSource(result)) &&
		!pulseWeakSearchSource(result) &&
		!pulseSearchResultLooksThinHomepage(result) &&
		!pulseSearchResultLooksEditorialOverview(result) &&
		!pulseNewsCopyLooksGeneric(title) &&
		pulseCopyContainsConcreteEvent(title) &&
		pulseCopyHasIdentifiableSubject(title) &&
		len(pulseConcreteEventFamilies(result)) > 0 &&
		len([]rune(combined)) >= 60
}

func pulseTrustedSingletonMeetsQualityGate(date string, module string, result pulseSearchResult) bool {
	if !pulseTrustedSingletonCopyReady(result) {
		return false
	}
	reference, err := time.Parse("2006-01-02", date)
	if err != nil {
		return false
	}
	publishedAt, ok := pulseSearchResultPublishedAt(result)
	if !ok {
		return false
	}
	return !publishedAt.Before(reference.Add(-pulseFreshnessWindow(module))) &&
		!publishedAt.After(reference.Add(pulseFutureDateTolerance))
}

func pulseClusterAddsIndependentSource(cluster []pulseSearchResult, candidate pulseSearchResult) bool {
	candidateDomain := pulseSourceDomainKey(candidate.URL)
	if candidateDomain == "" {
		return false
	}
	for _, result := range cluster {
		if pulseSourceDomainKey(result.URL) == candidateDomain ||
			pulseSearchResultsShareSyndicatedTitle(result, candidate) {
			return false
		}
	}
	return true
}

func pulseSearchIndependentSourceCount(results []pulseSearchResult) int {
	seenDomains := map[string]bool{}
	seenTitles := map[string]bool{}
	count := 0
	for _, result := range results {
		domain := pulseSourceDomainKey(result.URL)
		if domain == "" || seenDomains[domain] {
			continue
		}
		title := pulseSyndicatedTitleKey(result.Title)
		if title != "" && seenTitles[title] {
			continue
		}
		seenDomains[domain] = true
		if title != "" {
			seenTitles[title] = true
		}
		count++
	}
	return count
}

// Different domains are not automatically independent publications. Chinese
// news aggregators frequently republish the same wire copy verbatim, including
// its headline. Treat a sufficiently specific identical headline as one
// publication so a syndicated story cannot satisfy the corroboration gate.
func pulseSearchResultsShareSyndicatedTitle(left pulseSearchResult, right pulseSearchResult) bool {
	leftTitle := pulseSyndicatedTitleKey(left.Title)
	rightTitle := pulseSyndicatedTitleKey(right.Title)
	return leftTitle != "" && leftTitle == rightTitle
}

func pulseSyndicatedTitleKey(value string) string {
	cleaned := cleanSearchText(value)
	if len([]rune(cleaned)) < 10 {
		return ""
	}
	return strings.ReplaceAll(pulseClusterTitleKey(cleaned), " ", "")
}

func pulseFilterNewSearchFallbackResults(results []pulseSearchResult, seen map[string]bool) []pulseSearchResult {
	filtered := make([]pulseSearchResult, 0, len(results))
	for _, result := range results {
		key := pulseSearchResultDedupeKey(result)
		if key != "" {
			if seen[key] {
				continue
			}
		}
		filtered = append(filtered, result)
	}
	return filtered
}

func pulseSearchResultDedupeKey(result pulseSearchResult) string {
	rawURL := strings.TrimSpace(result.URL)
	if rawURL != "" {
		if parsed, err := url.Parse(rawURL); err == nil && parsed.Hostname() != "" {
			host := strings.TrimPrefix(strings.ToLower(parsed.Hostname()), "www.")
			path := strings.TrimRight(parsed.EscapedPath(), "/")
			if path != "" {
				return host + path
			}
			return host
		}
		return strings.ToLower(rawURL)
	}
	title := strings.ToLower(strings.Join(strings.Fields(result.Title), " "))
	snippet := strings.ToLower(strings.Join(strings.Fields(result.Snippet), " "))
	return strings.TrimSpace(title + " " + snippet)
}

func searchFallbackClusterRecommendationReason(queryEvidence pulseSearchEvidence, results []pulseSearchResult, module string) string {
	focus := firstNonEmptyPulse(queryEvidence.TopicName, queryEvidence.Intent, moduleCategory(module))
	if len(results) == 1 {
		return pulseCompactRecommendationReason(fmt.Sprintf("「%s」下的一条外网线索。", focus))
	}
	switch module {
	case pulseSourceMemory:
		return pulseCompactRecommendationReason(fmt.Sprintf("延续你近期关注的「%s」。", focus))
	case pulseSourceInterestHot:
		return pulseCompactRecommendationReason(fmt.Sprintf("由你的关注方向「%s」延伸。", focus))
	default:
		return pulseCompactRecommendationReason(fmt.Sprintf("与你订阅的「%s」直接相关。", focus))
	}
}

func searchFallbackClusterItem(date string, queryEvidence pulseSearchEvidence, moduleIndex int) models.PulseItem {
	now := time.Now()
	module := normalizePulseModuleKey(queryEvidence.Module)
	results := queryEvidence.Results[:minInt(len(queryEvidence.Results), pulseSearchResultLimit)]
	sources := newsSourcesFromSearchResults(results, 5)
	title := searchFallbackClusterTitle(module, queryEvidence, results)
	summary := pulseCompactSummary(searchFallbackClusterSummary(queryEvidence, results))
	reason := searchFallbackClusterRecommendationReason(queryEvidence, results, module)
	questionContext := pulseQuestionContext{
		Title:     title,
		Summary:   summary,
		Module:    module,
		TopicName: queryEvidence.TopicName,
		Query:     queryEvidence.Query,
		Intent:    queryEvidence.Intent,
		Category:  moduleCategory(module),
		KeyPoints: searchFallbackClusterKeyPoints(queryEvidence, results),
		Context:   searchFallbackClusterContext(queryEvidence, results),
		Sources:   sources,
	}
	detail := pulseItemDetail{
		ContentVersion:       pulseContentVersion,
		EvidenceMode:         queryEvidence.Intent,
		RecommendationReason: reason,
		Signals:              []string{},
		QuickContext:         questionContext.Context,
		KeyPoints:            questionContext.KeyPoints,
		NewsSources:          sources,
		SuggestedQuestions:   personalizedPulseSuggestedQuestions(nil, questionContext),
		PrecomputedAt:        now.UTC().Format(time.RFC3339),
	}
	evidenceScore := pulseSearchClusterScore(queryEvidence, results)
	heatScore := maxInt(55, minInt(92, 35+evidenceScore/2))
	return models.PulseItem{
		ID:            pulseItemID(date, module, fmt.Sprintf("%s:%s:%d", queryEvidence.Query, results[0].URL, moduleIndex)),
		Date:          date,
		TopicID:       queryEvidence.TopicID,
		TopicName:     queryEvidence.TopicName,
		Source:        module,
		Category:      moduleCategory(module),
		Title:         limitText(title, 120),
		Summary:       summary,
		HeatScore:     normalizeHeatScore(heatScore, module, moduleIndex),
		DetailJSON:    mustJSON(detail),
		ExplorePrompt: limitText(fmt.Sprintf("请基于这些新闻来源聚合展开并核验「%s」：\n%s\n\n请总结最新信息、可信度、为什么推荐给我，以及我下一步该追问什么。", title, newsSourcePromptLines(sources)), 900),
		CreatedAt:     now,
		UpdatedAt:     now,
	}
}

func searchFallbackClusterTitle(module string, queryEvidence pulseSearchEvidence, results []pulseSearchResult) string {
	trustedSingleton := len(results) == 1 && pulseTrustedSingletonCopyReady(results[0])
	if !trustedSingleton && (len(results) < 2 || !pulseSearchClusterHasTrustSignal(results) ||
		!pulseSearchClusterDescribesConcreteEvent(results)) {
		return ""
	}
	if headline := searchFallbackClusterPreferredHeadline(results); headline != "" {
		return limitText(headline, 120)
	}
	subject := searchFallbackClusterSubject(queryEvidence, results)
	change := searchFallbackClusterTitleChange(results)
	if subject == "" || change == "" {
		return ""
	}
	return limitText(fmt.Sprintf("%s%s", subject, change), 120)
}

func searchFallbackClusterSummary(queryEvidence pulseSearchEvidence, results []pulseSearchResult) string {
	trustedSingleton := len(results) == 1 && pulseTrustedSingletonCopyReady(results[0])
	if !trustedSingleton && (len(results) < 2 || !pulseSearchClusterHasTrustSignal(results) || !pulseSearchClusterDescribesConcreteEvent(results)) {
		return ""
	}
	if trustedSingleton {
		return searchFallbackTrustedSingletonSummary(results[0])
	}
	subject := searchFallbackClusterSubject(queryEvidence, results)
	if subject == "" {
		return ""
	}
	change := searchFallbackClusterSummaryChange(results)
	if change == "" {
		return ""
	}
	aspects := searchFallbackClusterAspects(results)
	aspectText := strings.Join(aspects[:minInt(len(aspects), 3)], "、")
	eventLabel := searchFallbackClusterEventLabel(results)
	trustedLabel := "权威媒体"
	for _, result := range results {
		if pulsePrimarySearchSource(result) {
			trustedLabel = "官方或一手材料"
			break
		}
	}
	lead := fmt.Sprintf("%s%s", subject, change)
	if headline := searchFallbackClusterPreferredHeadline(results); headline != "" {
		lead = strings.TrimRight(headline, "。！？!? ")
	}
	summary := fmt.Sprintf(
		"%s。现有来源对这项%s的共同信息集中在%s，至少两个独立发布机构给出了能够相互印证的时间、产品或版本线索。%s提供了事件主体和发布内容，其他独立报道补充了开放范围、能力变化或相关背景。综合各来源后，当前可以确认的是它们描述的是同一项具体更新；尚未得到交叉支持的参数、数字和推测不纳入这份综述。",
		lead,
		eventLabel,
		aspectText,
		trustedLabel,
	)
	return pulseCompactSummary(summary)
}

func searchFallbackClusterPreferredHeadline(results []pulseSearchResult) string {
	type candidate struct {
		Title string
		Score int
		Index int
	}
	candidates := []candidate{}
	for index, result := range results {
		title := cleanSearchText(result.Title)
		if title == "" || !pulseTermHasHan(title) ||
			pulseSearchResultLooksEditorialOverview(result) ||
			pulseNewsCopyLooksGeneric(title) ||
			!pulseCopyContainsConcreteEvent(title) ||
			!pulseCopyHasIdentifiableSubject(title) {
			continue
		}
		score := 10
		if pulsePrimarySearchSource(result) {
			score += 30
		} else if pulseAuthoritativeSearchSource(result) {
			score += 20
		} else if !pulseWeakSearchSource(result) {
			score += 8
		}
		if _, ok := pulseSearchResultPublishedAt(result); ok {
			score += 3
		}
		candidates = append(candidates, candidate{Title: title, Score: score, Index: index})
	}
	if len(candidates) == 0 {
		return ""
	}
	sort.SliceStable(candidates, func(i, j int) bool {
		if candidates[i].Score == candidates[j].Score {
			return candidates[i].Index < candidates[j].Index
		}
		return candidates[i].Score > candidates[j].Score
	})
	return candidates[0].Title
}

func searchFallbackTrustedSingletonSummary(result pulseSearchResult) string {
	headline := strings.TrimRight(cleanSearchText(result.Title), "。！？!? ")
	snippet := cleanSearchText(result.Snippet)
	if headline == "" || snippet == "" {
		return ""
	}
	summary := headline + "。"
	if !strings.Contains(strings.ToLower(headline), strings.ToLower(snippet)) {
		summary += snippet
	}
	summary = pulseCompactSummary(summary)
	if len([]rune(summary)) < pulseSummaryMinRunes {
		return ""
	}
	return summary
}

func searchFallbackClusterSubject(queryEvidence pulseSearchEvidence, results []pulseSearchResult) string {
	entities := searchFallbackClusterEntities(queryEvidence, results)
	for _, entity := range entities {
		if pulseCorroborationTermLooksDistinctive(entity) || pulseCorroborationTermLooksEntityOnly(entity) {
			return entity
		}
	}
	for _, entity := range entities {
		if !pulseConcreteEventIdentityTermLooksBroad(entity) {
			return entity
		}
	}
	return ""
}

func searchFallbackClusterEventLabel(results []pulseSearchResult) string {
	shared := map[string]bool{}
	for index, result := range results {
		families := pulseConcreteEventFamilies(result)
		if index == 0 {
			for family := range families {
				shared[family] = true
			}
			continue
		}
		for family := range shared {
			if !families[family] {
				delete(shared, family)
			}
		}
	}
	labels := []struct{ family, label string }{
		{"acquisition", "收购事件"}, {"funding", "融资事件"}, {"partnership", "合作事件"},
		{"policy", "政策变化"}, {"legal", "法律事件"}, {"research", "研究发布"},
		{"incident", "安全或服务事件"}, {"financial_results", "财务更新"},
		{"personnel", "人事变化"}, {"product_change", "产品更新"}, {"public_statement", "公开发布"},
	}
	for _, item := range labels {
		if shared[item.family] {
			return item.label
		}
	}
	return "新闻事件"
}

func searchFallbackClusterContext(queryEvidence pulseSearchEvidence, results []pulseSearchResult) string {
	if len(results) == 0 {
		return ""
	}
	if len(results) == 1 && pulseTrustedSingletonCopyReady(results[0]) {
		return pulseCompactRecommendationReason("首轮命中近期可信发布，二次检索仅用于补充来源和背景。")
	}
	datedSources := 0
	for _, result := range results {
		if strings.TrimSpace(result.PublishedAt) != "" {
			datedSources++
		}
	}
	return pulseCompactRecommendationReason(
		fmt.Sprintf("%d 个独立来源互证，%d 个来源带发布时间。", pulseSearchIndependentSourceCount(results), datedSources),
	)
}

func searchFallbackClusterKeyPoints(queryEvidence pulseSearchEvidence, results []pulseSearchResult) []string {
	return pulseCompactKeyPoints(searchFallbackClusterAspects(results))
}

func searchFallbackClusterFocus(module string, queryEvidence pulseSearchEvidence, results []pulseSearchResult) string {
	topic := cleanSearchText(queryEvidence.TopicName)
	clusterText := strings.ToLower(searchFallbackClusterText(queryEvidence, results))
	if strings.EqualFold(topic, "ai") && pulseClusterMentionsModel(clusterText) {
		return "AI 模型进展"
	}
	if topic != "" {
		return topic
	}
	switch module {
	case pulseSourceMemory:
		return "近日关注延伸"
	case pulseSourceInterestHot:
		return "可能兴趣方向"
	default:
		return "订阅 Topic"
	}
}

func searchFallbackClusterEntities(queryEvidence pulseSearchEvidence, results []pulseSearchResult) []string {
	shared := searchFallbackSharedClusterEntities(results)
	if len(shared) > 0 {
		return shared
	}
	text := searchFallbackClusterText(queryEvidence, results)
	entities := []string{}
	for _, match := range pulseModelEntityPattern.FindAllString(text, -1) {
		entities = appendPulseEntity(entities, normalizePulseEntity(match))
	}
	for _, entity := range pulseKnownEntities {
		if pulseTextContainsFold(text, entity) {
			entities = appendPulseEntity(entities, entity)
		}
	}
	return limitStringSlice(entities, 5, 40)
}

func searchFallbackSharedClusterEntities(results []pulseSearchResult) []string {
	type termStat struct {
		Term    string
		Domains []string
	}
	stats := map[string]termStat{}
	for _, result := range results {
		domain := pulseSourceDomainKey(result.URL)
		if domain == "" {
			continue
		}
		if pulseSearchResultLooksThinHomepage(result) {
			continue
		}
		for _, term := range pulseCorroborationTerms(result) {
			normalized := strings.ToLower(strings.TrimSpace(term))
			if normalized == "" || pulseCorroborationTermLooksGeneric(normalized) {
				continue
			}
			stat := stats[normalized]
			if stat.Term == "" {
				stat.Term = normalizePulseEntity(term)
			}
			stat.Domains = appendUniqueStrings(stat.Domains, domain)
			stats[normalized] = stat
		}
	}
	shared := make([]termStat, 0, len(stats))
	for _, stat := range stats {
		if len(stat.Domains) >= 2 {
			shared = append(shared, stat)
		}
	}
	sort.SliceStable(shared, func(i, j int) bool {
		leftDistinctive := pulseCorroborationTermLooksDistinctive(shared[i].Term)
		rightDistinctive := pulseCorroborationTermLooksDistinctive(shared[j].Term)
		if leftDistinctive != rightDistinctive {
			return leftDistinctive
		}
		leftStrong := pulseCorroborationTermLooksStrong(shared[i].Term)
		rightStrong := pulseCorroborationTermLooksStrong(shared[j].Term)
		if leftStrong != rightStrong {
			return leftStrong
		}
		if len(shared[i].Domains) == len(shared[j].Domains) {
			leftLength := len([]rune(shared[i].Term))
			rightLength := len([]rune(shared[j].Term))
			if leftLength == rightLength {
				return strings.ToLower(shared[i].Term) < strings.ToLower(shared[j].Term)
			}
			return leftLength > rightLength
		}
		return len(shared[i].Domains) > len(shared[j].Domains)
	})
	entities := []string{}
	for _, stat := range shared {
		entities = appendPulseEntity(entities, stat.Term)
		if len(entities) >= 5 {
			break
		}
	}
	return entities
}

func pulseSearchResultLooksThinHomepage(result pulseSearchResult) bool {
	parsed, err := url.Parse(strings.TrimSpace(result.URL))
	if err != nil || parsed.Hostname() == "" {
		return false
	}
	path := strings.Trim(strings.TrimSpace(parsed.EscapedPath()), "/")
	if path != "" {
		return false
	}
	snippet := cleanSearchText(result.Snippet)
	return len([]rune(snippet)) < 80
}

func pulseSearchResultsCorroborate(queryEvidence pulseSearchEvidence, left pulseSearchResult, right pulseSearchResult) bool {
	if !pulseSearchResultsShareConcreteEvent(left, right) {
		return false
	}
	leftTerms := pulseCorroborationTerms(left)
	rightTerms := pulseCorroborationTerms(right)
	overlap := intersectPulseTerms(leftTerms, rightTerms)
	if len(overlap) < 2 {
		return false
	}
	queryTerms := pulseSearchRelevanceTerms(pulseSearchQueryFromEvidence(queryEvidence))
	subjectTerms := pulseCorroborationSubjectTermSet(queryEvidence)
	hasEventTerm := false
	eventTermCount := 0
	hasDistinctiveEventTerm := false
	hasStrongTerm := false
	for _, term := range overlap {
		if pulseCorroborationTermLooksStrong(term) {
			hasStrongTerm = true
		}
		if !pulseCorroborationTermLooksEntityOnly(term) &&
			!subjectTerms[strings.ToLower(strings.TrimSpace(term))] {
			hasEventTerm = true
			eventTermCount++
			if pulseCorroborationTermLooksDistinctive(term) {
				hasDistinctiveEventTerm = true
			}
		}
	}
	if !hasEventTerm || (eventTermCount < 2 && !hasDistinctiveEventTerm) {
		return false
	}
	if hasStrongTerm {
		return true
	}
	return len(intersectPulseTerms(overlap, queryTerms)) > 0
}

func pulseSearchClusterDescribesConcreteEvent(results []pulseSearchResult) bool {
	if len(results) < 2 {
		return false
	}
	for leftIndex, left := range results {
		for _, right := range results[leftIndex+1:] {
			if !pulseSearchResultsShareConcreteEvent(left, right) {
				return false
			}
		}
	}
	return true
}

func pulseSearchResultsShareConcreteEvent(left pulseSearchResult, right pulseSearchResult) bool {
	if !pulseResultsHaveIndependentDomains(left, right) {
		return false
	}
	if pulseSearchResultLooksEditorialOverview(left) && pulseSearchResultLooksEditorialOverview(right) {
		return false
	}

	leftFamilies := pulseConcreteEventFamilies(left)
	rightFamilies := pulseConcreteEventFamilies(right)
	sharesEventFamily := false
	for family := range leftFamilies {
		if rightFamilies[family] {
			sharesEventFamily = true
			break
		}
	}
	if !sharesEventFamily {
		return false
	}

	for _, term := range intersectPulseTerms(pulseCorroborationTerms(left), pulseCorroborationTerms(right)) {
		if !pulseConcreteEventIdentityTermLooksBroad(term) {
			return true
		}
	}
	return false
}

func pulseSearchResultLooksEditorialOverview(result pulseSearchResult) bool {
	title := strings.ToLower(cleanSearchText(result.Title))
	return pulseTextHasAny(
		title,
		"trend", "trends", "analysis", "deep dive", "overview", "guide", "tutorial",
		"forecast", "prediction", "future of", "revolution", "new era", "landscape", "state of",
		"briefing", "daily brief", "daily digest", "weekly digest", "roundup", "latest news",
		"趋势", "分析", "深度", "综述", "全景", "展望", "预测", "革命", "新时代", "指南", "教程", "盘点", "日报", "周报",
	)
}

func pulseConcreteEventFamilies(result pulseSearchResult) map[string]bool {
	text := strings.ToLower(cleanSearchText(strings.Join([]string{result.Title, result.Snippet}, " ")))
	families := map[string]bool{}
	add := func(family string, markers ...string) {
		if pulseTextHasAny(text, markers...) {
			families[family] = true
		}
	}
	add(
		"product_change",
		"release", "launch", "unveil", "roll out", "rollout", " shipped ", " shipping ", "debut", "introduc",
		"available now", "general availability", "generally available", " to ga", " ga ", "out of beta",
		"production-ready", "production ready", "opens access", "open source", "open-source", "adds ", "added ",
		"发布", "推出", "上线", "开放", "开源", "正式亮相", "正式 ga", "正式可用", "新增", "升级",
	)
	add("acquisition", "acquir", "merger", "buys ", "bought ", "收购", "并购", "合并")
	add("funding", "funding", "raises ", "raised ", "investment round", "融资", "募资")
	add("personnel", "appoint", "hire", "resign", "steps down", "named as", "任命", "出任", "离职", "辞职")
	add("partnership", "partner", "collaborat", "joint venture", "合作", "签署协议", "达成协议")
	add("policy", "regulation", "regulator", "approved", "approval", "law ", "bill ", "ban ", "政策", "法规", "法案", "获批", "批准", "监管", "禁令")
	add("legal", "lawsuit", "sues ", "sued ", "court ", "fine ", "起诉", "诉讼", "判决", "罚款")
	add("research", "study finds", "researchers found", "benchmark shows", "paper published", "report finds", "survey finds", "研究发现", "报告发布", "公布报告", "调查显示", "评测显示")
	add("incident", "outage", "breach", "vulnerability", "exploit", "shutdown", "宕机", "故障", "漏洞", "遭攻击", "数据泄露", "停服")
	add("financial_results", "earnings", "revenue ", "profit ", "quarterly results", "财报", "营收", "利润", "季度业绩")
	add("public_statement", "keynote", "summit", "conference", "said at", "峰会", "大会", "演讲")
	return families
}

func pulseConcreteEventIdentityTermLooksBroad(term string) bool {
	normalized := strings.ToLower(strings.TrimSpace(term))
	if normalized == "" ||
		pulseCorroborationTermLooksGeneric(normalized) ||
		pulseCorroborationTermLooksEntityOnly(term) {
		return true
	}
	broadTerms := []string{
		"ai", "aigc", "agent", "agents", "llm", "rag", "development", "workflow", "workflows",
		"人工智能", "智能体", "大模型", "行业", "市场", "趋势", "时代",
	}
	for _, broad := range broadTerms {
		if normalized == broad {
			return true
		}
	}
	return false
}

func pulseCorroborationTermLooksEntityOnly(term string) bool {
	normalized := strings.TrimSpace(term)
	if normalized == "" {
		return false
	}
	for _, entity := range pulseKnownEntities {
		if strings.EqualFold(normalized, entity) {
			return true
		}
	}
	return pulseModelEntityPattern.MatchString(normalized)
}

func pulseCorroborationSubjectTermSet(evidence pulseSearchEvidence) map[string]bool {
	subjects := map[string]bool{}
	add := func(term string) {
		normalized := strings.ToLower(strings.TrimSpace(term))
		if normalized != "" {
			subjects[normalized] = true
		}
	}
	for _, term := range pulseKeywordsFromText(evidence.TopicName) {
		add(term)
	}
	queryTerms := pulseSearchRelevanceTerms(pulseSearchQueryFromEvidence(evidence))
	if len(queryTerms) > 0 {
		add(queryTerms[0])
	}
	for _, term := range pulseCapitalizedTermPattern.FindAllString(evidence.Query, -1) {
		add(term)
	}
	return subjects
}

func pulseCorroborationTermLooksDistinctive(term string) bool {
	normalized := strings.TrimSpace(term)
	if len([]rune(normalized)) < 5 {
		return false
	}
	return strings.ContainsAny(normalized, "0123456789-")
}

func pulseResultsHaveIndependentDomains(left pulseSearchResult, right pulseSearchResult) bool {
	leftDomain := pulseSourceDomainKey(left.URL)
	rightDomain := pulseSourceDomainKey(right.URL)
	return leftDomain != "" && rightDomain != "" && leftDomain != rightDomain &&
		!pulseSearchResultsShareSyndicatedTitle(left, right)
}

func pulseCorroborationTerms(result pulseSearchResult) []string {
	text := cleanSearchText(strings.Join([]string{result.Title, result.Snippet}, " "))
	terms := []string{}
	appendTerm := func(term string) {
		term = strings.TrimFunc(strings.TrimSpace(term), unicode.IsPunct)
		terms = appendUniqueStrings(terms, term)
	}
	for _, match := range pulseModelEntityPattern.FindAllString(text, -1) {
		appendTerm(normalizePulseEntity(match))
	}
	for _, entity := range pulseKnownEntities {
		if pulseTextContainsFold(text, entity) {
			appendTerm(entity)
		}
	}
	for _, term := range pulseClusterHintTerms(text) {
		if !pulseCorroborationTermLooksGeneric(term) {
			appendTerm(term)
		}
	}
	for _, term := range pulseKeywordsFromText(text) {
		if !pulseCorroborationTermLooksGeneric(term) {
			appendTerm(term)
		}
	}
	return limitStringSlice(terms, 16, 40)
}

func pulseCorroborationTermLooksStrong(term string) bool {
	normalized := strings.ToLower(strings.TrimSpace(term))
	if normalized == "" || pulseCorroborationTermLooksGeneric(normalized) {
		return false
	}
	if pulseModelEntityPattern.MatchString(term) {
		return true
	}
	for _, entity := range pulseKnownEntities {
		if strings.EqualFold(term, entity) {
			return true
		}
	}
	strongTerms := []string{
		"rag", "dify", "claude", "gemini", "openai", "anthropic", "deepseek", "qwen", "kimi",
		"具身智能", "人形机器人", "向量检索", "知识图谱", "知识库", "工具调用", "多智能体",
	}
	for _, value := range strongTerms {
		if normalized == strings.ToLower(value) {
			return true
		}
	}
	if pulseTermHasHan(term) && len([]rune(term)) >= 4 {
		return true
	}
	return strings.ContainsAny(normalized, "-_0123456789")
}

func pulseCorroborationTermLooksGeneric(term string) bool {
	normalized := strings.ToLower(strings.TrimSpace(term))
	if pulseSearchTermLooksGeneric(normalized) {
		return true
	}
	if len([]rune(normalized)) > 32 {
		return true
	}
	generic := []string{
		"code", "open", "source", "github", "issue", "guide", "tutorial", "overview", "example", "examples",
		"release", "released", "launch", "launched", "using", "use", "how", "what", "why", "market", "map",
		"company", "companies", "product", "products", "model", "models", "platform", "platforms",
		"service", "services", "technology", "software", "business", "enterprise", "team", "developer", "developers",
		"announce", "announces", "announced", "official", "independent", "report", "reports", "news", "update", "updates",
		"工程", "实践", "文章", "教程", "指南", "案例", "资料", "经验", "总结", "方案", "系统", "平台",
		"公司", "企业", "产品", "模型", "服务", "技术", "软件", "团队", "开发者", "发布", "宣布", "报道", "更新",
	}
	for _, value := range generic {
		if normalized == strings.ToLower(value) {
			return true
		}
	}
	return false
}

func appendPulseEntity(entities []string, entity string) []string {
	entity = normalizePulseEntity(entity)
	if entity == "" || pulseEntityLooksGeneric(entity) {
		return entities
	}
	normalized := strings.ToLower(strings.ReplaceAll(entity, " ", ""))
	for _, existing := range entities {
		existingKey := strings.ToLower(strings.ReplaceAll(existing, " ", ""))
		if existingKey == normalized || strings.Contains(existingKey, normalized) || strings.Contains(normalized, existingKey) {
			return entities
		}
	}
	return append(entities, entity)
}

func normalizePulseEntity(entity string) string {
	entity = strings.TrimSpace(strings.Join(strings.Fields(entity), " "))
	entity = strings.Trim(entity, "：:，,。.;；、()（）[]【】\"'")
	if entity == "" {
		return ""
	}
	lower := strings.ToLower(entity)
	switch lower {
	case "gpt", "chatgpt":
		return "GPT"
	case "openai":
		return "OpenAI"
	case "claude":
		return "Claude"
	case "anthropic":
		return "Anthropic"
	case "gemini":
		return "Gemini"
	case "llama":
		return "Llama"
	case "grok":
		return "Grok"
	case "xai":
		return "xAI"
	case "deepseek":
		return "DeepSeek"
	case "qwen":
		return "Qwen"
	case "kimi":
		return "Kimi"
	case "mistral":
		return "Mistral"
	case "sora":
		return "Sora"
	case "fable":
		return "Fable"
	case "mythos":
		return "Mythos"
	}
	if strings.HasPrefix(lower, "gpt") {
		return strings.ToUpper(strings.ReplaceAll(entity, " ", "-"))
	}
	return entity
}

func pulseEntityLooksGeneric(entity string) bool {
	normalized := strings.ToLower(strings.TrimSpace(entity))
	if normalized == "" {
		return true
	}
	generic := []string{"latest", "news", "the", "model", "models", "available", "all", "new"}
	for _, value := range generic {
		if normalized == value {
			return true
		}
	}
	return false
}

func searchFallbackClusterTitleChange(results []pulseSearchResult) string {
	if len(results) == 1 || pulseAllWeakSearchSources(results) {
		return ""
	}
	text := strings.ToLower(searchFallbackResultsText(results))
	switch {
	case pulseTextHasAny(text, "expected", "reportedly", "rumor", "rumour", "预计", "传闻", "据称", "据报道") &&
		pulseTextHasAny(text, "release", "released", "launch", "launched", "发布", "推出", "上线"):
		return "发布计划受到多源报道"
	case pulseTextHasAny(text, "release", "released", "launch", "launched", "announce", "announces", "unveil", "unveils", "available", "发布", "推出", "宣布", "上线", "开放"):
		return "正式发布"
	case pulseTextHasAny(text, "acquire", "acquired", "acquisition", "收购"):
		return "宣布收购交易"
	case pulseTextHasAny(text, "funding", "fundraise", "raised", "融资"):
		return "完成新一轮融资"
	case pulseTextHasAny(text, "partner", "partnership", "合作", "签署"):
		return "宣布合作计划"
	case pulseTextHasAny(text, "benchmark", "performance", "state-of-the-art", "能力", "性能", "评测"):
		return "公布新能力评测"
	default:
		return ""
	}
}

func pulseAllWeakSearchSources(results []pulseSearchResult) bool {
	if len(results) == 0 {
		return false
	}
	for _, result := range results {
		if !pulseWeakSearchSource(result) {
			return false
		}
	}
	return true
}

func pulseWeakSearchSource(result pulseSearchResult) bool {
	parsed, err := url.Parse(strings.TrimSpace(result.URL))
	if err != nil {
		return false
	}
	host := strings.TrimPrefix(strings.ToLower(parsed.Hostname()), "www.")
	weakHosts := []string{
		"blog.csdn.net",
		"download.csdn.net",
		"csdn.net",
		"cnblogs.com",
		"juejin.cn",
		"zhihu.com",
		"zhuanlan.zhihu.com",
		"segmentfault.com",
		"dev.to",
		"medium.com",
		"sohu.com",
		"toutiao.com",
		"baijiahao.baidu.com",
		"163.com",
		"so.html5.qq.com",
		"baike.sogou.com",
	}
	for _, weakHost := range weakHosts {
		if host == weakHost || strings.HasSuffix(host, "."+weakHost) {
			return true
		}
	}
	return false
}

func pulsePrimarySearchSource(result pulseSearchResult) bool {
	source := strings.ToLower(cleanSearchText(result.Source))
	if pulseTextHasAny(source, "official", "primary source", "官网", "官方", "公司公告") {
		return true
	}
	return pulseSearchSourceHostMatches(result.URL, []string{
		"openai.com", "chatgpt.com", "anthropic.com", "claude.com",
		"blog.google", "deepmind.google", "ai.google.dev", "developers.googleblog.com",
		"x.ai", "meta.com", "deepseek.com", "qwenlm.ai", "alibabacloud.com",
		"mistral.ai", "nvidia.com", "microsoft.com", "sec.gov", "arxiv.org",
		"uipath.com", "openrouter.ai", "huggingface.co", "aws.amazon.com",
		"gov.cn", "samr.gov.cn",
	})
}

func pulseAuthoritativeSearchSource(result pulseSearchResult) bool {
	if pulsePrimarySearchSource(result) {
		return true
	}
	return pulseSearchSourceHostMatches(result.URL, []string{
		"reuters.com", "apnews.com", "bloomberg.com", "ft.com", "wsj.com",
		"economist.com", "technologyreview.com", "theverge.com", "techcrunch.com",
		"cnbc.com", "bbc.com", "theguardian.com", "nikkei.com", "wired.com",
		"arstechnica.com", "venturebeat.com", "zdnet.com", "axios.com", "fortune.com",
		"theinformation.com", "business-standard.com", "thehindu.com", "36kr.com",
		"new.qq.com", "news.qq.com", "caixin.com", "yicai.com", "stcn.com",
		"cnstock.com", "chinanews.com.cn", "thepaper.cn", "jiemian.com",
		"21jingji.com", "eeo.com.cn", "cls.cn", "redstarnews.com",
	})
}

func pulseSearchSourceHostMatches(rawURL string, domains []string) bool {
	parsed, err := url.Parse(strings.TrimSpace(rawURL))
	if err != nil {
		return false
	}
	host := strings.TrimPrefix(strings.ToLower(parsed.Hostname()), "www.")
	for _, domain := range domains {
		domain = strings.TrimPrefix(strings.ToLower(strings.TrimSpace(domain)), "www.")
		if host == domain || strings.HasSuffix(host, "."+domain) {
			return true
		}
	}
	return false
}

func searchFallbackClusterSummaryChange(results []pulseSearchResult) string {
	text := strings.ToLower(searchFallbackResultsText(results))
	switch {
	case pulseTextHasAny(text, "expected", "reportedly", "rumor", "rumour", "预计", "传闻", "据称", "据报道") &&
		pulseTextHasAny(text, "release", "released", "launch", "launched", "发布", "推出", "上线"):
		return "计划发布新版本，但不同报道给出的时间或开放范围尚未一致"
	case pulseTextHasAny(text, "release", "released", "launch", "launched", "announce", "announces", "unveil", "unveils", "available", "发布", "推出", "宣布", "上线", "开放"):
		return "已正式发布，多家来源同时提到其版本能力或开放范围变化"
	case pulseTextHasAny(text, "acquire", "acquired", "acquisition", "收购"):
		return "宣布收购交易，多家来源报道了同一交易主体"
	case pulseTextHasAny(text, "funding", "fundraise", "raised", "融资"):
		return "完成新一轮融资，多家来源报道了同一融资事件"
	case pulseTextHasAny(text, "partner", "partnership", "合作", "签署"):
		return "宣布合作计划，多家来源报道了同一合作事件"
	case pulseTextHasAny(text, "benchmark", "performance", "state-of-the-art", "capable", "能力", "性能", "评测"):
		return "公布了新的能力评测结果，不同来源的评测口径仍有差异"
	default:
		return ""
	}
}

func searchFallbackClusterAspects(results []pulseSearchResult) []string {
	text := strings.ToLower(searchFallbackResultsText(results))
	aspects := []string{}
	if pulseTextHasAny(text, "expected", "date", "when", "预计", "时间", "日期", "发布") {
		aspects = append(aspects, "时间线")
	}
	if pulseTextHasAny(text, "version", "gpt-", "fable", "mythos", "版本", "型号", "模型") {
		aspects = append(aspects, "版本/模型名称")
	}
	if pulseTextHasAny(text, "available", "access", "restricted", "everyone", "开放", "可用", "访问", "限制") {
		aspects = append(aspects, "开放范围")
	}
	if pulseTextHasAny(text, "performance", "benchmark", "capable", "state-of-the-art", "能力", "性能", "评测") {
		aspects = append(aspects, "能力变化")
	}
	if pulseTextHasAny(text, "safe", "safety", "guardrail", "安全", "风控") {
		aspects = append(aspects, "安全/风控约束")
	}
	if len(aspects) == 0 {
		aspects = append(aspects, "事实更新", "来源可信度", "后续跟踪关键词")
	}
	return limitStringSlice(aspects, 4, 24)
}

func searchFallbackClusterUncertainty(results []pulseSearchResult) string {
	text := strings.ToLower(searchFallbackResultsText(results))
	if pulseTextHasAny(text, "expected", "reportedly", "rumor", "rumour", "预计", "传闻", "据称", "据报道") {
		return "目前更像待核验信号，具体发布时间、版本号和官方表述要以原文/官方发布为准。"
	}
	return "这是搜索摘要聚合，具体事实、发布时间和上下文仍要打开原文核验。"
}

func pulseClusterMentionsModel(text string) bool {
	return pulseTextHasAny(text, "gpt", "claude", "gemini", "llama", "model", "llm", "openai", "anthropic", "模型", "大模型")
}

func searchFallbackClusterText(queryEvidence pulseSearchEvidence, results []pulseSearchResult) string {
	parts := []string{queryEvidence.TopicName, queryEvidence.Query, queryEvidence.Intent}
	for _, result := range results {
		parts = append(parts, result.Title, result.Snippet, result.Source)
	}
	return strings.Join(parts, " ")
}

func searchFallbackResultsText(results []pulseSearchResult) string {
	parts := []string{}
	for _, result := range results {
		parts = append(parts, result.Title, result.Snippet)
	}
	return strings.Join(parts, " ")
}

func pulseTextContainsFold(text string, needle string) bool {
	return strings.Contains(strings.ToLower(text), strings.ToLower(needle))
}

func pulseTextHasAny(text string, needles ...string) bool {
	for _, needle := range needles {
		if strings.Contains(text, strings.ToLower(needle)) {
			return true
		}
	}
	return false
}

func searchResultSnippet(result pulseSearchResult) string {
	return firstNonEmptyPulse(cleanSearchText(result.Snippet), cleanSearchText(result.Title), "搜索结果没有提供摘要，需要点击来源或继续追问来核验细节。")
}

func pulseItemCopyLooksLikeSearchDump(title string, summary string) bool {
	return pulseTitleLooksLikeSearchDump(title) || pulseSummaryLooksLikeSearchDump(summary)
}

func pulseTitleLooksLikeSearchDump(value string) bool {
	cleaned := cleanSearchText(value)
	normalized := strings.ToLower(cleaned)
	if cleaned == "" {
		return false
	}
	badFragments := []string{
		"近期资讯聚合",
		"recent news",
		"latest news",
		"the latest news",
		"latest information",
	}
	for _, fragment := range badFragments {
		if strings.Contains(normalized, strings.ToLower(fragment)) {
			return true
		}
	}
	return pulseMostlyEnglish(cleaned) && len([]rune(cleaned)) > 32
}

func pulseSummaryLooksLikeSearchDump(value string) bool {
	cleaned := cleanSearchText(value)
	normalized := strings.ToLower(cleaned)
	if cleaned == "" {
		return false
	}
	badFragments := []string{
		"关键线索是",
		"另一个来源关注",
		"latest information",
		"the latest information",
	}
	for _, fragment := range badFragments {
		if strings.Contains(normalized, strings.ToLower(fragment)) {
			return true
		}
	}
	return strings.HasPrefix(cleaned, "聚合 ") || (pulseMostlyEnglish(cleaned) && len([]rune(cleaned)) > 80)
}

func pulseMostlyEnglish(value string) bool {
	letterCount := 0
	hanCount := 0
	for _, r := range value {
		switch {
		case unicode.Is(unicode.Han, r):
			hanCount++
		case (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z'):
			letterCount++
		}
	}
	return hanCount == 0 && letterCount >= 18
}

func pulseSearchResultsFromNewsSources(sources []pulseNewsSource) []pulseSearchResult {
	results := make([]pulseSearchResult, 0, len(sources))
	for _, source := range sources {
		if !pulseSafeHTTPURL(source.URL) {
			continue
		}
		results = append(results, pulseSearchResult{
			Title:       cleanSearchText(source.Title),
			Snippet:     cleanSearchText(source.Snippet),
			URL:         strings.TrimSpace(source.URL),
			Source:      cleanSearchText(source.Source),
			PublishedAt: cleanSearchText(source.PublishedAt),
		})
	}
	return results
}

func newsSourcesFromSearchResults(results []pulseSearchResult, maxItems int) []pulseNewsSource {
	sources := make([]pulseNewsSource, 0, minInt(len(results), maxItems))
	for _, result := range results {
		sources = append(sources, pulseNewsSource{
			Title:       result.Title,
			URL:         result.URL,
			Source:      result.Source,
			Snippet:     result.Snippet,
			PublishedAt: result.PublishedAt,
		})
	}
	return normalizeNewsSources(sources, maxItems)
}

func newsSourcePromptLines(sources []pulseNewsSource) string {
	lines := []string{}
	for _, source := range sources[:minInt(len(sources), 5)] {
		lines = append(lines, fmt.Sprintf("- %s: %s", firstNonEmptyPulse(source.Title, source.Source, "新闻来源"), source.URL))
	}
	return strings.Join(lines, "\n")
}

func personalizedPulseSuggestedQuestions(existing []string, ctx pulseQuestionContext) []string {
	terms := pulseQuestionTerms(ctx)
	questions := []string{}
	appendQuestion := func(question string, requireContext bool) {
		if len(questions) >= pulseSuggestedQuestionLimit {
			return
		}
		cleaned := cleanSearchText(question)
		if cleaned == "" || pulseQuestionLooksGeneric(cleaned) {
			return
		}
		if requireContext && !pulseQuestionMentionsContext(cleaned, terms) {
			return
		}
		cleaned = pulseCompactSuggestedQuestion(cleaned)
		if cleaned == "" || !pulseWelcomeSuggestionLooksUseful(cleaned) {
			return
		}
		questions = appendUniqueStrings(questions, cleaned)
	}
	for _, question := range existing {
		appendQuestion(question, len(terms) > 0)
	}

	for _, question := range buildPulseSuggestedQuestions(ctx) {
		appendQuestion(question, false)
	}

	focus := pulseShortQuestionAnchor(
		firstNonEmptyPulse(pulseQuestionFocus(ctx), ctx.TopicName, ctx.Query, moduleCategory(ctx.Module)),
		16,
	)
	anchor := pulseShortQuestionAnchor(
		firstNonEmptyPulse(ctx.TopicName, ctx.Category, moduleCategory(ctx.Module), focus, "这个方向"),
		14,
	)
	for _, question := range []string{
		fmt.Sprintf("「%s」发生了什么？", focus),
		fmt.Sprintf("「%s」有哪些关键证据？", focus),
		fmt.Sprintf("接下来跟踪「%s」什么？", anchor),
	} {
		appendQuestion(question, false)
	}
	return questions[:minInt(len(questions), pulseSuggestedQuestionLimit)]
}

func buildPulseSuggestedQuestions(ctx pulseQuestionContext) []string {
	focus := pulseShortQuestionAnchor(pulseQuestionFocus(ctx), 16)
	topic := pulseShortQuestionAnchor(firstNonEmptyPulse(ctx.TopicName, ctx.Category, moduleCategory(ctx.Module)), 14)
	sourceA := pulseShortQuestionAnchor(pulseSourceQuestionTitle(ctx.Sources, 0), 14)
	sourceB := pulseShortQuestionAnchor(pulseSourceQuestionTitle(ctx.Sources, 1), 14)
	keyPoint := pulseShortQuestionAnchor(pulseDistinctQuestionPhrase(pulseQuestionPhraseFromStrings(ctx.KeyPoints), focus, sourceA), 14)
	if keyPoint == "" {
		keyPoint = pulseShortQuestionAnchor(pulseDistinctQuestionPhrase(pulseQuestionPhrase(ctx.Summary), focus, sourceA), 14)
	}

	questions := []string{}
	if focus != "" {
		questions = append(questions, fmt.Sprintf("「%s」发生了什么？", focus))
	}
	if keyPoint != "" {
		questions = append(questions, fmt.Sprintf("「%s」有哪些证据？", keyPoint))
	}
	if sourceA != "" && sourceB != "" {
		questions = append(questions, fmt.Sprintf("「%s」与「%s」哪里一致？", sourceA, sourceB))
	}
	if sourceA != "" {
		questions = append(questions, fmt.Sprintf("「%s」有哪些关键事实？", sourceA))
	}
	if topic != "" {
		questions = append(questions, fmt.Sprintf("接下来跟踪「%s」什么？", topic))
	}
	if len(questions) == 0 {
		questions = append(questions, "这条更新发生了什么？", "有哪些关键证据？", "接下来跟踪什么？")
	}
	return questions
}

func pulseShortQuestionAnchor(value string, maxRunes int) string {
	value = pulseQuestionPhrase(value)
	if maxRunes <= 1 {
		return ""
	}
	for _, separator := range []string{"、", "，", ",", "；", ";", "：", ":"} {
		if index := strings.Index(value, separator); index >= 0 {
			candidate := strings.TrimSpace(value[:index])
			if len([]rune(candidate)) >= 2 {
				value = candidate
				break
			}
		}
	}
	runes := []rune(value)
	if len(runes) <= maxRunes {
		return strings.TrimSpace(strings.TrimRight(value, "、，,；;：:-_"))
	}
	cut := maxRunes
	for index := maxRunes - 1; index >= maxRunes/2; index-- {
		if unicode.IsSpace(runes[index]) || strings.ContainsRune("、，,；;：:-_", runes[index]) {
			cut = index
			break
		}
	}
	return strings.TrimSpace(strings.TrimRight(string(runes[:cut]), "、，,；;：:-_"))
}

func pulseCompactSuggestedQuestion(value string) string {
	value = cleanSearchText(value)
	value = strings.TrimSpace(strings.TrimRight(value, "。.!！?？;；,，"))
	if value == "" {
		return ""
	}
	runes := []rune(value)
	if len(runes) >= pulseSuggestedQuestionMaxRunes {
		return ""
	}
	return value + "？"
}

func pulseQuestionLooksGeneric(question string) bool {
	normalized := strings.ToLower(strings.TrimSpace(question))
	if normalized == "" {
		return true
	}
	genericFragments := []string{
		"为什么值得关注",
		"有哪些风险",
		"最近有哪些进展",
		"有哪些公司",
		"下一步做什么",
		"怎么验证",
		"如何排优先级",
		"请展开",
		"帮我检索这个方向",
		"这些来源共同说明了什么趋势",
		"这个话题和我的近期目标有什么关系",
		"它和我订阅的 topic/关键词有什么关系",
		"对我关注的",
		"意味着什么",
		"结论哪里一致",
		"哪些来源支持或反驳",
		"哪些事实需要打开原文确认",
		"如果以",
		"应该排除哪些噪声结果",
		"有什么落地场景",
		"成本瓶颈在哪",
		"用 5 分钟",
		"用5分钟",
	}
	for _, fragment := range genericFragments {
		if strings.Contains(normalized, strings.ToLower(fragment)) {
			return true
		}
	}
	return false
}

func pulseQuestionMentionsContext(question string, terms []string) bool {
	if len(terms) == 0 {
		return true
	}
	normalizedQuestion := strings.ToLower(question)
	for _, term := range terms {
		needle := strings.ToLower(pulseQuestionPhrase(term))
		if needle == "" {
			continue
		}
		if strings.Contains(normalizedQuestion, needle) {
			return true
		}
		runes := []rune(needle)
		if len(runes) > 8 && strings.Contains(normalizedQuestion, string(runes[:8])) {
			return true
		}
	}
	return false
}

func pulseQuestionTerms(ctx pulseQuestionContext) []string {
	terms := []string{}
	terms = appendUniqueStrings(terms, pulseQuestionFocus(ctx), ctx.TopicName, ctx.Category, ctx.Intent)
	for _, part := range strings.Fields(ctx.Query) {
		terms = appendUniqueStrings(terms, part)
	}
	for _, point := range ctx.KeyPoints[:minInt(len(ctx.KeyPoints), 3)] {
		terms = appendUniqueStrings(terms, pulseQuestionPhrase(point))
	}
	for _, source := range ctx.Sources[:minInt(len(ctx.Sources), 3)] {
		terms = appendUniqueStrings(terms, pulseQuestionPhrase(source.Title))
	}
	return limitStringSlice(terms, 10, 40)
}

func pulseQuestionFocus(ctx pulseQuestionContext) string {
	value := cleanSearchText(firstNonEmptyPulse(ctx.Title, ctx.Summary, ctx.TopicName, ctx.Query))
	if value == "" {
		return ""
	}
	if strings.Contains(value, "近期资讯聚合") || strings.HasPrefix(value, "可能值得关注") || strings.HasPrefix(value, "近日关注延伸") {
		if index := strings.Index(value, "："); index >= 0 && index+len("：") < len(value) {
			value = strings.TrimSpace(value[index+len("："):])
		} else if index := strings.Index(value, ":"); index >= 0 && index+1 < len(value) {
			value = strings.TrimSpace(value[index+1:])
		}
	}
	return pulseQuestionPhrase(value)
}

func pulseSourceQuestionTitle(sources []pulseNewsSource, index int) string {
	if index < 0 || index >= len(sources) {
		return ""
	}
	return pulseQuestionPhrase(sources[index].Title)
}

func pulseQuestionPhraseFromStrings(values []string) string {
	for _, value := range values {
		if phrase := pulseQuestionPhraseFromKeyPoint(value); phrase != "" {
			return phrase
		}
	}
	return ""
}

func pulseQuestionPhraseFromKeyPoint(value string) string {
	cleaned := cleanSearchText(value)
	if index := strings.Index(cleaned, "："); index > 0 && index+len("：") < len(cleaned) {
		before := strings.TrimSpace(cleaned[:index])
		after := strings.TrimSpace(cleaned[index+len("："):])
		if len([]rune(before)) > 18 && after != "" {
			return pulseQuestionPhrase(after)
		}
	}
	return pulseQuestionPhrase(cleaned)
}

func pulseDistinctQuestionPhrase(candidate string, existing ...string) string {
	candidate = pulseQuestionPhrase(candidate)
	if candidate == "" {
		return ""
	}
	for _, value := range existing {
		if pulseQuestionPhrasesOverlap(candidate, value) {
			return ""
		}
	}
	return candidate
}

func pulseQuestionPhrasesOverlap(left string, right string) bool {
	left = strings.ToLower(pulseQuestionPhrase(left))
	right = strings.ToLower(pulseQuestionPhrase(right))
	if left == "" || right == "" {
		return false
	}
	leftKey := pulseQuestionPrefix(left, 12)
	rightKey := pulseQuestionPrefix(right, 12)
	if leftKey == "" || rightKey == "" {
		return false
	}
	return strings.Contains(left, rightKey) || strings.Contains(right, leftKey)
}

func pulseQuestionPrefix(value string, maxRunes int) string {
	runes := []rune(value)
	if len(runes) <= maxRunes {
		return string(runes)
	}
	return string(runes[:maxRunes])
}

func pulseQuestionPhrase(value string) string {
	cleaned := cleanSearchText(value)
	cleaned = strings.Trim(cleaned, "「」\"'“”‘’[]()（） ")
	if cleaned == "" {
		return ""
	}
	if index := strings.Index(cleaned, "关键线索是："); index >= 0 {
		cleaned = strings.TrimSpace(cleaned[index+len("关键线索是："):])
	}
	if index := strings.Index(cleaned, "关键线索是:"); index >= 0 {
		cleaned = strings.TrimSpace(cleaned[index+len("关键线索是:"):])
	}
	for _, sep := range []string{"。", "；", ";", "\n"} {
		if index := strings.Index(cleaned, sep); index > 0 {
			cleaned = strings.TrimSpace(cleaned[:index])
		}
	}
	if index := strings.Index(cleaned, "："); index > 0 && index < 18 {
		cleaned = strings.TrimSpace(cleaned[index+len("："):])
	}
	if index := strings.Index(cleaned, ":"); index > 0 && index < 18 {
		cleaned = strings.TrimSpace(cleaned[index+1:])
	}
	return limitText(cleaned, 36)
}

func buildFallbackPulse(date string, topics []models.PulseTopic, signals []memoryPulseSignal, searchErrors []string) ([]models.PulseModule, []models.PulseItem) {
	now := time.Now()
	modules := make([]models.PulseModule, 0, len(pulseModuleOrder))
	for _, key := range pulseModuleOrder {
		title, summary := fallbackModuleCopy(key, topics, signals, searchErrors)
		modules = append(modules, models.PulseModule{
			ID:        pulseItemID(date, "module", key),
			Date:      date,
			Key:       key,
			Title:     title,
			Summary:   summary,
			CreatedAt: now,
			UpdatedAt: now,
		})
	}
	return modules, []models.PulseItem{}
}

func fallbackItem(date, source string, index int, title, reason, topicID, topicName, category string, searchErrors []string) models.PulseItem {
	now := time.Now()
	signals := []string{
		"降级生成：Pulse 外网检索或预计算 Agent 暂不可用。",
		"没有可用外网搜索结果；这不是最新热点总结，只是待检索问题入口。",
	}
	if len(searchErrors) > 0 {
		signals = append(signals, "搜索错误："+strings.Join(limitStringSlice(searchErrors, 2, 160), "；"))
	}
	questionContext := pulseQuestionContext{
		Title:     title,
		Summary:   reason,
		Module:    source,
		TopicName: topicName,
		Category:  category,
		KeyPoints: []string{reason},
		Context:   reason,
	}
	detail := pulseItemDetail{
		ContentVersion:       pulseContentVersion,
		RecommendationReason: reason,
		Signals:              signals,
		QuickContext:         "这是为了保证定时 Pulse 不空白而生成的降级推荐；下一次外网搜索与 Agent 可用时会重新生成基于来源的新内容。",
		KeyPoints:            []string{"把它当作可继续追问的入口。", "如果需要实时事实，请点击后让助手搜索验证。", "你可以调整 topic 来影响后续推荐。"},
		SuggestedQuestions:   personalizedPulseSuggestedQuestions(nil, questionContext),
		PrecomputedAt:        now.UTC().Format(time.RFC3339),
	}
	return models.PulseItem{
		ID:            pulseItemID(date, source, fmt.Sprintf("%s:%d", title, index)),
		Date:          date,
		TopicID:       topicID,
		TopicName:     topicName,
		Source:        source,
		Category:      category,
		Title:         title,
		Summary:       reason,
		HeatScore:     normalizeHeatScore(0, source, index),
		DetailJSON:    mustJSON(detail),
		ExplorePrompt: fmt.Sprintf("请展开「%s」，先说明推荐依据，再给我 3 个可继续追问的问题。", title),
		CreatedAt:     now,
		UpdatedAt:     now,
	}
}

func inferMemorySignals(messages []models.Message) []memoryPulseSignal {
	type themeSpec struct {
		theme    string
		focus    string
		keywords []string
	}
	specs := []themeSpec{
		{theme: "AI 应用与 Agent", focus: "AI Agent、模型能力和应用工程化", keywords: []string{"ai", "agent", "gpt", "模型", "rag", "minimax", "openai", "智能体"}},
		{theme: "AIGC 创作", focus: "生图、提示词和多模态素材创作", keywords: []string{"生图", "画", "图片", "头像", "提示词", "多模态", "aigc"}},
		{theme: "旅行规划", focus: "短途路线、住宿和行程取舍", keywords: []string{"旅游", "旅行", "自驾", "出发", "两天一夜", "路线", "惠州", "清远"}},
		{theme: "投资研究", focus: "公司基本面、风险和投资判断", keywords: []string{"投资", "公司", "值得投资", "估值", "spacex", "商业模式"}},
		{theme: "健康管理", focus: "减脂、训练、饮食和恢复", keywords: []string{"减脂", "健康", "训练", "饮食", "睡眠", "体重"}},
		{theme: "工程实现", focus: "代码、接口、测试和产品功能落地", keywords: []string{"代码", "接口", "测试", "go", "python", "前端", "后端", "功能"}},
	}

	signalsByTheme := map[string]*memoryPulseSignal{}
	recentUserMessages := make([]string, 0, len(messages))
	for _, message := range messages {
		if message.Role != "user" {
			continue
		}
		content := strings.TrimSpace(message.Content)
		if content == "" {
			continue
		}
		recentUserMessages = append(recentUserMessages, content)
		lower := strings.ToLower(content)
		for _, spec := range specs {
			matched := matchedKeywords(lower, spec.keywords)
			if len(matched) == 0 {
				continue
			}
			signal := signalsByTheme[spec.theme]
			if signal == nil {
				signal = &memoryPulseSignal{Theme: spec.theme, Focus: spec.focus}
				signalsByTheme[spec.theme] = signal
			}
			signal.Count++
			signal.Keywords = appendUniqueStrings(signal.Keywords, matched...)
			if len(signal.Snippets) < 2 {
				signal.Snippets = append(signal.Snippets, "近期消息："+compactSnippet(content, 52))
			}
		}
	}

	signals := make([]memoryPulseSignal, 0, len(signalsByTheme))
	for _, signal := range signalsByTheme {
		sort.Strings(signal.Keywords)
		signals = append(signals, *signal)
	}
	sort.SliceStable(signals, func(i, j int) bool {
		if signals[i].Count == signals[j].Count {
			return signals[i].Theme < signals[j].Theme
		}
		return signals[i].Count > signals[j].Count
	})

	if len(signals) > 0 {
		return signals
	}
	if len(recentUserMessages) > 0 {
		return []memoryPulseSignal{{
			Theme:    "最近对话延展",
			Focus:    "延续你最近提出的问题",
			Count:    len(recentUserMessages),
			Keywords: []string{"最近对话"},
			Snippets: []string{"近期消息：" + compactSnippet(recentUserMessages[0], 52)},
		}}
	}
	return nil
}

func collectInterestTerms(topics []models.PulseTopic, signals []memoryPulseSignal) []string {
	terms := []string{}
	for _, topic := range topics {
		terms = appendUniqueStrings(terms, topic.Name)
		terms = appendUniqueStrings(terms, expandPulseTopicKeywords(topic.Name, decodeKeywords(topic.Keywords))...)
	}
	for _, signal := range signals {
		terms = appendUniqueStrings(terms, signal.Theme, signal.Focus)
		terms = appendUniqueStrings(terms, signal.Keywords...)
	}
	return terms
}

func buildPulseSuggestedTopics(topics []models.PulseTopic, signals []memoryPulseSignal) []pulseSuggestedTopicResponse {
	existing := map[string]bool{}
	for _, topic := range topics {
		existing[normalizedPulseTopicKey(topic.Name)] = true
	}

	suggestions := []pulseSuggestedTopicResponse{}
	add := func(name string, keywords []string, reason string, source string, heat int) {
		name = normalizeTopicName(name)
		if name == "" {
			return
		}
		key := normalizedPulseTopicKey(name)
		if key == "" || existing[key] {
			return
		}
		for _, item := range suggestions {
			if normalizedPulseTopicKey(item.Name) == key {
				return
			}
		}
		suggestions = append(suggestions, pulseSuggestedTopicResponse{
			Name:      name,
			Keywords:  limitStringSlice(expandPulseTopicKeywords(name, keywords), 5, 28),
			Reason:    limitText(reason, 120),
			Source:    source,
			HeatScore: normalizeHeatScore(heat, pulseSourceInterestHot, len(suggestions)),
		})
	}

	for index, signal := range signals[:minInt(len(signals), 4)] {
		name := pulseTopicNameFromSignal(signal)
		keywords := append([]string{}, signal.Keywords...)
		keywords = appendUniqueStrings(keywords, pulseKeywordsFromText(signal.Focus)...)
		reason := fmt.Sprintf("来自最近对话里的「%s」信号，适合先订阅成一个可持续追踪的 topic。", signal.Theme)
		add(name, keywords, reason, "memory", 94-index*4)
	}

	for _, topic := range topics {
		for _, seed := range adjacentPulseTopicSeeds(topic) {
			add(seed.Name, seed.Keywords, seed.Reason, "topic_expansion", seed.HeatScore)
		}
	}

	for _, seed := range defaultPulseTopicSeeds() {
		add(seed.Name, seed.Keywords, seed.Reason, seed.Source, seed.HeatScore)
	}

	limit := 6
	if len(topics) > 0 {
		limit = 5
	}
	if len(suggestions) > limit {
		suggestions = suggestions[:limit]
	}
	return suggestions
}

func pulseTopicNameFromSignal(signal memoryPulseSignal) string {
	switch signal.Theme {
	case "最近对话延展":
		return "最近问题延伸"
	case "工作台探索":
		return "个人工作台与效率系统"
	default:
		return signal.Theme
	}
}

func adjacentPulseTopicSeeds(topic models.PulseTopic) []pulseSuggestedTopicResponse {
	text := strings.ToLower(strings.Join(append([]string{topic.Name}, decodeKeywords(topic.Keywords)...), " "))
	seeds := []pulseSuggestedTopicResponse{}
	add := func(name string, keywords []string, reason string, heat int) {
		seeds = append(seeds, pulseSuggestedTopicResponse{
			Name:      name,
			Keywords:  keywords,
			Reason:    reason,
			Source:    "topic_expansion",
			HeatScore: heat,
		})
	}
	switch {
	case pulseTextHasAny(text, "agent", "rag", "ai", "openai", "模型", "智能体", "大模型"):
		add("Agent 工程实践", []string{"工具调用", "RAG", "工作流", "评测"}, "由 AI/Agent 相关订阅外扩，适合追踪工程落地和产品架构。", 88)
		add("大模型产品动态", []string{"OpenAI", "Claude", "Gemini", "模型能力"}, "和当前 AI 订阅相邻，适合集中跟进模型与产品发布。", 84)
	case pulseTextHasAny(text, "机器人", "具身", "embodied", "人形"):
		add("具身智能产业链", []string{"人形机器人", "传感器", "执行器", "量产"}, "由机器人订阅外扩，适合跟进产业化、供应链和商业化信号。", 88)
		add("机器人模型与数据", []string{"VLA", "world model", "仿真数据", "机器人学习"}, "和机器人 topic 相邻，适合深入模型、数据和训练范式。", 84)
	case pulseTextHasAny(text, "投资", "估值", "公司", "商业模式"):
		add("公司基本面跟踪", []string{"收入", "毛利", "竞争格局", "风险"}, "由投资研究订阅外扩，适合持续沉淀可核验的信息簇。", 86)
	case pulseTextHasAny(text, "健康", "减脂", "训练", "饮食"):
		add("训练与恢复", []string{"力量训练", "睡眠", "蛋白质", "恢复"}, "由健康管理订阅外扩，适合把信息流变成可执行的长期跟踪。", 84)
	}
	return seeds
}

func defaultPulseTopicSeeds() []pulseSuggestedTopicResponse {
	return []pulseSuggestedTopicResponse{
		{Name: "AI 应用开发", Keywords: []string{"Agent", "RAG", "多模态", "工作流"}, Reason: "适合作为信息流冷启动 topic，覆盖产品、工程和模型能力。", Source: "starter", HeatScore: 82},
		{Name: "大模型产品动态", Keywords: []string{"OpenAI", "Claude", "Gemini", "模型发布"}, Reason: "更新频率高，容易形成可持续阅读的信息簇。", Source: "starter", HeatScore: 80},
		{Name: "工程效率与工具链", Keywords: []string{"代码助手", "DevOps", "测试", "自动化"}, Reason: "和日常研发工作相关，适合积累可复用方法。", Source: "starter", HeatScore: 76},
		{Name: "产品增长与用户研究", Keywords: []string{"增长实验", "留存", "推荐系统", "用户洞察"}, Reason: "适合从案例、数据和方法论里继续延展学习。", Source: "starter", HeatScore: 72},
		{Name: "投资研究", Keywords: []string{"公司基本面", "估值", "商业模式", "风险"}, Reason: "适合把外部资讯整理成可核验的研究线索。", Source: "starter", HeatScore: 68},
		{Name: "健康管理", Keywords: []string{"减脂", "训练", "饮食", "睡眠"}, Reason: "适合长期跟踪可执行建议和个人目标。", Source: "starter", HeatScore: 64},
	}
}

func expandPulseTopicKeywords(name string, keywords []string) []string {
	expanded := normalizeKeywords(keywords)
	text := strings.ToLower(strings.Join(append([]string{name}, expanded...), " "))
	add := func(values ...string) {
		expanded = appendUniqueStrings(expanded, values...)
	}

	switch {
	case pulseTextHasAny(text, "agent", "智能体"):
		add("工具调用", "RAG", "工作流", "评测", "多智能体")
	case pulseTextHasAny(text, "rag", "知识库"):
		add("向量检索", "重排", "知识库", "引用来源", "评测")
	case pulseTextHasAny(text, "ai", "openai", "claude", "gemini", "模型", "大模型"):
		add("模型能力", "产品发布", "多模态", "推理", "开源模型")
	case pulseTextHasAny(text, "机器人", "具身", "embodied", "人形"):
		add("具身智能", "人形机器人", "VLA", "量产", "供应链")
	case pulseTextHasAny(text, "投资", "估值", "公司", "商业模式"):
		add("公司基本面", "收入", "竞争格局", "风险", "估值")
	case pulseTextHasAny(text, "产品", "增长", "用户"):
		add("用户研究", "留存", "转化", "推荐系统", "增长实验")
	case pulseTextHasAny(text, "健康", "减脂", "训练", "饮食"):
		add("热量缺口", "力量训练", "蛋白质", "睡眠", "恢复")
	case pulseTextHasAny(text, "旅行", "旅游", "自驾"):
		add("路线", "住宿", "交通", "预算", "避坑")
	}

	if len(expanded) == 0 {
		expanded = appendUniqueStrings(expanded, pulseKeywordsFromText(name)...)
	}
	return limitStringSlice(expanded, 8, 28)
}

func pulseKeywordsFromText(value string) []string {
	parts := strings.FieldsFunc(value, func(r rune) bool {
		return unicode.IsSpace(r) || strings.ContainsRune(",，;；/、|｜:：()（）[]【】", r)
	})
	keywords := []string{}
	for _, part := range parts {
		cleaned := strings.TrimSpace(part)
		if cleaned == "" {
			continue
		}
		runeCount := len([]rune(cleaned))
		if runeCount < 2 || runeCount > 18 {
			continue
		}
		keywords = appendUniqueStrings(keywords, cleaned)
	}
	return keywords
}

func normalizedPulseTopicKey(value string) string {
	return strings.ToLower(strings.ReplaceAll(normalizeTopicName(value), " ", ""))
}

func normalizePulseModuleKey(key string) string {
	switch strings.TrimSpace(key) {
	case pulseSourceTopicHot, "topic", "topicHot":
		return pulseSourceTopicHot
	case pulseSourceMemory, "recent_memory":
		return pulseSourceMemory
	case pulseSourceInterestHot, "hot", "interestHot":
		return pulseSourceInterestHot
	default:
		return ""
	}
}

func defaultPulseModuleCopy(key string) (string, string) {
	switch key {
	case pulseSourceTopicHot:
		return "关注 Topic 的今日推荐", "根据你订阅的主题生成今天值得展开的问题和切入点。"
	case pulseSourceMemory:
		return "近日 Memory 延展", "根据最近对话信号生成可以继续推进的上下文入口。"
	case pulseSourceInterestHot:
		return "可能感兴趣的近日热门", "结合 topic 与 memory 信号，生成你可能想追踪的热门方向。"
	default:
		return "Pulse 推荐", "今日预计算推荐。"
	}
}

func fallbackModuleCopy(key string, topics []models.PulseTopic, signals []memoryPulseSignal, searchErrors []string) (string, string) {
	searchIssue := "外网搜索暂不可用"
	if len(searchErrors) > 0 {
		searchIssue = "外网搜索失败"
	}
	switch key {
	case pulseSourceTopicHot:
		if len(topics) == 0 {
			return "还没有订阅 Topic", "添加 Topic 后，这里会定时生成你关注主题下的个性化推荐。"
		}
		return fmt.Sprintf("等待检索的 %d 个订阅 Topic", len(topics)), searchIssue + "，本次没有可核验来源，因此不展示推荐卡；搜索恢复后会重新生成。"
	case pulseSourceMemory:
		if len(signals) > 0 {
			return "等待检索的近日 Memory", fmt.Sprintf("%s；最近最强信号是「%s」，但本次没有可核验来源，因此不展示推荐卡。", searchIssue, signals[0].Theme)
		}
		return "等待更多 Memory 信号", searchIssue + "；继续使用工作台后，这里会基于近期对话和外网检索生成推荐。"
	case pulseSourceInterestHot:
		terms := collectInterestTerms(topics, signals)
		if len(terms) > 0 {
			return "等待检索的兴趣外扩", fmt.Sprintf("%s；「%s」等方向暂未拿到可核验来源，因此不展示推荐卡。", searchIssue, strings.Join(terms[:minInt(len(terms), 3)], " / "))
		}
		return "冷启动兴趣探索", searchIssue + "；等 topic、memory 和外网来源更充分后再生成推荐。"
	default:
		return defaultPulseModuleCopy(key)
	}
}

func moduleCategory(key string) string {
	switch key {
	case pulseSourceTopicHot:
		return "关注 Topic"
	case pulseSourceMemory:
		return "近日 Memory"
	case pulseSourceInterestHot:
		return "可能兴趣"
	default:
		return "Pulse"
	}
}

func scopePulseModels(userID string, modules []models.PulseModule, items []models.PulseItem) {
	userID = normalizedUserID(userID)
	for index := range modules {
		modules[index].UserID = userID
		if userID != "0" {
			modules[index].ID = pulseItemID(modules[index].Date, "module:"+userID, modules[index].Key)
		}
	}
	for index := range items {
		items[index].UserID = userID
		if userID != "0" {
			items[index].ID = pulseItemID(items[index].Date, items[index].Source+":"+userID, items[index].ID)
		}
	}
}

func sortPulseModules(modules []models.PulseModule) {
	order := map[string]int{}
	for index, key := range pulseModuleOrder {
		order[key] = index
	}
	sort.SliceStable(modules, func(i, j int) bool {
		return order[modules[i].Key] < order[modules[j].Key]
	})
}

func normalizeHeatScore(score int, source string, index int) int {
	if score <= 0 {
		base := map[string]int{
			pulseSourceTopicHot:    76,
			pulseSourceMemory:      72,
			pulseSourceInterestHot: 68,
		}[source]
		score = base - index*3
	}
	if score < 1 {
		return 1
	}
	if score > 100 {
		return 100
	}
	return score
}

func limitText(value string, limit int) string {
	value = strings.TrimSpace(value)
	if limit <= 0 {
		return value
	}
	runes := []rune(value)
	if len(runes) <= limit {
		return value
	}
	return string(runes[:limit-1]) + "..."
}

func pulseCompactSummary(value string) string {
	return pulseCompactSentences(value, 6, pulseSummaryMaxRunes)
}

func pulseCompactRecommendationReason(value string) string {
	return pulseCompactSentences(value, 1, pulseRecommendationMaxRunes)
}

func pulseCompactDetailContext(value string, repeatedValues ...string) string {
	value = pulseCompactSentences(value, 1, 120)
	if value == "" {
		return ""
	}
	normalized := strings.ToLower(strings.TrimSpace(value))
	for _, repeated := range repeatedValues {
		repeated = strings.ToLower(strings.TrimSpace(cleanSearchText(repeated)))
		if repeated == "" {
			continue
		}
		if normalized == repeated ||
			(len([]rune(normalized)) >= 12 && strings.Contains(repeated, normalized)) {
			return ""
		}
	}
	return value
}

func pulseCompactKeyPoints(values []string) []string {
	points := []string{}
	for _, value := range values {
		cleaned := cleanSearchText(value)
		normalized := strings.ToLower(cleaned)
		if cleaned == "" ||
			pulseTextHasAny(normalized, "推荐理由", "核验动作", "搜索来源", "http://", "https://") {
			continue
		}
		cleaned = pulseCompactSentences(cleaned, 1, 36)
		points = appendUniqueStrings(points, cleaned)
		if len(points) >= 3 {
			break
		}
	}
	return points
}

func pulseCompactSentences(value string, maxSentences int, maxRunes int) string {
	value = cleanSearchText(value)
	if value == "" || maxSentences <= 0 || maxRunes <= 0 {
		return ""
	}
	var builder strings.Builder
	sentenceCount := 0
	for _, r := range value {
		builder.WriteRune(r)
		if strings.ContainsRune("。！？!?", r) {
			sentenceCount++
			if sentenceCount >= maxSentences {
				break
			}
		}
	}
	compacted := strings.TrimSpace(builder.String())
	runes := []rune(compacted)
	if len(runes) > maxRunes {
		return string(runes[:maxRunes-1]) + "…"
	}
	return compacted
}

func metadataString(metadata map[string]interface{}, keys ...string) string {
	for _, key := range keys {
		value, ok := metadata[key]
		if !ok || value == nil {
			continue
		}
		switch typed := value.(type) {
		case string:
			if strings.TrimSpace(typed) != "" {
				return strings.TrimSpace(typed)
			}
		case fmt.Stringer:
			text := strings.TrimSpace(typed.String())
			if text != "" {
				return text
			}
		default:
			text := strings.TrimSpace(fmt.Sprint(typed))
			if text != "" && text != "<nil>" {
				return text
			}
		}
	}
	return ""
}

func pulseSearchPageMetadataString(metadata map[string]interface{}, key string) string {
	pageValue, ok := metadata["page"]
	if !ok || pageValue == nil {
		return ""
	}
	page, ok := pageValue.(map[string]interface{})
	if !ok {
		return ""
	}
	if value := metadataString(page, key); value != "" {
		return value
	}
	nestedValue, ok := page["metadata"]
	if !ok || nestedValue == nil {
		return ""
	}
	nested, ok := nestedValue.(map[string]interface{})
	if !ok {
		return ""
	}
	return metadataString(nested, key)
}

func parsePulsePublishedAt(value string) (time.Time, bool) {
	text := strings.TrimSpace(value)
	if text == "" {
		return time.Time{}, false
	}
	layouts := []string{
		time.RFC3339Nano,
		time.RFC3339,
		time.RFC1123,
		time.RFC1123Z,
		time.RFC822,
		time.RFC822Z,
		"2006-01-02T15:04:05",
		"2006-01-02",
		"2006/01/02",
		"2006.01.02",
		"Jan 2, 2006",
		"January 2, 2006",
		"2 Jan 2006",
		"2 January 2006",
	}
	for _, layout := range layouts {
		if parsed, err := time.Parse(layout, text); err == nil {
			return parsed.UTC(), true
		}
	}
	if match := pulseISODatePattern.FindString(text); match != "" {
		normalized := strings.ReplaceAll(strings.ReplaceAll(match, "/", "-"), ".", "-")
		if parsed, err := time.Parse("2006-1-2", normalized); err == nil {
			return parsed.UTC(), true
		}
	}
	if match := pulseChineseDatePattern.FindStringSubmatch(text); len(match) == 4 {
		normalized := fmt.Sprintf("%s-%s-%s", match[1], match[2], match[3])
		if parsed, err := time.Parse("2006-1-2", normalized); err == nil {
			return parsed.UTC(), true
		}
	}
	for _, pattern := range []*regexp.Regexp{pulseEnglishMonthDatePattern, pulseEnglishDayMonthDatePattern} {
		match := strings.TrimSpace(pattern.FindString(text))
		if match == "" {
			continue
		}
		for _, layout := range []string{"Jan 2, 2006", "January 2, 2006", "Jan 2 2006", "January 2 2006", "2 Jan 2006", "2 January 2006"} {
			if parsed, err := time.Parse(layout, match); err == nil {
				return parsed.UTC(), true
			}
		}
	}
	return time.Time{}, false
}

func pulseSearchResultPublishedAt(result pulseSearchResult) (time.Time, bool) {
	if publishedAt, ok := parsePulsePublishedAt(result.PublishedAt); ok {
		return publishedAt, true
	}
	// Search providers frequently omit the metadata field while retaining an
	// explicit publication date in the title or snippet. Recover only concrete
	// dates; never infer freshness merely from the query date.
	for _, value := range []string{result.Title, result.Snippet} {
		if publishedAt, ok := parsePulsePublishedAt(value); ok {
			return publishedAt, true
		}
	}
	return time.Time{}, false
}

func pulseFreshnessWindow(module string) time.Duration {
	if normalizePulseModuleKey(module) == pulseSourceMemory {
		return pulseMemoryFreshnessWindow
	}
	return pulseTopicFreshnessWindow
}

func pulseSearchResultHasStaleDate(date string, module string, result pulseSearchResult) bool {
	publishedAt, ok := pulseSearchResultPublishedAt(result)
	if !ok {
		return false
	}
	reference, err := time.Parse("2006-01-02", date)
	if err != nil {
		return false
	}
	return publishedAt.Before(reference.Add(-pulseFreshnessWindow(module))) ||
		publishedAt.After(reference.Add(pulseFutureDateTolerance))
}

func pulseSearchResultsFreshEnough(date string, module string, results []pulseSearchResult) bool {
	reference, err := time.Parse("2006-01-02", date)
	if err != nil {
		return false
	}
	allDomains := map[string]bool{}
	recentDomains := map[string]bool{}
	for _, result := range results {
		domain := pulseSourceDomainKey(result.URL)
		if domain == "" {
			continue
		}
		allDomains[domain] = true
		publishedAt, ok := pulseSearchResultPublishedAt(result)
		if !ok {
			continue
		}
		if publishedAt.Before(reference.Add(-pulseFreshnessWindow(module))) ||
			publishedAt.After(reference.Add(pulseFutureDateTolerance)) {
			// A known-stale source must not be rescued by one newer result. The
			// relaxed path applies only when the corroborating source is undated.
			return false
		}
		recentDomains[domain] = true
	}
	return len(allDomains) >= 2 && len(recentDomains) >= 1
}

func pulseNewsSourcesMeetQualityGate(date string, module string, sources []pulseNewsSource) bool {
	return len(pulseNewsSourceQualityIssues(date, module, sources)) == 0
}

func pulseKeywordDigestSourcesMeetQualityGate(date string, module string, sources []pulseNewsSource) bool {
	if len(sources) < 2 || len(sources) > pulseSearchClusterMaxSources {
		return false
	}
	results := pulseSearchResultsFromNewsSources(sources)
	if pulseSearchIndependentSourceCount(results) < 2 || pulseAllWeakSearchSources(results) {
		return false
	}
	return pulseSearchResultsFreshEnough(date, module, results)
}

func pulseItemSourceQualityIssues(date string, module string, evidenceMode string, sources []pulseNewsSource) []string {
	if evidenceMode == "keyword_digest" {
		if pulseKeywordDigestSourcesMeetQualityGate(date, module, sources) {
			return nil
		}
		return []string{"invalid_keyword_digest_sources"}
	}
	return pulseNewsSourceQualityIssues(date, module, sources)
}

func pulseNewsSourceQualityIssues(date string, module string, sources []pulseNewsSource) []string {
	issues := []string{}
	results := pulseSearchResultsFromNewsSources(sources)
	if len(results) == 1 && pulseTrustedSingletonMeetsQualityGate(date, module, results[0]) {
		return issues
	}
	if len(sources) < 2 || len(sources) > pulseSearchClusterMaxSources {
		issues = append(issues, "insufficient_sources")
	}
	if pulseSearchIndependentSourceCount(results) < 2 {
		issues = append(issues, "insufficient_independent_sources")
	}
	if len(results) > 0 && pulseAllWeakSearchSources(results) {
		issues = append(issues, "only_weak_sources")
	}
	if len(results) > 0 && !pulseSearchClusterHasTrustSignal(results) {
		issues = append(issues, "missing_trusted_source")
	}
	if len(results) > 0 && !pulseSearchClusterDescribesConcreteEvent(results) {
		issues = append(issues, "sources_do_not_describe_same_event")
	}
	if !pulseSearchResultsFreshEnough(date, module, results) {
		issues = append(issues, "insufficient_fresh_sources")
	}
	return issues
}

func pulseNewsCopyMeetsQualityGate(title string, summary string) bool {
	return len(pulseNewsCopyQualityIssues(title, summary)) == 0
}

func pulseItemCopyQualityIssues(evidenceMode string, title string, summary string) []string {
	if evidenceMode != "keyword_digest" {
		return pulseNewsCopyQualityIssues(title, summary)
	}
	title = cleanSearchText(title)
	summary = cleanSearchText(summary)
	issues := []string{}
	if title == "" {
		issues = append(issues, "missing_title")
	}
	if summary == "" {
		issues = append(issues, "missing_summary")
	}
	if title != "" && (pulseNewsCopyLooksGeneric(title) || pulseTitleLooksLikeSearchDump(title)) {
		issues = append(issues, "generic_title")
	}
	if summary != "" && (pulseNewsCopyLooksGeneric(summary) || pulseSummaryLooksLikeSearchDump(summary)) {
		issues = append(issues, "generic_summary")
	}
	if title != "" && !pulseTextHasAny(strings.ToLower(title), "趋势", "进展", "热点", "演进", "转向", "走向", "路线", "押注", "升温", "成为", "加速", "trend", "shift", "transition", "advance") {
		issues = append(issues, "digest_title_missing_direction")
	}
	if summary != "" && len([]rune(summary)) < pulseSummaryMinRunes {
		issues = append(issues, "summary_too_short")
	}
	return issues
}

func pulseNewsCopyQualityIssues(title string, summary string) []string {
	issues := []string{}
	title = cleanSearchText(title)
	summary = cleanSearchText(summary)
	if title == "" {
		issues = append(issues, "missing_title")
	}
	if summary == "" {
		issues = append(issues, "missing_summary")
	}
	if title != "" && pulseNewsCopyLooksGeneric(title) {
		issues = append(issues, "generic_title")
	}
	if summary != "" && pulseNewsCopyLooksGeneric(summary) {
		issues = append(issues, "generic_summary")
	}
	if title != "" && !pulseCopyContainsConcreteEvent(title) {
		issues = append(issues, "title_missing_concrete_event")
	}
	if title != "" && !pulseCopyHasIdentifiableSubject(title) {
		issues = append(issues, "title_missing_identifiable_subject")
	}
	if summary != "" && !pulseCopyContainsConcreteFact(summary) {
		issues = append(issues, "summary_missing_concrete_fact")
	}
	return issues
}

func pulseNewsCopyLooksGeneric(value string) bool {
	normalized := strings.ToLower(cleanSearchText(value))
	for _, fragment := range pulseGenericNewsCopyFragments {
		if strings.Contains(normalized, strings.ToLower(fragment)) {
			return true
		}
	}
	return false
}

func pulseCopyContainsConcreteEvent(value string) bool {
	return pulseConcreteEventIndex(value) >= 0
}

func pulseConcreteEventIndex(value string) int {
	normalized := strings.ToLower(cleanSearchText(value))
	best := -1
	if location := pulseGeneralAvailabilityPattern.FindStringIndex(normalized); len(location) == 2 {
		best = location[0]
	}
	for _, term := range pulseConcreteEventTerms {
		index := strings.Index(normalized, strings.ToLower(term))
		if index >= 0 && (best < 0 || index < best) {
			best = index
		}
	}
	return best
}

func pulseCopyHasIdentifiableSubject(value string) bool {
	cleaned := cleanSearchText(value)
	if pulseModelEntityPattern.MatchString(cleaned) {
		return true
	}
	for _, entity := range pulseKnownEntities {
		if pulseTextContainsFold(cleaned, entity) {
			return true
		}
	}

	eventIndex := pulseConcreteEventIndex(cleaned)
	if eventIndex <= 0 {
		return false
	}
	subject := strings.TrimSpace(cleaned[:eventIndex])
	for _, separator := range []string{"。", "；", ";", "，", ",", "：", ":"} {
		if index := strings.LastIndex(subject, separator); index >= 0 {
			subject = strings.TrimSpace(subject[index+len(separator):])
		}
	}
	for _, prefix := range []string{"据报道", "报道称", "消息显示", "多家来源称", "独立报告称", "官方消息称"} {
		subject = strings.TrimSpace(strings.TrimPrefix(subject, prefix))
	}
	normalizedSubject := strings.ToLower(strings.ReplaceAll(subject, " ", ""))
	genericSubjects := []string{
		"ai", "ai模型", "模型", "大模型", "agent", "智能体", "行业", "市场",
		"技术", "产品", "平台", "工具", "项目", "公司", "企业", "团队",
		"模型进展", "ai模型进展", "订阅topic", "可能兴趣方向", "近日关注延伸",
	}
	for _, generic := range genericSubjects {
		if normalizedSubject == strings.ToLower(strings.ReplaceAll(generic, " ", "")) {
			return false
		}
	}
	return len([]rune(subject)) >= 3
}

func pulseCopyContainsConcreteFact(summary string) bool {
	if !pulseCopyHasIdentifiableSubject(summary) {
		return false
	}
	if pulseCopyContainsConcreteEvent(summary) {
		return true
	}
	normalized := strings.ToLower(cleanSearchText(summary))
	factNouns := []string{
		"定价", "价格", "参数", "上下文窗口", "版本号", "发布日期", "估值",
		"营收", "利润", "用户数", "准确率", "排名", "price", "revenue",
		"valuation", "users", "accuracy",
	}
	hasFactNoun := false
	for _, noun := range factNouns {
		if strings.Contains(normalized, noun) {
			hasFactNoun = true
			break
		}
	}
	if !hasFactNoun {
		return false
	}
	for _, r := range normalized {
		if unicode.IsDigit(r) {
			return true
		}
	}
	return false
}

func pulseItemMeetsQualityGate(item models.PulseItem) bool {
	return len(pulseItemQualityIssues(item)) == 0
}

func pulseItemQualityIssues(item models.PulseItem) []string {
	var detail pulseItemDetail
	if item.DetailJSON == "" || json.Unmarshal([]byte(item.DetailJSON), &detail) != nil {
		return append(pulseNewsCopyQualityIssues(item.Title, item.Summary), "missing_or_invalid_detail")
	}
	issues := append([]string{}, pulseItemCopyQualityIssues(detail.EvidenceMode, item.Title, item.Summary)...)
	if detail.ContentVersion >= pulseContentVersion {
		issues = append(issues, pulseSummaryLengthIssues(item.Summary)...)
	}
	if detail.EvidenceMode == "keyword_digest" &&
		!pulseKeywordDigestTitleClaimsSupported(item.Title, detail.NewsSources) {
		issues = append(issues, "unsupported_digest_title_claim")
	}
	return append(issues, pulseItemSourceQualityIssues(item.Date, item.Source, detail.EvidenceMode, detail.NewsSources)...)
}

func pulseSummaryLengthIssues(summary string) []string {
	length := len([]rune(cleanSearchText(summary)))
	issues := []string{}
	if length < pulseSummaryMinRunes {
		issues = append(issues, "summary_too_short")
	}
	if length > pulseSummaryMaxRunes {
		issues = append(issues, "summary_too_long")
	}
	return issues
}

func filterPulseItemsForPublishing(items []models.PulseItem) []models.PulseItem {
	filtered, _ := filterPulseItemsForPublishingWithDiagnostics(items)
	return filtered
}

func filterPulseItemsForPublishingWithDiagnostics(items []models.PulseItem) ([]models.PulseItem, []pulseCandidateRejectionDiagnostic) {
	filtered := make([]models.PulseItem, 0, len(items))
	rejections := []pulseCandidateRejectionDiagnostic{}
	for _, item := range items {
		issues := pulseItemQualityIssues(item)
		if len(issues) == 0 {
			filtered = append(filtered, item)
			continue
		}
		var detail pulseItemDetail
		_ = json.Unmarshal([]byte(item.DetailJSON), &detail)
		rejections = append(rejections, pulseCandidateRejectionDiagnostic{
			Stage:         "publishing",
			Module:        item.Source,
			TopicID:       item.TopicID,
			TopicName:     item.TopicName,
			Title:         limitText(cleanSearchText(item.Title), 180),
			Reasons:       issues,
			SourceCount:   len(detail.NewsSources),
			SourceDomains: pulseNewsSourceDomains(detail.NewsSources),
		})
	}
	return filtered, rejections
}

func pulseNewsSourceDomains(sources []pulseNewsSource) []string {
	domains := []string{}
	for _, source := range sources {
		if domain := pulseSourceDomainKey(source.URL); domain != "" {
			domains = appendUniqueStrings(domains, domain)
		}
	}
	sort.Strings(domains)
	return domains
}

func pulseRejectionReasonCounts(rejections []pulseCandidateRejectionDiagnostic) map[string]int {
	counts := map[string]int{}
	for _, rejection := range rejections {
		for _, reason := range rejection.Reasons {
			counts[reason]++
		}
	}
	return counts
}

func revalidatePulseCachedItems(items []models.PulseItem) ([]models.PulseItem, []models.PulseItem) {
	current := make([]models.PulseItem, 0, len(items))
	upgrades := []models.PulseItem{}
	seenGroundedClusters := map[string]string{}
	for _, item := range items {
		validated, upgraded, ok := revalidatePulseCachedItem(item)
		if !ok {
			continue
		}
		var detail pulseItemDetail
		_ = json.Unmarshal([]byte(validated.DetailJSON), &detail)
		clusterKey := pulseGroundedSourceClusterKey(detail.NewsSources)
		if clusterKey != "" {
			if previousModule, exists := seenGroundedClusters[clusterKey]; exists && previousModule != validated.Source {
				// Old rows do not persist the generation evidence ID. Treat an
				// identical source set as a duplicate only when it crossed module
				// boundaries, which is the known failure mode. One source bundle can
				// legitimately support multiple distinct cards inside a module.
				continue
			}
			seenGroundedClusters[clusterKey] = validated.Source
		}
		current = append(current, validated)
		if upgraded {
			upgrades = append(upgrades, validated)
		}
	}
	return current, upgrades
}

func revalidatePulseCachedItem(item models.PulseItem) (models.PulseItem, bool, bool) {
	var detail pulseItemDetail
	if item.DetailJSON == "" || json.Unmarshal([]byte(item.DetailJSON), &detail) != nil {
		return models.PulseItem{}, false, false
	}
	if detail.ContentVersion > pulseContentVersion {
		return models.PulseItem{}, false, false
	}
	if detail.ContentVersion == pulseContentVersion {
		if !pulseCachedItemMeetsCurrentContract(item, detail) {
			return models.PulseItem{}, false, false
		}
		return item, false, true
	}

	// Legacy rows can remain visible when their evidence still passes today's
	// quality gate. Upgrade only their presentation shape; never bless a row
	// that the current source or low-information checks reject.
	if pulseItemLooksLowInformation(item) {
		return models.PulseItem{}, false, false
	}
	item.Summary = pulseCompactSummary(item.Summary)
	detail.ContentVersion = pulseContentVersion
	detail.RecommendationReason = pulseCompactRecommendationReason(detail.RecommendationReason)
	detail.Signals = limitStringSlice(detail.Signals, 6, 180)
	detail.QuickContext = pulseCompactDetailContext(
		detail.QuickContext,
		item.Summary,
		detail.RecommendationReason,
	)
	detail.KeyPoints = pulseCompactKeyPoints(detail.KeyPoints)
	detail.NewsSources = normalizeNewsSources(detail.NewsSources, pulseSearchClusterMaxSources)
	detail.SuggestedQuestions = personalizedPulseSuggestedQuestions(
		detail.SuggestedQuestions,
		pulseQuestionContext{
			Title:     item.Title,
			Summary:   item.Summary,
			Module:    item.Source,
			TopicName: item.TopicName,
			Category:  item.Category,
			KeyPoints: detail.KeyPoints,
			Context:   detail.QuickContext,
			Sources:   detail.NewsSources,
		},
	)
	item.DetailJSON = mustJSON(detail)
	if !pulseCachedItemMeetsCurrentContract(item, detail) {
		return models.PulseItem{}, false, false
	}
	return item, true, true
}

func pulseCachedItemMeetsCurrentContract(item models.PulseItem, detail pulseItemDetail) bool {
	if detail.ContentVersion != pulseContentVersion || pulseItemLooksLowInformation(item) {
		return false
	}
	if item.Summary == "" || item.Summary != pulseCompactSummary(item.Summary) {
		return false
	}
	if len(pulseSummaryLengthIssues(item.Summary)) > 0 {
		return false
	}
	if detail.RecommendationReason != pulseCompactRecommendationReason(detail.RecommendationReason) {
		return false
	}
	if len(detail.SuggestedQuestions) == 0 ||
		len(detail.SuggestedQuestions) > pulseSuggestedQuestionLimit {
		return false
	}
	for _, question := range detail.SuggestedQuestions {
		cleaned := cleanSearchText(question)
		if cleaned == "" ||
			len([]rune(cleaned)) > pulseSuggestedQuestionMaxRunes ||
			pulseQuestionLooksGeneric(cleaned) {
			return false
		}
	}
	return true
}

func persistPulseCachedItemUpgrades(items []models.PulseItem) error {
	if len(items) == 0 {
		return nil
	}
	return database.DB.Transaction(func(tx *gorm.DB) error {
		for _, item := range items {
			if err := tx.Model(&models.PulseItem{}).
				Where("id = ? AND user_id = ? AND date = ?", item.ID, item.UserID, item.Date).
				UpdateColumns(map[string]interface{}{
					"summary":     item.Summary,
					"detail_json": item.DetailJSON,
				}).Error; err != nil {
				return err
			}
		}
		return nil
	})
}

func pulseMinimumReplacementCount(existingVerifiedCount int) int {
	if existingVerifiedCount <= 0 {
		return 0
	}
	return maxInt(1, (existingVerifiedCount*2+2)/3)
}

func limitStringSlice(values []string, maxItems int, maxRunes int) []string {
	result := []string{}
	for _, value := range values {
		cleaned := limitText(value, maxRunes)
		if cleaned == "" {
			continue
		}
		result = appendUniqueStrings(result, cleaned)
		if len(result) >= maxItems {
			break
		}
	}
	return result
}

func firstNonEmptyPulse(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return strings.TrimSpace(value)
		}
	}
	return ""
}

func minInt(a int, b int) int {
	if a < b {
		return a
	}
	return b
}

func maxInt(a int, b int) int {
	if a > b {
		return a
	}
	return b
}

func hasSearchResults(evidence []pulseSearchEvidence) bool {
	for _, item := range evidence {
		if len(item.Results) > 0 {
			return true
		}
	}
	return false
}

func normalizeNewsSources(values []pulseNewsSource, maxItems int) []pulseNewsSource {
	if maxItems <= 0 {
		return nil
	}
	sources := []pulseNewsSource{}
	seen := map[string]bool{}
	for _, value := range values {
		url := strings.TrimSpace(value.URL)
		if !pulseSafeHTTPURL(url) {
			continue
		}
		key := strings.ToLower(url)
		if seen[key] {
			continue
		}
		seen[key] = true
		source := pulseNewsSource{
			Title:       limitText(firstNonEmptyPulse(cleanSearchText(value.Title), cleanSearchText(value.Source), url), 180),
			URL:         url,
			Source:      limitText(cleanSearchText(value.Source), 80),
			Snippet:     limitText(cleanSearchText(value.Snippet), 360),
			PublishedAt: limitText(value.PublishedAt, 80),
		}
		sources = append(sources, source)
		if len(sources) >= maxItems {
			break
		}
	}
	return sources
}

func cleanSearchText(value string) string {
	text := html.UnescapeString(strings.TrimSpace(value))
	if text == "" {
		return ""
	}
	var builder strings.Builder
	inTag := false
	for _, r := range text {
		switch r {
		case '<':
			inTag = true
			builder.WriteRune(' ')
		case '>':
			inTag = false
			builder.WriteRune(' ')
		default:
			if !inTag {
				builder.WriteRune(r)
			}
		}
	}
	return strings.Join(strings.Fields(builder.String()), " ")
}

func pulseSearchResultLooksUseful(title string, snippet string, rawURL string) bool {
	normalizedTitle := strings.ToLower(strings.TrimSpace(title))
	normalizedURL := strings.ToLower(strings.TrimSpace(rawURL))
	if normalizedTitle == "" || normalizedURL == "" {
		return false
	}
	if !pulseSafeHTTPURL(rawURL) {
		return false
	}
	if strings.Contains(normalizedTitle, "stock price") && (strings.Contains(normalizedURL, "finance.yahoo.com") || strings.Contains(normalizedURL, "google.com/finance")) {
		return false
	}
	parsed, err := url.Parse(rawURL)
	if err != nil {
		return true
	}
	host := strings.TrimPrefix(strings.ToLower(parsed.Hostname()), "www.")
	path := strings.TrimSpace(parsed.EscapedPath())
	if path == "" || path == "/" {
		switch host {
		case "openai.com", "chatgpt.com", "google.com", "microsoft.com":
			return false
		}
		if snippet == "" && (strings.Contains(normalizedTitle, "home") || strings.Contains(normalizedTitle, "official")) {
			return false
		}
	}
	return true
}

func pulseSearchResultRelevanceScore(query pulseSearchQuery, result pulseSearchResult) int {
	terms := pulseSearchRelevanceTerms(query)
	if len(terms) == 0 {
		return 0
	}
	score := 0
	for _, term := range terms {
		if pulseSearchTextContainsTerm(result.Title, term) {
			score += 5
		}
		if pulseSearchTextContainsTerm(result.Snippet, term) {
			score += 2
		}
		if pulseSearchTextContainsTerm(result.URL, term) {
			score++
		}
	}
	return score
}

func pulseSearchRelevanceTerms(query pulseSearchQuery) []string {
	values := []string{query.TopicName, query.Query}
	terms := []string{}
	seen := map[string]bool{}
	for _, value := range values {
		for _, part := range strings.FieldsFunc(value, func(r rune) bool {
			return unicode.IsSpace(r) || strings.ContainsRune(",，;；/、|｜:：()（）[]【】\"'“”", r)
		}) {
			term := strings.ToLower(strings.TrimSpace(part))
			term = strings.Trim(term, ".!?！？。")
			if pulseSearchTermLooksGeneric(term) || seen[term] {
				continue
			}
			seen[term] = true
			terms = append(terms, term)
		}
	}
	return terms
}

func pulseSearchTermLooksGeneric(term string) bool {
	if term == "" {
		return true
	}
	if _, err := strconv.Atoi(term); err == nil {
		return true
	}
	if pulseISODatePattern.MatchString(term) {
		return true
	}
	if !pulseTermHasHan(term) && len([]rune(term)) <= 2 {
		return true
	}
	generic := []string{
		"latest", "news", "recent", "update", "updates", "trend", "trends", "analysis", "emerging",
		"case", "study", "with", "from", "for", "and", "the", "after", "since", "new",
		"official", "release", "independent", "report", "research", "industry", "data",
		"company", "companies", "product", "products", "model", "models", "platform", "platforms",
		"service", "services", "technology", "software", "business", "enterprise", "team", "developer", "developers",
		"launch", "launches", "launched", "announce", "announces", "announced",
		"最新", "近期", "新闻", "资讯", "热门", "趋势", "分析", "外网", "相关",
		"公司", "企业", "产品", "模型", "平台", "服务", "技术", "软件", "团队", "开发者", "发布", "宣布",
	}
	for _, value := range generic {
		if term == value {
			return true
		}
	}
	return false
}

func pulseSearchTextContainsTerm(text string, term string) bool {
	haystack := strings.ToLower(strings.Join(strings.Fields(text), " "))
	term = strings.ToLower(strings.Join(strings.Fields(term), " "))
	if haystack == "" || term == "" {
		return false
	}
	if pulseTermHasHan(term) || len([]rune(term)) > 3 {
		return strings.Contains(haystack, term)
	}
	pattern := `(?i)(^|[^a-z0-9])` + regexp.QuoteMeta(term) + `($|[^a-z0-9])`
	return regexp.MustCompile(pattern).FindStringIndex(haystack) != nil
}

func pulseTermHasHan(term string) bool {
	for _, r := range term {
		if unicode.Is(unicode.Han, r) {
			return true
		}
	}
	return false
}

func newsSourcesFromSignals(signals []string, maxItems int) []pulseNewsSource {
	sources := []pulseNewsSource{}
	for _, signal := range signals {
		source, ok := newsSourceFromSignal(signal)
		if !ok {
			continue
		}
		sources = append(sources, source)
	}
	return normalizeNewsSources(sources, maxItems)
}

func newsSourceFromSignal(signal string) (pulseNewsSource, bool) {
	cleaned := strings.TrimSpace(signal)
	if cleaned == "" {
		return pulseNewsSource{}, false
	}
	index := strings.Index(strings.ToLower(cleaned), "https://")
	if index < 0 {
		index = strings.Index(strings.ToLower(cleaned), "http://")
	}
	if index < 0 {
		return pulseNewsSource{}, false
	}
	rawURL := cleaned[index:]
	if end := strings.IndexFunc(rawURL, unicode.IsSpace); end >= 0 {
		rawURL = rawURL[:end]
	}
	rawURL = strings.TrimRight(rawURL, "，,。.;；)")
	if rawURL == "" {
		return pulseNewsSource{}, false
	}
	title := strings.TrimSpace(cleaned[:index])
	title = strings.TrimPrefix(title, "搜索来源：")
	title = strings.TrimPrefix(title, "来源：")
	title = strings.TrimSpace(strings.Trim(title, "-—:： "))
	return pulseNewsSource{
		Title: firstNonEmptyPulse(title, rawURL),
		URL:   rawURL,
	}, true
}

func matchedKeywords(content string, keywords []string) []string {
	matched := []string{}
	for _, keyword := range keywords {
		if strings.Contains(content, strings.ToLower(keyword)) {
			matched = appendUniqueStrings(matched, keyword)
		}
	}
	return matched
}

func appendUniqueStrings(values []string, next ...string) []string {
	seen := map[string]bool{}
	for _, value := range values {
		seen[strings.ToLower(value)] = true
	}
	for _, value := range next {
		cleaned := strings.TrimSpace(value)
		if cleaned == "" {
			continue
		}
		key := strings.ToLower(cleaned)
		if seen[key] {
			continue
		}
		seen[key] = true
		values = append(values, cleaned)
	}
	return values
}

func compactSnippet(value string, limit int) string {
	cleaned := strings.Join(strings.Fields(value), " ")
	runes := []rune(cleaned)
	if len(runes) <= limit {
		return cleaned
	}
	if limit <= 1 {
		return string(runes[:limit])
	}
	return string(runes[:limit-1]) + "..."
}

func requestedPulseDate(value string) (string, bool) {
	if strings.TrimSpace(value) == "" {
		return time.Now().Format("2006-01-02"), true
	}
	parsed, err := time.Parse("2006-01-02", strings.TrimSpace(value))
	if err != nil {
		return "", false
	}
	return parsed.Format("2006-01-02"), true
}

func normalizeTopicName(value string) string {
	return strings.Join(strings.Fields(strings.TrimSpace(value)), " ")
}

func normalizeKeywords(values []string) []string {
	seen := map[string]bool{}
	keywords := make([]string, 0, len(values))
	for _, value := range values {
		parts := strings.FieldsFunc(value, func(r rune) bool {
			return r == ',' || r == '，' || r == ';' || r == '；' || r == '、' || r == '\n' || r == '\r'
		})
		for _, part := range parts {
			cleaned := strings.Join(strings.Fields(part), " ")
			if cleaned == "" {
				continue
			}
			runes := []rune(cleaned)
			if len(runes) == 1 && runes[0] <= unicode.MaxASCII && (unicode.IsLetter(runes[0]) || unicode.IsDigit(runes[0])) {
				continue
			}
			cleaned = limitText(cleaned, 60)
			key := strings.ToLower(cleaned)
			if seen[key] {
				continue
			}
			seen[key] = true
			keywords = append(keywords, cleaned)
			if len(keywords) >= 20 {
				break
			}
		}
		if len(keywords) >= 20 {
			break
		}
	}
	sort.Strings(keywords)
	return keywords
}

func encodeKeywords(values []string) string {
	payload, _ := json.Marshal(normalizeKeywords(values))
	return string(payload)
}

func decodeKeywords(value string) []string {
	var keywords []string
	if err := json.Unmarshal([]byte(value), &keywords); err != nil {
		return nil
	}
	return normalizeKeywords(keywords)
}

func topicResponses(topics []models.PulseTopic) []pulseTopicResponse {
	responses := make([]pulseTopicResponse, 0, len(topics))
	for _, topic := range topics {
		responses = append(responses, topicResponse(topic))
	}
	return responses
}

func topicResponse(topic models.PulseTopic) pulseTopicResponse {
	return pulseTopicResponse{
		ID:        topic.ID,
		Name:      topic.Name,
		Keywords:  decodeKeywords(topic.Keywords),
		CreatedAt: topic.CreatedAt,
		UpdatedAt: topic.UpdatedAt,
	}
}

func pulseClusterKey(item models.PulseItem) string {
	titleKey := pulseClusterTitleKey(item.Title)
	if titleKey == "" {
		return ""
	}
	parts := []string{
		normalizePulseModuleKey(item.Source),
		strings.ToLower(firstNonEmptyPulse(item.TopicID, item.TopicName, item.Category)),
		titleKey,
	}
	if domains := pulseItemSourceDomains(item, 3); len(domains) > 0 {
		parts = append(parts, strings.Join(domains, ","))
	}
	return fmt.Sprintf("cluster_%x", stableHash(strings.Join(parts, "|")))
}

func pulseEventClusterKey(event models.PulseEvent) string {
	if strings.TrimSpace(event.MetadataJSON) == "" {
		return ""
	}
	var metadata map[string]interface{}
	if err := json.Unmarshal([]byte(event.MetadataJSON), &metadata); err != nil {
		return ""
	}
	for _, key := range []string{"cluster_key", "clusterKey"} {
		if value, ok := metadata[key]; ok {
			cleaned := strings.TrimSpace(fmt.Sprint(value))
			if cleaned != "" {
				return cleaned
			}
		}
	}
	return ""
}

func pulseClusterTitleKey(value string) string {
	cleaned := strings.ToLower(cleanSearchText(value))
	if cleaned == "" {
		return ""
	}
	var builder strings.Builder
	lastSpace := false
	for _, r := range cleaned {
		switch {
		case unicode.IsLetter(r) || unicode.IsDigit(r) || unicode.Is(unicode.Han, r):
			builder.WriteRune(r)
			lastSpace = false
		case unicode.IsSpace(r):
			if !lastSpace && builder.Len() > 0 {
				builder.WriteRune(' ')
				lastSpace = true
			}
		}
	}
	return limitText(strings.TrimSpace(builder.String()), 80)
}

func pulseItemSourceDomains(item models.PulseItem, maxItems int) []string {
	var detail pulseItemDetail
	if item.DetailJSON != "" {
		_ = json.Unmarshal([]byte(item.DetailJSON), &detail)
	}
	domains := []string{}
	for _, source := range detail.NewsSources {
		if domain := pulseSourceDomainKey(source.URL); domain != "" {
			domains = appendUniqueStrings(domains, domain)
		}
		if len(domains) >= maxItems {
			break
		}
	}
	return domains
}

func pulseSourceDomainKey(rawURL string) string {
	if !pulseSafeHTTPURL(rawURL) {
		return ""
	}
	parsed, err := url.Parse(strings.TrimSpace(rawURL))
	if err != nil {
		return ""
	}
	host := strings.ToLower(parsed.Hostname())
	host = strings.TrimPrefix(host, "www.")
	if registrable, err := publicsuffix.EffectiveTLDPlusOne(host); err == nil && registrable != "" {
		host = registrable
	}
	publisherGroups := map[string]string{
		"ones.cn":         "publisher:ones",
		"ones.com.cn":     "publisher:ones",
		"google.com":      "publisher:google",
		"deepmind.google": "publisher:google",
		"openai.com":      "publisher:openai",
		"chatgpt.com":     "publisher:openai",
		"anthropic.com":   "publisher:anthropic",
		"claude.com":      "publisher:anthropic",
		"tencent.com":     "publisher:tencent",
		"qq.com":          "publisher:tencent",
		"meta.com":        "publisher:meta",
		"facebook.com":    "publisher:meta",
		"x.ai":            "publisher:xai",
		"x.com":           "publisher:xai",
	}
	if group := publisherGroups[host]; group != "" {
		return group
	}
	return host
}

func pulseSafeHTTPURL(rawURL string) bool {
	parsed, err := url.Parse(strings.TrimSpace(rawURL))
	scheme := strings.ToLower(parsed.Scheme)
	if err != nil ||
		(scheme != "http" && scheme != "https") ||
		parsed.Hostname() == "" ||
		parsed.User != nil {
		return false
	}
	host := strings.ToLower(parsed.Hostname())
	if host == "localhost" || strings.HasSuffix(host, ".localhost") || strings.HasSuffix(host, ".local") {
		return false
	}
	if ip := net.ParseIP(host); ip != nil &&
		(ip.IsLoopback() || ip.IsPrivate() || ip.IsUnspecified() || ip.IsLinkLocalUnicast() || ip.IsLinkLocalMulticast()) {
		return false
	}
	return true
}

type pulseFeatureState struct {
	feedbackByItem map[string]pulseItemFeedbackResponse
	feedbackByKey  map[string]pulseItemFeedbackResponse
	directScores   map[string]int
	clusterScores  map[string]int
	topicScores    map[string]int
	sourceScores   map[string]int
}

func loadPulseFeatureState(userID string, date string, items []models.PulseItem) (pulseFeatureState, error) {
	state := pulseFeatureState{
		feedbackByItem: map[string]pulseItemFeedbackResponse{},
		feedbackByKey:  map[string]pulseItemFeedbackResponse{},
		directScores:   map[string]int{},
		clusterScores:  map[string]int{},
		topicScores:    map[string]int{},
		sourceScores:   map[string]int{},
	}
	if len(items) == 0 {
		return state, nil
	}

	itemIDs := make([]string, 0, len(items))
	itemByID := map[string]models.PulseItem{}
	for _, item := range items {
		if item.ID == "" {
			continue
		}
		itemIDs = append(itemIDs, item.ID)
		itemByID[item.ID] = item
	}
	if len(itemIDs) == 0 {
		return state, nil
	}

	var events []models.PulseEvent
	err := database.DB.Where("user_id = ?", normalizedUserID(userID)).
		Order("created_at desc").
		Limit(pulseFeatureEventLimit).
		Find(&events).Error
	if err != nil {
		return state, err
	}
	sort.SliceStable(events, func(i, j int) bool {
		return events[i].CreatedAt.Before(events[j].CreatedAt)
	})

	featureReference := time.Now()
	explicitFeedbackByItem := map[string]pulseItemFeedbackResponse{}
	explicitFeedbackByCluster := map[string]pulseItemFeedbackResponse{}
	for _, event := range events {
		item, ok := itemByID[event.ItemID]
		clusterKey := pulseEventClusterKey(event)
		if clusterKey == "" && ok {
			clusterKey = pulseClusterKey(item)
		}
		if ok {
			feedback := state.feedbackByItem[event.ItemID]
			switch normalizePulseEventType(event.EventType) {
			case pulseEventExposure:
				if event.Value != 0 {
					feedback.ExposureCount++
				}
			case pulseEventOpen:
				if event.Value != 0 {
					feedback.OpenCount++
				}
			case pulseEventLike:
				feedback.Liked = event.Value > 0
				if event.Value > 0 {
					feedback.LikeCount = 1
				} else {
					feedback.LikeCount = 0
				}
			case pulseEventUpvote:
				if event.Value > 0 {
					feedback.Vote = "up"
					feedback.UpvoteCount = 1
					feedback.DownvoteCount = 0
				} else if feedback.Vote == "up" {
					feedback.Vote = ""
					feedback.UpvoteCount = 0
				}
			case pulseEventDownvote:
				if event.Value > 0 {
					feedback.Vote = "down"
					feedback.DownvoteCount = 1
					feedback.UpvoteCount = 0
				} else if feedback.Vote == "down" {
					feedback.Vote = ""
					feedback.DownvoteCount = 0
				}
			}
			state.feedbackByItem[event.ItemID] = feedback
		}
		if clusterKey != "" {
			feedback := state.feedbackByKey[clusterKey]
			switch normalizePulseEventType(event.EventType) {
			case pulseEventExposure:
				if event.Value != 0 {
					feedback.ExposureCount++
				}
			case pulseEventOpen:
				if event.Value != 0 {
					feedback.OpenCount++
				}
			case pulseEventLike:
				feedback.Liked = event.Value > 0
				if event.Value > 0 {
					feedback.LikeCount = 1
				} else {
					feedback.LikeCount = 0
				}
			case pulseEventUpvote:
				if event.Value > 0 {
					feedback.Vote = "up"
					feedback.UpvoteCount = 1
					feedback.DownvoteCount = 0
				} else if feedback.Vote == "up" {
					feedback.Vote = ""
					feedback.UpvoteCount = 0
				}
			case pulseEventDownvote:
				if event.Value > 0 {
					feedback.Vote = "down"
					feedback.DownvoteCount = 1
					feedback.UpvoteCount = 0
				} else if feedback.Vote == "down" {
					feedback.Vote = ""
					feedback.DownvoteCount = 0
				}
			}
			state.feedbackByKey[clusterKey] = feedback
		}

		eventType := normalizePulseEventType(event.EventType)
		if eventType == pulseEventExposure || eventType == pulseEventOpen {
			weight := pulseTimeDecayedEventWeight(event, featureReference)
			if ok {
				state.directScores[event.ItemID] += weight
			}
			if clusterKey != "" {
				state.clusterScores[clusterKey] += weight
			}
			topicID := firstNonEmptyPulse(event.TopicID, item.TopicID)
			if topicID != "" {
				state.topicScores["id:"+topicID] += weight / 2
			} else {
				topicName := firstNonEmptyPulse(event.TopicName, item.TopicName)
				if topicName != "" {
					state.topicScores["name:"+strings.ToLower(topicName)] += weight / 2
				}
			}
			if source := normalizePulseModuleKey(firstNonEmptyPulse(event.Source, item.Source)); source != "" {
				state.sourceScores[source] += weight / 3
			}
		} else if eventType == pulseEventLike || eventType == pulseEventUpvote || eventType == pulseEventDownvote {
			previous := explicitFeedbackByItem[event.ItemID]
			current := pulseApplyExplicitFeedback(previous, eventType, event.Value)
			explicitFeedbackByItem[event.ItemID] = current
			delta := pulseExplicitFeedbackWeight(current) - pulseExplicitFeedbackWeight(previous)
			if ok {
				state.directScores[event.ItemID] += delta
			}
			topicID := firstNonEmptyPulse(event.TopicID, item.TopicID)
			if topicID != "" {
				state.topicScores["id:"+topicID] += delta / 2
			} else {
				topicName := firstNonEmptyPulse(event.TopicName, item.TopicName)
				if topicName != "" {
					state.topicScores["name:"+strings.ToLower(topicName)] += delta / 2
				}
			}
			if source := normalizePulseModuleKey(firstNonEmptyPulse(event.Source, item.Source)); source != "" {
				state.sourceScores[source] += delta / 3
			}
			if clusterKey != "" {
				previousCluster := explicitFeedbackByCluster[clusterKey]
				currentCluster := pulseApplyExplicitFeedback(previousCluster, eventType, event.Value)
				explicitFeedbackByCluster[clusterKey] = currentCluster
				state.clusterScores[clusterKey] += pulseExplicitFeedbackWeight(currentCluster) -
					pulseExplicitFeedbackWeight(previousCluster)
			}
		}
	}
	return state, nil
}

func pulseApplyExplicitFeedback(feedback pulseItemFeedbackResponse, eventType string, value int) pulseItemFeedbackResponse {
	switch eventType {
	case pulseEventLike:
		feedback.Liked = value > 0
	case pulseEventUpvote:
		if value > 0 {
			feedback.Vote = "up"
		} else if feedback.Vote == "up" {
			feedback.Vote = ""
		}
	case pulseEventDownvote:
		if value > 0 {
			feedback.Vote = "down"
		} else if feedback.Vote == "down" {
			feedback.Vote = ""
		}
	}
	return feedback
}

func pulseExplicitFeedbackWeight(feedback pulseItemFeedbackResponse) int {
	weight := 0
	if feedback.Liked {
		weight += 16
	}
	switch feedback.Vote {
	case "up":
		weight += 22
	case "down":
		weight -= 28
	}
	return weight
}

func (state pulseFeatureState) feedbackFor(itemID string) pulseItemFeedbackResponse {
	if state.feedbackByItem == nil {
		return pulseItemFeedbackResponse{}
	}
	return state.feedbackByItem[itemID]
}

func (state pulseFeatureState) scoreFor(item models.PulseItem) int {
	score := item.HeatScore
	directScore := 0
	if state.directScores != nil {
		directScore = state.directScores[item.ID]
		score += directScore
	}
	if directScore == 0 && state.clusterScores != nil {
		score += state.clusterScores[pulseClusterKey(item)]
	}
	if state.topicScores != nil {
		if item.TopicID != "" {
			score += state.topicScores["id:"+item.TopicID]
		} else if item.TopicName != "" {
			score += state.topicScores["name:"+strings.ToLower(item.TopicName)]
		}
	}
	if state.sourceScores != nil {
		score += state.sourceScores[normalizePulseModuleKey(item.Source)]
	}
	if score < 1 {
		return 1
	}
	if score > 140 {
		return 140
	}
	return score
}

func rankPulseItems(items []models.PulseItem, featureState pulseFeatureState) []models.PulseItem {
	ranked := append([]models.PulseItem(nil), items...)
	sort.SliceStable(ranked, func(i, j int) bool {
		leftScore := featureState.scoreFor(ranked[i])
		rightScore := featureState.scoreFor(ranked[j])
		if leftScore == rightScore {
			if ranked[i].HeatScore == ranked[j].HeatScore {
				return ranked[i].CreatedAt.Before(ranked[j].CreatedAt)
			}
			return ranked[i].HeatScore > ranked[j].HeatScore
		}
		return leftScore > rightScore
	})
	return ranked
}

func recommendedPulseItems(items []models.PulseItem, featureState pulseFeatureState) []models.PulseItem {
	ranked := rankPulseItems(items, featureState)
	eligible := make([]models.PulseItem, 0, len(ranked))
	seenClusters := map[string]bool{}
	for _, item := range ranked {
		if pulseItemLooksLowInformation(item) || featureState.shouldFilter(item) {
			continue
		}
		if key := pulseClusterKey(item); key != "" {
			if seenClusters[key] {
				continue
			}
			seenClusters[key] = true
		}
		eligible = append(eligible, item)
	}
	return diversifyPulseItems(eligible, pulseVisibleItemLimit)
}

func diversifyPulseItems(ranked []models.PulseItem, limit int) []models.PulseItem {
	if limit <= 0 || len(ranked) == 0 {
		return nil
	}
	selected := map[string]bool{}
	topicCounts := map[string]int{}
	moduleQueues := map[string][]models.PulseItem{}
	for _, item := range ranked {
		moduleQueues[normalizePulseModuleKey(item.Source)] = append(moduleQueues[normalizePulseModuleKey(item.Source)], item)
	}
	add := func(item models.PulseItem) bool {
		if item.ID == "" || selected[item.ID] || len(selected) >= limit {
			return false
		}
		selected[item.ID] = true
		if topicKey := pulseItemTopicDiversityKey(item); topicKey != "" {
			topicCounts[topicKey]++
		}
		return true
	}

	for round := 0; round < 2; round++ {
		for _, module := range pulseModuleOrder {
			queue := moduleQueues[module]
			if round < len(queue) {
				add(queue[round])
			}
		}
	}
	deferred := []models.PulseItem{}
	for _, item := range ranked {
		if selected[item.ID] {
			continue
		}
		topicKey := pulseItemTopicDiversityKey(item)
		if topicKey != "" && topicCounts[topicKey] >= 2 {
			deferred = append(deferred, item)
			continue
		}
		add(item)
	}
	for _, item := range deferred {
		add(item)
	}

	result := make([]models.PulseItem, 0, minInt(len(selected), limit))
	for _, item := range ranked {
		if selected[item.ID] {
			result = append(result, item)
		}
	}
	return result
}

func pulseItemTopicDiversityKey(item models.PulseItem) string {
	if strings.TrimSpace(item.TopicID) != "" {
		return "id:" + strings.TrimSpace(item.TopicID)
	}
	if strings.TrimSpace(item.TopicName) != "" {
		return "name:" + strings.ToLower(strings.TrimSpace(item.TopicName))
	}
	return ""
}

func pulseItemLooksLowInformation(item models.PulseItem) bool {
	if !pulseItemMeetsQualityGate(item) {
		return true
	}
	var detail pulseItemDetail
	if item.DetailJSON != "" {
		_ = json.Unmarshal([]byte(item.DetailJSON), &detail)
	}
	text := strings.ToLower(strings.Join([]string{
		item.Title,
		item.Summary,
		detail.RecommendationReason,
		detail.QuickContext,
		strings.Join(detail.Signals, " "),
		strings.Join(detail.KeyPoints, " "),
	}, " "))
	return pulseTextHasAny(
		text,
		"待核验线索",
		"单一来源",
		"单一弱证据来源",
		"不足以判断",
		"无有效结果",
		"搜索失败",
		"没有可核验来源",
	)
}

func (state pulseFeatureState) shouldFilter(item models.PulseItem) bool {
	feedback := state.feedbackFor(item.ID)
	if feedback.Vote == "down" {
		return true
	}
	if feedback.OpenCount >= pulseOpenFilterThreshold {
		return true
	}
	if feedback.ExposureCount >= pulseExposureFilterThreshold {
		return true
	}
	clusterFeedback := state.feedbackByKey[pulseClusterKey(item)]
	if clusterFeedback.Vote == "down" {
		return true
	}
	if clusterFeedback.OpenCount >= pulseOpenFilterThreshold {
		return true
	}
	return clusterFeedback.ExposureCount >= pulseExposureFilterThreshold
}

func pulseEventFeatureWeight(event models.PulseEvent) int {
	if event.Value == 0 {
		switch normalizePulseEventType(event.EventType) {
		case pulseEventLike:
			return -16
		case pulseEventUpvote:
			return -22
		case pulseEventDownvote:
			return 28
		default:
			return 0
		}
	}
	if event.Value < 0 {
		switch normalizePulseEventType(event.EventType) {
		case pulseEventLike:
			return -16
		case pulseEventUpvote:
			return -22
		case pulseEventDownvote:
			return -28
		default:
			return 0
		}
	}
	switch normalizePulseEventType(event.EventType) {
	case pulseEventExposure:
		return -1
	case pulseEventOpen:
		return 8
	case pulseEventLike:
		return 16
	case pulseEventUpvote:
		return 22
	case pulseEventDownvote:
		return -28
	default:
		return 0
	}
}

func pulseTimeDecayedEventWeight(event models.PulseEvent, reference time.Time) int {
	weight := pulseEventFeatureWeight(event)
	if weight == 0 || event.CreatedAt.IsZero() {
		return weight
	}
	switch normalizePulseEventType(event.EventType) {
	case pulseEventLike, pulseEventUpvote, pulseEventDownvote:
		// Explicit preferences remain stable until the matching undo event arrives.
		return weight
	}
	age := reference.Sub(event.CreatedAt)
	switch {
	case age <= 7*24*time.Hour:
		return weight
	case age <= 30*24*time.Hour:
		return weight / 2
	case age <= 90*24*time.Hour:
		return weight / 4
	default:
		return 0
	}
}

func normalizePulseEventType(value string) string {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case pulseEventExposure, "impression", "view":
		return pulseEventExposure
	case pulseEventOpen, "click":
		return pulseEventOpen
	case pulseEventLike, "favorite", "fav":
		return pulseEventLike
	case pulseEventUpvote, "up", "thumb_up", "thumbs_up":
		return pulseEventUpvote
	case pulseEventDownvote, "down", "dislike", "thumb_down", "thumbs_down":
		return pulseEventDownvote
	default:
		return ""
	}
}

func defaultPulseEventValue(eventType string) int {
	return 1
}

func normalizePulseEventValue(eventType string, value int) int {
	if value == 0 {
		return 0
	}
	switch normalizePulseEventType(eventType) {
	case pulseEventDownvote:
		if value < 0 {
			return 1
		}
		return 1
	default:
		if value < 0 {
			return -1
		}
		return 1
	}
}

func pulseRecommendationNote(item models.PulseItem) string {
	focus := firstNonEmptyPulse(item.TopicName, item.Category, moduleCategory(item.Source))
	switch normalizePulseModuleKey(item.Source) {
	case pulseSourceTopicHot:
		if focus != "" {
			return fmt.Sprintf("可能对「%s」推荐", focus)
		}
		return "可能对已订阅 Topic 推荐"
	case pulseSourceMemory:
		return "可能对近期 Memory 推荐"
	case pulseSourceInterestHot:
		if focus != "" && focus != moduleCategory(item.Source) {
			return fmt.Sprintf("可能对「%s」延伸推荐", focus)
		}
		return "可能对兴趣外扩推荐"
	default:
		if focus != "" {
			return fmt.Sprintf("可能对「%s」推荐", focus)
		}
		return "可能对你推荐"
	}
}

type pulseRelatedCandidate struct {
	item   models.PulseItem
	score  int
	reason string
}

func buildPulseRelatedClusters(item models.PulseItem, allItems []models.PulseItem) []pulseRelatedClusterResponse {
	if len(allItems) <= 1 {
		return nil
	}

	baseTerms := pulseClusterTerms(item)
	candidates := []pulseRelatedCandidate{}
	for _, candidate := range allItems {
		if candidate.ID == "" || candidate.ID == item.ID {
			continue
		}
		score, reason := pulseClusterRelationScore(item, candidate, baseTerms, pulseClusterTerms(candidate))
		if score < 18 {
			continue
		}
		candidates = append(candidates, pulseRelatedCandidate{item: candidate, score: score, reason: reason})
	}
	sort.SliceStable(candidates, func(i, j int) bool {
		if candidates[i].score == candidates[j].score {
			if candidates[i].item.HeatScore == candidates[j].item.HeatScore {
				return candidates[i].item.CreatedAt.Before(candidates[j].item.CreatedAt)
			}
			return candidates[i].item.HeatScore > candidates[j].item.HeatScore
		}
		return candidates[i].score > candidates[j].score
	})

	related := make([]pulseRelatedClusterResponse, 0, minInt(len(candidates), 3))
	for _, candidate := range candidates[:minInt(len(candidates), 3)] {
		related = append(related, pulseRelatedClusterResponse{
			ID:        candidate.item.ID,
			Source:    candidate.item.Source,
			TopicName: candidate.item.TopicName,
			Title:     candidate.item.Title,
			Summary:   limitText(candidate.item.Summary, 180),
			Reason:    candidate.reason,
			HeatScore: candidate.item.HeatScore,
		})
	}
	return related
}

func pulseClusterRelationScore(item models.PulseItem, candidate models.PulseItem, baseTerms []string, candidateTerms []string) (int, string) {
	score := candidate.HeatScore / 12
	reasons := []string{}

	if item.TopicID != "" && item.TopicID == candidate.TopicID {
		score += 46
		reasons = append(reasons, fmt.Sprintf("同属「%s」topic", firstNonEmptyPulse(item.TopicName, candidate.TopicName)))
	} else if item.TopicName != "" && strings.EqualFold(item.TopicName, candidate.TopicName) {
		score += 38
		reasons = append(reasons, fmt.Sprintf("同属「%s」topic", item.TopicName))
	}
	if normalizePulseModuleKey(item.Source) != "" && normalizePulseModuleKey(item.Source) == normalizePulseModuleKey(candidate.Source) {
		score += 12
		reasons = append(reasons, "同一推荐模块")
	}
	if item.Category != "" && strings.EqualFold(item.Category, candidate.Category) {
		score += 8
	}

	overlap := intersectPulseTerms(baseTerms, candidateTerms)
	if len(overlap) > 0 {
		score += minInt(len(overlap), 4) * 14
		reasons = append(reasons, fmt.Sprintf("共享「%s」线索", strings.Join(overlap[:minInt(len(overlap), 3)], " / ")))
	}
	if len(reasons) == 0 && score >= 18 {
		reasons = append(reasons, "同一批信息流里的高热相邻簇")
	}
	return score, strings.Join(limitStringSlice(reasons, 2, 80), "；")
}

func pulseClusterTerms(item models.PulseItem) []string {
	var detail pulseItemDetail
	_ = json.Unmarshal([]byte(item.DetailJSON), &detail)
	values := []string{item.TopicName, item.Category, item.Title, item.Summary, detail.QuickContext}
	values = append(values, detail.KeyPoints...)

	terms := []string{}
	for _, value := range values {
		terms = appendUniqueStrings(terms, pulseKeywordsFromText(value)...)
		terms = appendUniqueStrings(terms, pulseClusterHintTerms(value)...)
	}
	return limitStringSlice(terms, 14, 32)
}

func pulseClusterHintTerms(value string) []string {
	text := strings.ToLower(value)
	hints := []string{
		"AI", "Agent", "RAG", "AIGC", "LLM", "OpenAI", "Claude", "Gemini", "GPT", "DeepSeek", "Qwen", "Kimi",
		"多模态", "推理", "模型能力", "工具调用", "工作流", "知识库", "向量检索", "推荐系统",
		"机器人", "具身智能", "人形机器人", "供应链", "量产", "VLA",
		"投资", "估值", "商业模式", "增长", "留存", "健康", "减脂", "训练",
	}
	terms := []string{}
	for _, hint := range hints {
		if strings.Contains(text, strings.ToLower(hint)) {
			terms = appendUniqueStrings(terms, hint)
		}
	}
	for _, entity := range pulseKnownEntities {
		if strings.Contains(text, strings.ToLower(entity)) {
			terms = appendUniqueStrings(terms, entity)
		}
	}
	return terms
}

func intersectPulseTerms(left []string, right []string) []string {
	rightSet := map[string]bool{}
	for _, value := range right {
		key := strings.ToLower(value)
		if key != "" {
			rightSet[key] = true
		}
	}
	overlap := []string{}
	for _, value := range left {
		key := strings.ToLower(value)
		if key == "" || !rightSet[key] {
			continue
		}
		overlap = appendUniqueStrings(overlap, value)
	}
	return limitStringSlice(overlap, 16, 32)
}

func moduleResponses(modules []models.PulseModule, items []models.PulseItem) []pulseModuleResponse {
	return moduleResponsesWithFeatures(modules, items, items, pulseFeatureState{})
}

func moduleResponsesWithFeatures(modules []models.PulseModule, items []models.PulseItem, allItems []models.PulseItem, featureState pulseFeatureState) []pulseModuleResponse {
	if len(modules) == 0 {
		for _, key := range pulseModuleOrder {
			title, summary := defaultPulseModuleCopy(key)
			modules = append(modules, models.PulseModule{
				Key:     key,
				Title:   title,
				Summary: summary,
			})
		}
	}
	sortPulseModules(modules)

	itemsBySource := map[string][]models.PulseItem{}
	for _, item := range items {
		itemsBySource[normalizePulseModuleKey(item.Source)] = append(itemsBySource[normalizePulseModuleKey(item.Source)], item)
	}

	responses := make([]pulseModuleResponse, 0, len(modules))
	seen := map[string]bool{}
	for _, module := range modules {
		key := normalizePulseModuleKey(module.Key)
		if key == "" || seen[key] {
			continue
		}
		seen[key] = true
		moduleItems := itemsBySource[key]
		sort.SliceStable(moduleItems, func(i, j int) bool {
			if moduleItems[i].HeatScore == moduleItems[j].HeatScore {
				return moduleItems[i].CreatedAt.Before(moduleItems[j].CreatedAt)
			}
			return moduleItems[i].HeatScore > moduleItems[j].HeatScore
		})
		responses = append(responses, pulseModuleResponse{
			Key:     key,
			Title:   module.Title,
			Summary: module.Summary,
			Items:   itemResponsesWithFeatures(moduleItems, allItems, featureState),
		})
	}
	return responses
}

func itemResponses(items []models.PulseItem) []pulseItemResponse {
	return itemResponsesWithFeatures(items, items, pulseFeatureState{})
}

func itemResponsesWithFeatures(items []models.PulseItem, allItems []models.PulseItem, featureState pulseFeatureState) []pulseItemResponse {
	responses := make([]pulseItemResponse, 0, len(items))
	for _, item := range items {
		responses = append(responses, itemResponse(item, allItems, featureState))
	}
	return responses
}

func itemResponse(item models.PulseItem, allItems []models.PulseItem, featureState pulseFeatureState) pulseItemResponse {
	var detail pulseItemDetail
	_ = json.Unmarshal([]byte(item.DetailJSON), &detail)
	return pulseItemResponse{
		ID:                 item.ID,
		ClusterKey:         pulseClusterKey(item),
		Date:               item.Date,
		TopicID:            item.TopicID,
		TopicName:          item.TopicName,
		Source:             item.Source,
		Category:           item.Category,
		Title:              item.Title,
		Summary:            item.Summary,
		HeatScore:          item.HeatScore,
		Detail:             detail,
		ExplorePrompt:      item.ExplorePrompt,
		RelatedClusters:    buildPulseRelatedClusters(item, allItems),
		Feedback:           featureState.feedbackFor(item.ID),
		FeatureScore:       featureState.scoreFor(item),
		RecommendationNote: pulseRecommendationNote(item),
		CreatedAt:          item.CreatedAt,
		UpdatedAt:          item.UpdatedAt,
	}
}

func mustJSON(value interface{}) string {
	payload, _ := json.Marshal(value)
	return string(payload)
}

func pulseItemID(date string, source string, key string) string {
	return fmt.Sprintf("pulse_%x", stableHash(date+":"+source+":"+key))
}

func stableIndex(seed string, size int) int {
	if size <= 0 {
		return 0
	}
	return int(stableHash(seed) % uint32(size))
}

func stableHash(value string) uint32 {
	h := fnv.New32a()
	_, _ = h.Write([]byte(value))
	return h.Sum32()
}
