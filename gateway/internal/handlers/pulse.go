package handlers

import (
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

type generatedPulseModule struct {
	Key     string               `json:"key"`
	Title   string               `json:"title"`
	Summary string               `json:"summary"`
	Items   []generatedPulseItem `json:"items"`
}

type generatedPulseItem struct {
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
	TopicID   string `json:"topic_id,omitempty"`
	TopicName string `json:"topic_name,omitempty"`
}

type pulseSearchEvidence struct {
	QueryID        string              `json:"query_id"`
	Module         string              `json:"module"`
	Query          string              `json:"query"`
	Intent         string              `json:"intent"`
	TopicID        string              `json:"topic_id,omitempty"`
	TopicName      string              `json:"topic_name,omitempty"`
	ProviderErrors []string            `json:"provider_errors,omitempty"`
	Results        []pulseSearchResult `json:"results"`
	Error          string              `json:"error,omitempty"`
}

type pulseSearchResult struct {
	Title       string `json:"title"`
	Snippet     string `json:"snippet,omitempty"`
	URL         string `json:"url,omitempty"`
	Source      string `json:"source,omitempty"`
	PublishedAt string `json:"published_at,omitempty"`
}

type pulseRetrievalDiagnostics struct {
	Queries []pulseRetrievalQueryDiagnostic `json:"queries"`
}

type pulseRetrievalQueryDiagnostic struct {
	QueryID        string                           `json:"query_id"`
	Module         string                           `json:"module"`
	Query          string                           `json:"query"`
	Intent         string                           `json:"intent"`
	TopicID        string                           `json:"topic_id,omitempty"`
	TopicName      string                           `json:"topic_name,omitempty"`
	ResultCount    int                              `json:"result_count"`
	Error          string                           `json:"error,omitempty"`
	ProviderErrors []string                         `json:"provider_errors,omitempty"`
	Results        []pulseRetrievalResultDiagnostic `json:"results,omitempty"`
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

const (
	pulseSourceTopicHot    = "topic_hot"
	pulseSourceMemory      = "memory"
	pulseSourceInterestHot = "interest_hot"

	pulseEventExposure = "exposure"
	pulseEventOpen     = "open"
	pulseEventLike     = "like"
	pulseEventUpvote   = "upvote"
	pulseEventDownvote = "downvote"

	pulseSchedulerTickInterval      = 30 * time.Minute
	pulseScheduledRefreshInterval   = 6 * time.Hour
	pulseActiveAccountWindow        = 7 * 24 * time.Hour
	pulseAutomaticFailureRetryBase  = 12 * time.Hour
	pulseAutomaticFailureRetryLimit = 24 * time.Hour
	pulseSearchQueryLimit           = 16
	pulseSearchTopicQueryBudget     = 8
	pulseSearchMemoryQueryBudget    = 4
	pulseSearchInterestQueryBudget  = 4
	pulseSearchResultLimit          = 6
	pulseSearchRawResultLimit       = 8
	pulseSearchFollowupSeedLimit    = 6
	pulseSearchFollowupResultLimit  = 6
	pulseSearchExpandedResultLimit  = 10
	pulseSearchClusterMaxSources    = 5
	pulseCandidateTargetCount       = 12
	pulseCandidateMaxCount          = 18
	pulseVisibleItemLimit           = 12
	pulseOpenFilterThreshold        = 3
	pulseExposureFilterThreshold    = 8
	pulseFeatureEventLimit          = 1000
	pulseTopicFreshnessWindow       = 72 * time.Hour
	pulseMemoryFreshnessWindow      = 30 * 24 * time.Hour
	pulseWelcomeSuggestionMaxAge    = 7 * 24 * time.Hour
	pulseRetrievalHistoryRetention  = 90 * 24 * time.Hour
	pulseFutureDateTolerance        = 48 * time.Hour
	pulseSuggestedQuestionLimit     = 3
	pulseSuggestedQuestionMaxRunes  = 32
	pulseRecommendationMaxRunes     = 56
	pulseSummaryMaxRunes            = 180
	pulseContentVersion             = 2
	pulseGenerationStagePreparing   = "preparing"
	pulseGenerationStageSearching   = "searching"
	pulseGenerationStageSummarizing = "summarizing"
	pulseGenerationStageSaving      = "saving"
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
var pulseISODatePattern = regexp.MustCompile(`\b(20[0-9]{2})[-/.](0?[1-9]|1[0-2])[-/.](0?[1-9]|[12][0-9]|3[01])\b`)
var pulseChineseDatePattern = regexp.MustCompile(`(20[0-9]{2})年(0?[1-9]|1[0-2])月(0?[1-9]|[12][0-9]|3[01])日`)

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
	"released", "releases", "release", "launched", "launches", "launch",
	"announced", "announces", "announce", "unveiled", "unveils", "unveil",
	"updated", "updates", "upgraded", "acquired", "acquires", "acquire",
	"funded", "funding", "partnered", "partners", "deployed", "deploys",
	"expanded", "expands", "integrated", "integrates", "discontinued",
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
	searchEvidence, searchErrors := h.collectPulseSearchEvidence(date, topics, memorySignals)
	h.updatePulseGenerationStage(date, userID, pulseGenerationStageSummarizing)
	modules, items, err := h.generatePulse(date, userID, topics, memorySignals, searchEvidence, searchErrors)
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
	items = filterPulseItemsForPublishing(items)
	if len(items) != originalItemCount {
		slog.Warn(
			"Pulse quality gate removed unverified items",
			"date", date,
			"user_id", userID,
			"removed", originalItemCount-len(items),
			"remaining", len(items),
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
	issues := []string{}
	if !pulseNewsCopyMeetsQualityGate(item.Title, item.Summary) {
		issues = append(issues, "copy_not_specific")
	}
	var detail pulseItemDetail
	if item.DetailJSON == "" || json.Unmarshal([]byte(item.DetailJSON), &detail) != nil {
		return append(issues, "missing_or_invalid_detail"), nil
	}
	sources := normalizeNewsSources(detail.NewsSources, pulseSearchClusterMaxSources)
	results := pulseSearchResultsFromNewsSources(sources)
	if len(sources) < 2 {
		issues = append(issues, "insufficient_sources")
	}
	if pulseSearchIndependentSourceCount(results) < 2 {
		issues = append(issues, "insufficient_independent_sources")
	}
	if len(results) > 0 && pulseAllWeakSearchSources(results) {
		issues = append(issues, "only_weak_sources")
	}
	if len(results) > 0 && !pulseSearchClusterDescribesConcreteEvent(results) {
		issues = append(issues, "no_concrete_event")
	}
	if !pulseSearchResultsFreshEnough(item.Date, item.Source, results) {
		issues = append(issues, "insufficient_fresh_sources")
	}
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
				"query_id":     query.QueryID,
				"module":       query.Module,
				"query":        query.Query,
				"intent":       query.Intent,
				"topic_id":     query.TopicID,
				"topic_name":   query.TopicName,
				"result_count": query.ResultCount,
				"error":        query.Error,
				"results":      results,
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
	generationErr error,
) error {
	diagnostics := pulseRetrievalDiagnostics{Queries: []pulseRetrievalQueryDiagnostic{}}
	successfulQueries := 0
	resultCount := 0
	for _, query := range evidence {
		if len(query.Results) > 0 {
			successfulQueries++
		}
		resultCount += len(query.Results)
		queryDiagnostic := pulseRetrievalQueryDiagnostic{
			QueryID:        query.QueryID,
			Module:         query.Module,
			Query:          limitText(query.Query, 240),
			Intent:         limitText(query.Intent, 180),
			TopicID:        query.TopicID,
			TopicName:      limitText(query.TopicName, 100),
			ResultCount:    len(query.Results),
			Error:          limitText(query.Error, 300),
			ProviderErrors: limitStringSlice(query.ProviderErrors, 3, 220),
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

func (h *PulseHandler) collectPulseSearchEvidence(date string, topics []models.PulseTopic, signals []memoryPulseSignal) ([]pulseSearchEvidence, []string) {
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
	sem := make(chan struct{}, 4)
	var errMu sync.Mutex
	for index, query := range queries {
		wg.Add(1)
		go func(index int, query pulseSearchQuery) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()

			item := pulseSearchEvidence{
				QueryID:   query.ID,
				Module:    query.Module,
				Query:     query.Query,
				Intent:    query.Intent,
				TopicID:   query.TopicID,
				TopicName: query.TopicName,
			}
			resp, err := h.agent.Search(bridge.SearchRequest{
				Query:       query.Query,
				Limit:       pulseSearchRawResultLimit,
				OpenResults: true,
				OpenLimit:   1,
				PageChars:   1400,
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

	nonEmpty := make([]pulseSearchEvidence, 0, len(evidence))
	for _, item := range evidence {
		if item.Query == "" {
			continue
		}
		nonEmpty = append(nonEmpty, item)
	}
	nonEmpty = h.enrichPulseSearchEvidence(date, nonEmpty, &searchErrors)
	return nonEmpty, searchErrors
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

func (h *PulseHandler) enrichPulseSearchEvidence(date string, evidence []pulseSearchEvidence, searchErrors *[]string) []pulseSearchEvidence {
	if h.agent == nil || len(evidence) == 0 {
		return evidence
	}
	seeds := pulseSearchFollowupSeeds(date, evidence)
	if len(seeds) == 0 {
		return evidence
	}

	resultsByEvidence := make([][]pulseSearchResult, len(evidence))
	followupErrors := []string{}
	var wg sync.WaitGroup
	var mu sync.Mutex
	sem := make(chan struct{}, 4)
	for _, seed := range seeds {
		if seed.EvidenceIndex < 0 || seed.EvidenceIndex >= len(evidence) {
			continue
		}
		followupQuery, ok := pulseSearchFollowupQuery(date, evidence[seed.EvidenceIndex], seed.Result)
		if !ok {
			continue
		}
		wg.Add(1)
		go func(seed pulseSearchFollowupSeed, followupQuery pulseSearchQuery) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()

			resp, err := h.agent.Search(bridge.SearchRequest{
				Query:       followupQuery.Query,
				Limit:       pulseSearchFollowupResultLimit,
				OpenResults: true,
				OpenLimit:   2,
				PageChars:   1400,
			})
			if err != nil {
				mu.Lock()
				followupErrors = append(followupErrors, fmt.Sprintf("二次检索 %s: %v", followupQuery.Query, err))
				mu.Unlock()
				return
			}

			normalized := normalizePulseSearchResults(date, followupQuery, resp.Results, pulseSearchFollowupResultLimit)
			supporting := pulseSupportingFollowupResults(evidence[seed.EvidenceIndex], seed.Result, normalized)
			if len(supporting) == 0 {
				return
			}
			mu.Lock()
			resultsByEvidence[seed.EvidenceIndex] = append(resultsByEvidence[seed.EvidenceIndex], supporting...)
			mu.Unlock()
		}(seed, followupQuery)
	}
	wg.Wait()

	if len(followupErrors) > 0 && searchErrors != nil {
		*searchErrors = append(*searchErrors, limitStringSlice(followupErrors, 4, 220)...)
	}
	for index := range evidence {
		if len(resultsByEvidence[index]) == 0 {
			continue
		}
		query := pulseSearchQueryFromEvidence(evidence[index])
		merged := append([]pulseSearchResult{}, evidence[index].Results...)
		merged = append(merged, resultsByEvidence[index]...)
		evidence[index].Results = pulseRankSearchResults(query, merged, pulseSearchExpandedResultLimit)
	}
	return evidence
}

func pulseSearchQueryFromEvidence(item pulseSearchEvidence) pulseSearchQuery {
	return pulseSearchQuery{
		ID:        item.QueryID,
		Module:    item.Module,
		Query:     item.Query,
		Intent:    item.Intent,
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
		if !pulseWeakSearchSource(result) {
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
	seedIndex := 0
	for evidenceIndex, item := range evidence {
		if !pulseSearchEvidenceNeedsFollowup(date, item) {
			continue
		}
		query := pulseSearchQueryFromEvidence(item)
		for _, result := range item.Results {
			key := pulseSearchResultDedupeKey(result)
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
	if len(seeds) > pulseSearchFollowupSeedLimit {
		return seeds[:pulseSearchFollowupSeedLimit]
	}
	return seeds
}

func pulseSearchEvidenceNeedsFollowup(date string, evidence pulseSearchEvidence) bool {
	for _, cluster := range pulseCorroboratedSearchClusters(evidence, evidence.Results) {
		if pulseSearchResultsFreshEnough(date, evidence.Module, cluster) {
			return false
		}
	}
	return true
}

func pulseSearchFollowupQuery(date string, queryEvidence pulseSearchEvidence, seed pulseSearchResult) (pulseSearchQuery, bool) {
	terms := []string{}
	terms = appendUniqueStrings(terms, pulseCorroborationTerms(seed)...)
	for _, term := range pulseSearchRelevanceTerms(pulseSearchQueryFromEvidence(queryEvidence)) {
		terms = appendUniqueStrings(terms, term)
	}
	terms = limitStringSlice(terms, 5, 40)
	if len(terms) == 0 {
		return pulseSearchQuery{}, false
	}
	year := date
	if len(year) > 4 {
		year = year[:4]
	}
	queryText := strings.Join(terms, " ") + " latest update " + year
	return pulseSearchQuery{
		ID:        queryEvidence.QueryID + ":followup",
		Module:    queryEvidence.Module,
		Query:     queryText,
		Intent:    "围绕初始候选补充独立来源互证",
		TopicID:   queryEvidence.TopicID,
		TopicName: queryEvidence.TopicName,
	}, true
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

func buildPulseSearchQueries(date string, topics []models.PulseTopic, signals []memoryPulseSignal) []pulseSearchQuery {
	candidates := map[string][]pulseSearchQuery{
		pulseSourceTopicHot:    {},
		pulseSourceMemory:      {},
		pulseSourceInterestHot: {},
	}
	seen := map[string]bool{}
	addCandidate := func(module string, intent string, topicID string, topicName string, terms []string, suffix string) {
		cleanTerms := cleanPulseSearchTerms(terms)
		if len(cleanTerms) == 0 {
			return
		}
		query := strings.Join(cleanTerms[:minInt(len(cleanTerms), 5)], " ") + " " + strings.TrimSpace(suffix)
		key := strings.ToLower(module + ":" + query)
		if seen[key] {
			return
		}
		seen[key] = true
		candidates[module] = append(candidates[module], pulseSearchQuery{
			Module:    module,
			Query:     query,
			Intent:    intent,
			TopicID:   topicID,
			TopicName: topicName,
		})
	}

	currentTopics := append([]models.PulseTopic{}, topics...)
	if len(currentTopics) > 1 {
		offset := stableIndex(date+":pulse-topic-query-rotation", len(currentTopics))
		currentTopics = append(
			append([]models.PulseTopic{}, currentTopics[offset:]...),
			currentTopics[:offset]...,
		)
	}
	topicSuffixes := pulseSearchQuerySuffixesForDate(pulseSourceTopicHot, date)
	for suffixIndex := range topicSuffixes {
		for _, topic := range currentTopics {
			termGroups := pulseFocusedSearchTermGroups(
				topic.Name,
				expandPulseTopicKeywords(topic.Name, decodeKeywords(topic.Keywords)),
				len(topicSuffixes),
			)
			if len(termGroups) == 0 {
				continue
			}
			addCandidate(
				pulseSourceTopicHot,
				"查找订阅 topic 的近期外网热门进展",
				topic.ID,
				topic.Name,
				termGroups[suffixIndex%len(termGroups)],
				topicSuffixes[suffixIndex],
			)
		}
	}

	memorySuffixes := pulseSearchQuerySuffixesForDate(pulseSourceMemory, date)
	for suffixIndex := range memorySuffixes {
		for _, signal := range signals {
			termGroups := pulseFocusedSearchTermGroups(signal.Focus, signal.Keywords, len(memorySuffixes))
			if len(termGroups) == 0 {
				continue
			}
			addCandidate(
				pulseSourceMemory,
				"查找近期 memory 相关的新信息",
				"",
				"",
				termGroups[suffixIndex%len(termGroups)],
				memorySuffixes[suffixIndex],
			)
		}
	}

	interestTerms := collectInterestTerms(topics, signals)
	if len(interestTerms) > 0 {
		interestSuffixes := pulseSearchQuerySuffixesForDate(pulseSourceInterestHot, date)
		termGroups := pulseFocusedSearchTermGroups("", interestTerms, len(interestSuffixes))
		for suffixIndex, suffix := range interestSuffixes {
			if len(termGroups) == 0 {
				break
			}
			addCandidate(
				pulseSourceInterestHot,
				"根据 topic 与 memory 外扩查找用户可能感兴趣的近期热门方向",
				"",
				"",
				termGroups[suffixIndex%len(termGroups)],
				suffix,
			)
		}
	}

	queries := make([]pulseSearchQuery, 0, pulseSearchQueryLimit)
	nextIndex := map[string]int{}
	budgets := map[string]int{
		pulseSourceTopicHot:    pulseSearchTopicQueryBudget,
		pulseSourceMemory:      pulseSearchMemoryQueryBudget,
		pulseSourceInterestHot: pulseSearchInterestQueryBudget,
	}
	appendNext := func(module string) bool {
		index := nextIndex[module]
		if index >= len(candidates[module]) || len(queries) >= pulseSearchQueryLimit {
			return false
		}
		queries = append(queries, candidates[module][index])
		nextIndex[module] = index + 1
		return true
	}
	for _, module := range pulseModuleOrder {
		for count := 0; count < budgets[module]; count++ {
			if !appendNext(module) {
				break
			}
		}
	}
	for len(queries) < pulseSearchQueryLimit {
		added := false
		for _, module := range pulseModuleOrder {
			if appendNext(module) {
				added = true
			}
		}
		if !added {
			break
		}
	}
	for index := range queries {
		queries[index].ID = fmt.Sprintf("q%d", index+1)
	}
	return queries
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

func (h *PulseHandler) generatePulse(date string, userID string, topics []models.PulseTopic, signals []memoryPulseSignal, searchEvidence []pulseSearchEvidence, searchErrors []string) ([]models.PulseModule, []models.PulseItem, error) {
	if h.agent == nil {
		return nil, nil, fmt.Errorf("agent client is not configured")
	}
	userID = normalizedUserID(userID)

	input := map[string]interface{}{
		"date":            date,
		"user_id":         userID,
		"topics":          topicResponses(topics),
		"memory_signals":  signals,
		"interest_terms":  collectInterestTerms(topics, signals),
		"search_queries":  buildPulseSearchQueries(date, topics, signals),
		"search_evidence": searchEvidence,
		"search_errors":   searchErrors,
		"module_contract": []map[string]string{
			{"key": pulseSourceTopicHot, "purpose": "关注 topic 热门话题推荐。必须基于 module=topic_hot 的 search_evidence 总结外网最新结果。"},
			{"key": pulseSourceMemory, "purpose": "基于近日 memory 推荐。结合 memory_signals 与相关 search_evidence，总结最近可延续的话题。"},
			{"key": pulseSourceInterestHot, "purpose": "可能感兴趣的近日热门话题推荐。必须基于 topic/memory 外扩搜索结果推荐，而不是改写关键词。"},
		},
	}
	inputJSON, _ := json.MarshalIndent(input, "", "  ")

	rawResponse, err := h.requestPulseGeneration(date, userID, string(inputJSON))
	if err != nil {
		return nil, nil, err
	}

	var payload generatedPulsePayload
	if err := decodePulseGeneration(rawResponse, &payload); err != nil {
		firstErr := err
		repairedResponse, repairErr := h.repairPulseGeneration(date, userID, string(inputJSON), rawResponse, err)
		if repairErr != nil {
			return nil, nil, fmt.Errorf("%w; repair_failed=%v; response_preview=%q", firstErr, repairErr, compactSnippet(rawResponse, 320))
		} else if err := decodePulseGeneration(repairedResponse, &payload); err != nil {
			return nil, nil, fmt.Errorf("%w; original_error=%v; repaired_preview=%q", err, firstErr, compactSnippet(repairedResponse, 320))
		}
	}
	if err := validateGeneratedPulsePayload(payload, false); err != nil {
		return nil, nil, fmt.Errorf("%w; response_preview=%q", err, compactSnippet(rawResponse, 320))
	}
	filteredPayload, rejectedItems := filterGeneratedPulsePayloadByEvidence(date, payload, searchEvidence)
	if rejectedItems > 0 {
		slog.Warn(
			"Pulse discarded generated items that failed evidence validation",
			"date", date,
			"discarded", rejectedItems,
			"remaining", generatedPulseItemCount(filteredPayload),
		)
	}
	if generatedPulseItemCount(filteredPayload) == 0 {
		return nil, nil, fmt.Errorf("agent returned no items backed by recent independent sources")
	}
	payload = filteredPayload

	modules, items := generatedPayloadToModels(date, payload, topics)
	if len(modules) == 0 {
		return nil, nil, fmt.Errorf("agent returned no pulse modules")
	}
	return modules, items, nil
}

func (h *PulseHandler) requestPulseGeneration(date string, userID string, inputJSON string) (string, error) {
	return h.requestPulseChat(
		fmt.Sprintf("pulse-%s-%s", normalizedUserID(userID), date),
		userID,
		pulseGenerationPrompt(),
		[]string{
			"你是 Pulse 推荐预计算器。必须只输出一个合法 JSON 对象，不要 Markdown，不要解释。",
			"你必须基于 search_evidence 中的外网检索结果做新闻/资讯聚合总结，不能只改写 topic/keyword。",
			"search_evidence 可能包含围绕候选补充检索到的互证来源；生成 item 时只聚合多个独立来源共同支撑的信息簇，孤立单来源候选不要硬生成推荐。",
			"生成前必须先剔除和 query/topic 无关的搜索结果；如果剩余相关来源不足，不要硬生成推荐。",
			"每个 item 是一个资讯簇，必须包含 news_sources 数组，并且 signals 至少包含一个真实来源，格式为：搜索来源：标题 - URL。",
			"不得把单篇 CSDN/博客园/知乎/掘金/资源下载/转载聚合页包装成行业趋势；这类来源只能作为弱证据或辅助来源。",
			"title 必须写成中文资讯标题，并明确包含“可识别主体 + 具体动作/事件”，例如公司、产品或模型做了什么；禁止写“新线索值得跟踪”“新动向”“待核验信号”或“近期资讯聚合：...”。",
			"summary 必须只写 1-2 句可由来源直接支持的具体新闻事实，至少回答“谁做了什么、发布了什么版本或哪项数据发生了什么变化”之一；不得写推荐理由或核验套话，提取不到具体事实就不要生成 item。",
			"如果某模块没有搜索结果，items 可以为空，或明确说明搜索不足；禁止编造最新事实。",
		},
		[]string{
			"Pulse generation input JSON:\n" + string(inputJSON),
		},
	)
}

func (h *PulseHandler) repairPulseGeneration(date string, userID string, inputJSON string, brokenJSON string, parseErr error) (string, error) {
	return h.requestPulseChat(
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

func (h *PulseHandler) requestPulseChat(conversationID string, userID string, message string, modePrompts []string, contextBlocks []string) (string, error) {
	memoryEnabled := false
	errors := []string{}
	if h.agent == nil {
		return "", fmt.Errorf("agent client is not configured")
	}
	for _, modelPreference := range h.pulseModelPreferences() {
		resp, err := h.agent.Chat(bridge.ChatRequest{
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
{"modules":[{"key":"topic_hot","title":"...","summary":"...","items":[{"topic_id":"","topic_name":"","category":"...","title":"...","summary":"...","heat_score":80,"recommendation_reason":"...","signals":["..."],"quick_context":"...","key_points":["...","...","..."],"news_sources":[{"title":"...","url":"https://...","source":"...","snippet":"...","published_at":"..."}],"suggested_questions":["...","...","..."],"explore_prompt":"..."}]}]}

硬性要求：
- modules 必须且只能包含 topic_hot、memory、interest_hot 三个 key。
- 必须先阅读 search_evidence；推荐内容必须来自搜索结果的 title/snippet/url，而不是改写 topic/keyword。
- 必须先过滤 search_evidence.results：只保留 title/snippet/url 明确命中 query/topic 关键词、公司、产品、技术或事件的来源；和主题无关的地图、菜谱、游戏论坛、帮助页、站点首页等必须丢弃。
- CSDN、博客园、知乎、掘金、资源下载页、转载聚合页只能作为弱证据；不能把单篇此类来源包装成“趋势/范式/外网热门”。如果只有弱证据，降低 heat_score 并说明“仅作待核验线索”，或不生成该 item。
- topic_hot 必须优先使用 module=topic_hot 的搜索结果；interest_hot 必须使用 module=interest_hot 的搜索结果；memory 可结合 memory_signals 和搜索结果。
- 每个 item 是一个“资讯簇”：聚合 2-5 条相关搜索结果；不要把每条搜索结果拆成独立 item。
- title 写成中文编辑标题，必须同时包含可识别主体（公司、组织、产品、模型或项目）和具体动作/事件（如发布、开放、收购、融资、更新、下线或数据变化）；保留 GPT-5、Claude、OpenAI 等必要专名即可。禁止直接复制英文搜索标题，禁止写“近期资讯聚合：来源标题...”“新线索值得跟踪”“新动向”“待核验线索”或“发布与开放信号待核验”。
- item.summary 是卡片唯一的“新闻簇内容”字段：只用 1-2 句写可由来源直接支持的具体新闻事实，至少回答“谁在何时做了什么”“发布/开放了什么版本或能力”“哪项可量化数据发生了什么变化”之一。不要在 summary 里写推荐理由、核验套话、来源数量或“出现新的外部资讯信号”；禁止拼接来源标题/snippet，禁止写“聚合 N 条来源，关键线索是...”。如果无法提取具体事实，不要生成这个 item。
- recommendation_reason 只解释“为什么与这个用户相关”，必须是一句短句，不超过约 50 个中文字符；不得复述 summary、来源或核验提醒。
- news_sources 必须包含 2-5 个来自 search_evidence.results 的来源对象，url 必须原样复制。
- news_sources 至少来自 2 个独立发布机构，且至少 2 个来源必须带有处于当前模块时间窗内的 published_at；没有日期或只有陈旧来源时不要生成。
- 每个 item 的 signals 必须至少包含一个真实来源，格式为“搜索来源：标题 - URL”。
- quick_context 只补充来源之间的一致点、差异或证据强弱，不得复述 summary、recommendation_reason 或整段来源 snippet。
- key_points 只写 2-3 个简短事实标签，不得写“推荐理由”“核验动作”或重复来源。
- items 总数最多 18 条，证据充分时目标 8-12 条；质量优先，绝不为了数量复用来源或拆分同一事件。每个 item 恰好生成 3 个 suggested_questions。
- suggested_questions 必须像真实用户会点击的短任务型追问，每个尽量不超过 32 个中文字符；禁止“用 5 分钟帮我读懂……”等长模板。
- suggested_questions 里要点名具体技术、公司、地点、来源标题、数据或争议点；禁止使用“为什么值得关注/有哪些风险/这些来源说明什么趋势/对我意味着什么”这类泛化模板，也不要写成考试题或评审题。
- 所有面向用户的文本使用中文。
- 不要编造具体新闻事实；如果 search_evidence 为空或不足，在 signals 写明“外网搜索无可用结果/搜索失败”，并减少该模块 items。`
}

func pulseJSONRepairPrompt(parseErr error) string {
	return fmt.Sprintf(`上一次 Pulse 预计算输出不是合法 JSON，解析错误是：%v。

请修复 Broken Pulse JSON，返回且只返回修复后的 JSON 对象。
必须保留 modules 数组，并包含 topic_hot、memory、interest_hot 三个模块。
每个 item 必须包含 suggested_questions 数组，恰好 3 条；每条应引用具体标题、来源或关键点，并尽量不超过 32 个中文字符。
item.title 必须包含可识别主体和具体动作/事件；禁止“新线索值得跟踪”“新动向”等占位标题。
item.summary 只保留 1-2 句可由来源支持的具体新闻事实；无法说明谁做了什么就删除该 item。recommendation_reason 只保留一句简短的用户相关性说明。`, parseErr)
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
		if strings.TrimSpace(module.Title) == "" || strings.TrimSpace(module.Summary) == "" {
			return fmt.Errorf("agent returned module %q without personalized title or summary", key)
		}
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
	allowedByModule := map[string]map[string]pulseNewsSource{}
	evidenceByModule := map[string][]pulseSearchEvidence{}
	for _, queryEvidence := range evidence {
		module := normalizePulseModuleKey(queryEvidence.Module)
		if module == "" {
			continue
		}
		evidenceByModule[module] = append(evidenceByModule[module], queryEvidence)
		if allowedByModule[module] == nil {
			allowedByModule[module] = map[string]pulseNewsSource{}
		}
		for _, result := range queryEvidence.Results {
			key := pulseSearchResultDedupeKey(result)
			if key == "" {
				continue
			}
			allowedByModule[module][key] = pulseNewsSource{
				Title:       result.Title,
				URL:         result.URL,
				Source:      result.Source,
				Snippet:     result.Snippet,
				PublishedAt: result.PublishedAt,
			}
		}
	}

	filtered := generatedPulsePayload{Modules: make([]generatedPulseModule, 0, len(payload.Modules))}
	rejected := 0
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
					continue
				}
				seen[sourceKey] = true
				matched = append(matched, source)
				if len(matched) >= pulseSearchClusterMaxSources {
					break
				}
			}
			matched = pulseExpandGeneratedItemSources(matched, evidenceByModule[key], seen)
			matched = pulseCorroboratedGeneratedSources(matched, evidenceByModule[key])
			if strings.TrimSpace(item.Title) == "" ||
				strings.TrimSpace(item.Summary) == "" ||
				!pulseNewsCopyMeetsQualityGate(item.Title, item.Summary) ||
				!pulseNewsSourcesMeetQualityGate(date, key, matched) {
				rejected++
				continue
			}
			item.NewsSources = matched
			item.Sources = nil
			item.Signals = pulseSignalsWithVerifiedSources(item.Signals, matched)
			item.HeatScore = pulseVerifiedEvidenceHeatScore(matched, item.HeatScore)
			items = append(items, item)
		}
		module.Items = items
		filtered.Modules = append(filtered.Modules, module)
	}
	return filtered, rejected
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

	visited := make([]bool, len(sources))
	best := []int{}
	for start := range sources {
		if visited[start] || len(edges[start]) == 0 {
			continue
		}
		queue := []int{start}
		visited[start] = true
		component := []int{}
		for len(queue) > 0 {
			current := queue[0]
			queue = queue[1:]
			component = append(component, current)
			for next := range edges[current] {
				if visited[next] {
					continue
				}
				visited[next] = true
				queue = append(queue, next)
			}
		}
		if len(component) > len(best) {
			best = component
		}
	}
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
			itemTitle := strings.TrimSpace(generatedItem.Title)
			itemSummary := strings.TrimSpace(generatedItem.Summary)
			if pulseItemCopyLooksLikeSearchDump(itemTitle, itemSummary) {
				fallbackResults := pulseSearchResultsFromNewsSources(newsSources)
				if len(fallbackResults) > 0 {
					fallbackEvidence := pulseSearchEvidence{
						Module:    key,
						Query:     firstNonEmptyPulse(topicName, generatedItem.Category, generatedItem.Title),
						TopicID:   topicID,
						TopicName: topicName,
						Intent:    generatedItem.Category,
					}
					if pulseTitleLooksLikeSearchDump(itemTitle) {
						itemTitle = searchFallbackClusterTitle(key, fallbackEvidence, fallbackResults)
					}
					if pulseSummaryLooksLikeSearchDump(itemSummary) {
						itemSummary = searchFallbackClusterSummary(fallbackEvidence, fallbackResults)
					}
				}
			}
			itemSummary = pulseCompactSummary(itemSummary)
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
				Title:         limitText(itemTitle, 120),
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
	for _, queryEvidence := range evidence {
		module := normalizePulseModuleKey(queryEvidence.Module)
		if module == "" || len(queryEvidence.Results) == 0 {
			continue
		}
		for _, clusterResults := range pulseSearchFallbackClusters(queryEvidence) {
			if !pulseSearchResultsFreshEnough(date, module, clusterResults) {
				continue
			}
			clusterResults = pulseFilterNewSearchFallbackResults(clusterResults, seenResultKeys)
			if !pulseSearchClusterHasTrustSignal(clusterResults) ||
				!pulseSearchResultsFreshEnough(date, module, clusterResults) {
				continue
			}
			for _, result := range clusterResults {
				if key := pulseSearchResultDedupeKey(result); key != "" {
					seenResultKeys[key] = true
				}
			}
			if perModuleCount[module] >= searchFallbackItemLimit(module) {
				break
			}
			clusterEvidence := queryEvidence
			clusterEvidence.Results = clusterResults
			candidate := searchFallbackClusterItem(date, clusterEvidence, perModuleCount[module])
			if !pulseNewsCopyMeetsQualityGate(candidate.Title, candidate.Summary) {
				continue
			}
			candidates = append(candidates, candidate)
			perModuleCount[module]++
		}
	}
	if len(candidates) == 0 {
		return buildFallbackPulse(date, topics, signals, searchErrors)
	}
	items := diversifyPulseItems(
		rankPulseItems(candidates, pulseFeatureState{}),
		pulseCandidateTargetCount,
	)
	sortPulseModules(modules)
	return modules, items
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
		return "订阅 Topic 的外网新动向", fmt.Sprintf("已基于外网检索和二次取证处理 %d 条与订阅 topic 相关的新线索。", resultCount)
	case pulseSourceMemory:
		return "近日 Memory 的外网延伸", fmt.Sprintf("结合近期 memory 与外网检索结果，补充取证并提炼 %d 条可以继续追踪的线索。", resultCount)
	case pulseSourceInterestHot:
		return "可能感兴趣的外网热门", fmt.Sprintf("从 topic 与 memory 外扩检索，围绕候选补充取证并筛出 %d 条可能值得关注的新话题。", resultCount)
	default:
		return "外网检索推荐", fmt.Sprintf("基于 %d 条外网检索和二次取证结果生成。", resultCount)
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
	results = pulseRankSearchResults(pulseSearchQueryFromEvidence(queryEvidence), results, pulseSearchExpandedResultLimit)
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
			if !pulseSearchResultsCorroborate(queryEvidence, seed, candidate) {
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
	return !pulseAllWeakSearchSources(results)
}

func pulseClusterAddsIndependentSource(cluster []pulseSearchResult, candidate pulseSearchResult) bool {
	candidateDomain := pulseSourceDomainKey(candidate.URL)
	if candidateDomain == "" {
		return false
	}
	for _, result := range cluster {
		if pulseSourceDomainKey(result.URL) == candidateDomain {
			return false
		}
	}
	return true
}

func pulseSearchIndependentSourceCount(results []pulseSearchResult) int {
	domains := []string{}
	for _, result := range results {
		domain := pulseSourceDomainKey(result.URL)
		if domain == "" {
			continue
		}
		domains = appendUniqueStrings(domains, domain)
	}
	return len(domains)
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
	entities := searchFallbackClusterEntities(queryEvidence, results)
	change := searchFallbackClusterTitleChange(results)
	if len(entities) == 0 || change == "" {
		return ""
	}
	return limitText(fmt.Sprintf("%s%s", strings.Join(entities[:minInt(len(entities), 3)], "、"), change), 120)
}

func searchFallbackClusterSummary(queryEvidence pulseSearchEvidence, results []pulseSearchResult) string {
	if len(results) < 2 || pulseAllWeakSearchSources(results) {
		return ""
	}
	entities := searchFallbackClusterEntities(queryEvidence, results)
	if len(entities) == 0 {
		return ""
	}
	subject := strings.Join(entities[:minInt(len(entities), 3)], "、")
	change := searchFallbackClusterSummaryChange(results)
	if change == "" {
		return ""
	}
	return pulseCompactSummary(fmt.Sprintf("%s%s。", subject, change))
}

func searchFallbackClusterContext(queryEvidence pulseSearchEvidence, results []pulseSearchResult) string {
	if len(results) == 0 {
		return ""
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
		leftStrong := pulseCorroborationTermLooksStrong(shared[i].Term)
		rightStrong := pulseCorroborationTermLooksStrong(shared[j].Term)
		if leftStrong != rightStrong {
			return leftStrong
		}
		if len(shared[i].Domains) == len(shared[j].Domains) {
			return len([]rune(shared[i].Term)) > len([]rune(shared[j].Term))
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
	for leftIndex, left := range results {
		for _, right := range results[leftIndex+1:] {
			if pulseSearchResultsShareConcreteEvent(left, right) {
				return true
			}
		}
	}
	return false
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
		"趋势", "分析", "深度", "综述", "全景", "展望", "预测", "革命", "新时代", "指南", "教程", "盘点",
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
		"available now", "opens access", "open source", "open-source", "adds ", "added ",
		"发布", "推出", "上线", "开放", "开源", "正式亮相", "新增", "升级",
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
	return leftDomain != "" && rightDomain != "" && leftDomain != rightDomain
}

func pulseCorroborationTerms(result pulseSearchResult) []string {
	text := cleanSearchText(strings.Join([]string{result.Title, result.Snippet}, " "))
	terms := []string{}
	for _, match := range pulseModelEntityPattern.FindAllString(text, -1) {
		terms = appendUniqueStrings(terms, normalizePulseEntity(match))
	}
	for _, entity := range pulseKnownEntities {
		if pulseTextContainsFold(text, entity) {
			terms = appendUniqueStrings(terms, entity)
		}
	}
	for _, term := range pulseClusterHintTerms(text) {
		if !pulseCorroborationTermLooksGeneric(term) {
			terms = appendUniqueStrings(terms, term)
		}
	}
	for _, term := range pulseKeywordsFromText(text) {
		if !pulseCorroborationTermLooksGeneric(term) {
			terms = appendUniqueStrings(terms, term)
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
	runes := []rune(value)
	if len(runes) <= maxRunes {
		return value
	}
	return string(runes[:maxRunes])
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
	return pulseCompactSentences(value, 2, pulseSummaryMaxRunes)
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
	return time.Time{}, false
}

func pulseFreshnessWindow(module string) time.Duration {
	if normalizePulseModuleKey(module) == pulseSourceMemory {
		return pulseMemoryFreshnessWindow
	}
	return pulseTopicFreshnessWindow
}

func pulseSearchResultHasStaleDate(date string, module string, result pulseSearchResult) bool {
	publishedAt, ok := parsePulsePublishedAt(result.PublishedAt)
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
	recentDomains := map[string]bool{}
	for _, result := range results {
		publishedAt, ok := parsePulsePublishedAt(result.PublishedAt)
		if !ok ||
			publishedAt.Before(reference.Add(-pulseFreshnessWindow(module))) ||
			publishedAt.After(reference.Add(pulseFutureDateTolerance)) {
			continue
		}
		if domain := pulseSourceDomainKey(result.URL); domain != "" {
			recentDomains[domain] = true
		}
	}
	return len(recentDomains) >= 2
}

func pulseNewsSourcesMeetQualityGate(date string, module string, sources []pulseNewsSource) bool {
	if len(sources) < 2 || len(sources) > pulseSearchClusterMaxSources {
		return false
	}
	results := pulseSearchResultsFromNewsSources(sources)
	return pulseSearchIndependentSourceCount(results) >= 2 &&
		!pulseAllWeakSearchSources(results) &&
		pulseSearchClusterDescribesConcreteEvent(results) &&
		pulseSearchResultsFreshEnough(date, module, results)
}

func pulseNewsCopyMeetsQualityGate(title string, summary string) bool {
	title = cleanSearchText(title)
	summary = cleanSearchText(summary)
	if title == "" || summary == "" ||
		pulseNewsCopyLooksGeneric(title) ||
		pulseNewsCopyLooksGeneric(summary) {
		return false
	}
	return pulseCopyContainsConcreteEvent(title) &&
		pulseCopyHasIdentifiableSubject(title) &&
		pulseCopyContainsConcreteFact(summary)
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
	if !pulseNewsCopyMeetsQualityGate(item.Title, item.Summary) {
		return false
	}
	var detail pulseItemDetail
	if item.DetailJSON == "" || json.Unmarshal([]byte(item.DetailJSON), &detail) != nil {
		return false
	}
	return pulseNewsSourcesMeetQualityGate(item.Date, item.Source, detail.NewsSources)
}

func filterPulseItemsForPublishing(items []models.PulseItem) []models.PulseItem {
	filtered := make([]models.PulseItem, 0, len(items))
	for _, item := range items {
		if pulseItemMeetsQualityGate(item) {
			filtered = append(filtered, item)
		}
	}
	return filtered
}

func revalidatePulseCachedItems(items []models.PulseItem) ([]models.PulseItem, []models.PulseItem) {
	current := make([]models.PulseItem, 0, len(items))
	upgrades := []models.PulseItem{}
	for _, item := range items {
		validated, upgraded, ok := revalidatePulseCachedItem(item)
		if !ok {
			continue
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
	haystack := strings.ToLower(text)
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
		keywords = append(keywords, cleaned)
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
