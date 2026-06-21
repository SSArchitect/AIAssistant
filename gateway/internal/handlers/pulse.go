package handlers

import (
	"encoding/json"
	"fmt"
	"hash/fnv"
	"html"
	"log/slog"
	"net/http"
	"net/url"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"
	"unicode"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"gorm.io/gorm"
)

type PulseHandler struct {
	agent *bridge.AgentClient
	mu    sync.Mutex
}

type pulseTopicRequest struct {
	Name     string   `json:"name"`
	Keywords []string `json:"keywords"`
	Enabled  *bool    `json:"enabled"`
	UserID   string   `json:"user_id,omitempty"`
}

type pulseRefreshRequest struct {
	Date   string `json:"date"`
	UserID string `json:"user_id,omitempty"`
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
	Enabled   bool      `json:"enabled"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
}

type pulseItemDetail struct {
	RecommendationReason string            `json:"recommendation_reason"`
	Signals              []string          `json:"signals"`
	QuickContext         string            `json:"quick_context"`
	KeyPoints            []string          `json:"key_points"`
	NewsSources          []pulseNewsSource `json:"news_sources,omitempty"`
	SuggestedQuestions   []string          `json:"suggested_questions"`
	PrecomputedAt        string            `json:"precomputed_at"`
}

type pulseItemResponse struct {
	ID            string          `json:"id"`
	Date          string          `json:"date"`
	TopicID       string          `json:"topic_id,omitempty"`
	TopicName     string          `json:"topic_name,omitempty"`
	Source        string          `json:"source"`
	Category      string          `json:"category,omitempty"`
	Title         string          `json:"title"`
	Summary       string          `json:"summary"`
	HeatScore     int             `json:"heat_score"`
	Detail        pulseItemDetail `json:"detail"`
	ExplorePrompt string          `json:"explore_prompt,omitempty"`
	CreatedAt     time.Time       `json:"created_at"`
	UpdatedAt     time.Time       `json:"updated_at"`
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

const (
	pulseSourceTopicHot    = "topic_hot"
	pulseSourceMemory      = "memory"
	pulseSourceInterestHot = "interest_hot"

	pulseSchedulerTickInterval    = 30 * time.Minute
	pulseScheduledRefreshInterval = 6 * time.Hour
	pulseSearchQueryLimit         = 5
	pulseSearchResultLimit        = 5
)

var pulseModuleOrder = []string{
	pulseSourceTopicHot,
	pulseSourceMemory,
	pulseSourceInterestHot,
}

var pulseModelEntityPattern = regexp.MustCompile(`(?i)\b(?:gpt|claude|gemini|llama|grok|fable|mythos|deepseek|qwen|kimi|mistral|sora|dall-e|o[0-9])(?:[-\s]?[a-z0-9.]+)?\b`)

var pulseKnownEntities = []string{
	"GPT-5.6", "GPT-5", "GPT-4.5", "GPT-4o", "ChatGPT", "OpenAI",
	"Claude", "Anthropic", "Gemini", "DeepMind", "Google", "Llama",
	"Meta", "Grok", "xAI", "DeepSeek", "Qwen", "Kimi", "Mistral",
	"Sora", "Fable", "Mythos", "具身智能", "机器人",
}

func NewPulseHandler(agents ...*bridge.AgentClient) *PulseHandler {
	var agent *bridge.AgentClient
	if len(agents) > 0 {
		agent = agents[0]
	}
	return &PulseHandler{agent: agent}
}

func (h *PulseHandler) StartScheduler() {
	go func() {
		h.runScheduledPulse("startup")
		ticker := time.NewTicker(pulseSchedulerTickInterval)
		defer ticker.Stop()
		for range ticker.C {
			h.runScheduledPulse("tick")
		}
	}()
}

func (h *PulseHandler) runScheduledPulse(reason string) {
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
		if err := h.ensureDailyPulse(date, userID, true); err != nil {
			slog.Warn("Pulse scheduled generation failed", "reason", reason, "date", date, "user_id", userID, "error", err)
			continue
		}
		slog.Info("Pulse scheduled generation completed", "reason", reason, "date", date, "user_id", userID)
	}
}

func (h *PulseHandler) scheduledPulseUserIDs() []string {
	var accounts []models.Account
	if err := database.DB.Order("created_at asc").Find(&accounts).Error; err != nil {
		slog.Warn("Pulse account load failed; using default account", "error", err)
		return []string{"0"}
	}
	if len(accounts) == 0 {
		return []string{"0"}
	}
	userIDs := make([]string, 0, len(accounts))
	for _, account := range accounts {
		userIDs = append(userIDs, normalizedUserID(account.ID))
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
	if err := h.ensureDailyPulse(date, userID, false); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to prepare pulse: " + err.Error()})
		return
	}
	h.writePulse(c, date, userID)
}

func (h *PulseHandler) Refresh(c *gin.Context) {
	var req pulseRefreshRequest
	_ = c.ShouldBindJSON(&req)
	userID := requestUserID(c)
	if req.UserID != "" {
		userID = normalizedUserID(req.UserID)
	}

	dateText := req.Date
	if dateText == "" {
		dateText = c.Query("date")
	}
	date, ok := requestedPulseDate(dateText)
	if !ok {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid date, expected YYYY-MM-DD"})
		return
	}
	if err := h.ensureDailyPulse(date, userID, true); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to refresh pulse: " + err.Error()})
		return
	}
	h.writePulse(c, date, userID)
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

func (h *PulseHandler) CreateTopic(c *gin.Context) {
	var req pulseTopicRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}
	userID := requestUserID(c)
	if req.UserID != "" {
		userID = normalizedUserID(req.UserID)
	}

	name := normalizeTopicName(req.Name)
	if name == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "topic name is required"})
		return
	}

	enabled := true
	if req.Enabled != nil {
		enabled = *req.Enabled
	}

	keywordsJSON := encodeKeywords(req.Keywords)
	var existing models.PulseTopic
	err := database.DB.Where("user_id = ? AND lower(name) = lower(?)", userID, name).First(&existing).Error
	if err == nil {
		existing.Keywords = keywordsJSON
		existing.Enabled = enabled
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
		Enabled:   enabled,
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
	if req.Enabled != nil {
		topic.Enabled = *req.Enabled
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
	if err := database.DB.Delete(&models.PulseTopic{}, "id = ? AND user_id = ?", id, userID).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to delete topic"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"status": "deleted"})
}

func (h *PulseHandler) writePulse(c *gin.Context, date string, userID string) {
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
	var modules []models.PulseModule
	if err := database.DB.Where("date = ? AND user_id = ?", date, userID).Find(&modules).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load pulse modules"})
		return
	}

	generatedAt := ""
	if len(modules) > 0 {
		generatedAt = modules[0].CreatedAt.Format(time.RFC3339)
	} else if len(items) > 0 {
		generatedAt = items[0].CreatedAt.Format(time.RFC3339)
	}

	c.JSON(http.StatusOK, gin.H{
		"date":         date,
		"user_id":      userID,
		"generated_at": generatedAt,
		"topics":       topicResponses(topics),
		"items":        itemResponses(items),
		"modules":      moduleResponses(modules, items),
	})
}

func (h *PulseHandler) ensureDailyPulse(date string, userID string, force bool) error {
	userID = normalizedUserID(userID)
	h.mu.Lock()
	defer h.mu.Unlock()

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

	searchEvidence, searchErrors := h.collectPulseSearchEvidence(date, topics, memorySignals)
	modules, items, err := h.generatePulse(date, userID, topics, memorySignals, searchEvidence, searchErrors)
	if err != nil {
		slog.Warn("Pulse agent generation failed; using signal fallback", "date", date, "error", err)
		if hasSearchResults(searchEvidence) {
			modules, items = buildSearchFallbackPulse(date, topics, memorySignals, searchEvidence, searchErrors)
		} else {
			modules, items = buildFallbackPulse(date, topics, memorySignals, searchErrors)
		}
	}
	scopePulseModels(userID, modules, items)
	if len(modules) == 0 && len(items) == 0 {
		slog.Warn("Pulse generation returned no content; keeping existing pulse", "date", date, "user_id", userID)
		return nil
	}

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

func (h *PulseHandler) hasCurrentPulseShape(date string, userID string) (bool, error) {
	userID = normalizedUserID(userID)
	var items []models.PulseItem
	if err := database.DB.Where("date = ? AND user_id = ?", date, userID).Find(&items).Error; err != nil {
		return false, err
	}
	if len(items) == 0 {
		return false, nil
	}
	var modules []models.PulseModule
	if err := database.DB.Where("date = ? AND user_id = ?", date, userID).Find(&modules).Error; err != nil {
		return false, err
	}

	sources := map[string]bool{}
	for _, item := range items {
		sources[item.Source] = true
	}
	moduleKeys := map[string]bool{}
	for _, module := range modules {
		moduleKeys[module.Key] = true
	}
	return sources[pulseSourceMemory] &&
		sources[pulseSourceInterestHot] &&
		moduleKeys[pulseSourceTopicHot] &&
		moduleKeys[pulseSourceMemory] &&
		moduleKeys[pulseSourceInterestHot], nil
}

func (h *PulseHandler) loadTopics(userID string) ([]models.PulseTopic, error) {
	var topics []models.PulseTopic
	err := database.DB.Where("user_id = ?", normalizedUserID(userID)).Order("enabled desc, created_at asc").Find(&topics).Error
	return topics, err
}

func (h *PulseHandler) loadMemorySignals(userID string) ([]memoryPulseSignal, error) {
	var messages []models.Message
	if err := database.DB.Where("user_id = ?", normalizedUserID(userID)).Order(messageReverseChronologicalOrder).Limit(60).Find(&messages).Error; err != nil {
		return nil, err
	}
	return inferMemorySignals(messages), nil
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
	sem := make(chan struct{}, 2)
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
				Query: query.Query,
				Limit: pulseSearchResultLimit,
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
			for _, result := range resp.Results {
				title := limitText(cleanSearchText(result.Title), 180)
				snippet := cleanSearchText(result.Snippet)
				resultURL := strings.TrimSpace(result.URL)
				if title == "" || resultURL == "" {
					continue
				}
				if !pulseSearchResultLooksUseful(title, snippet, resultURL) {
					continue
				}
				item.Results = append(item.Results, pulseSearchResult{
					Title:       title,
					Snippet:     limitText(snippet, 520),
					URL:         resultURL,
					Source:      limitText(cleanSearchText(result.Source), 80),
					PublishedAt: limitText(metadataString(result.Metadata, "published_at", "publishedAt", "pub_date", "date"), 80),
				})
				if len(item.Results) >= pulseSearchResultLimit {
					break
				}
			}
			if len(item.Results) == 0 {
				item.Error = "搜索完成但没有可用结果。"
				if len(item.ProviderErrors) > 0 {
					item.Error = "搜索完成但没有可用结果；部分来源失败：" + strings.Join(item.ProviderErrors, "；")
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
	return nonEmpty, searchErrors
}

func buildPulseSearchQueries(date string, topics []models.PulseTopic, signals []memoryPulseSignal) []pulseSearchQuery {
	year := date
	if len(year) > 4 {
		year = year[:4]
	}
	queries := make([]pulseSearchQuery, 0, pulseSearchQueryLimit)
	seen := map[string]bool{}
	add := func(module string, intent string, topicID string, topicName string, terms []string) {
		if len(queries) >= pulseSearchQueryLimit {
			return
		}
		cleanTerms := cleanPulseSearchTerms(terms)
		if len(cleanTerms) == 0 {
			return
		}
		query := strings.Join(cleanTerms[:minInt(len(cleanTerms), 5)], " ") + " " + pulseSearchQuerySuffix(module, year)
		key := strings.ToLower(module + ":" + query)
		if seen[key] {
			return
		}
		seen[key] = true
		queries = append(queries, pulseSearchQuery{
			ID:        fmt.Sprintf("q%d", len(queries)+1),
			Module:    module,
			Query:     query,
			Intent:    intent,
			TopicID:   topicID,
			TopicName: topicName,
		})
	}

	for _, topic := range topics {
		if !topic.Enabled {
			continue
		}
		terms := []string{topic.Name}
		terms = append(terms, decodeKeywords(topic.Keywords)...)
		add(pulseSourceTopicHot, "查找订阅 topic 的近期外网热门进展", topic.ID, topic.Name, terms)
	}

	for _, signal := range signals {
		terms := []string{signal.Focus}
		terms = append(terms, signal.Keywords...)
		add(pulseSourceMemory, "查找近期 memory 相关的新信息", "", "", terms)
		if len(queries) >= pulseSearchQueryLimit-1 {
			break
		}
	}

	interestTerms := collectInterestTerms(topics, signals)
	if len(interestTerms) > 0 {
		add(pulseSourceInterestHot, "根据 topic 与 memory 外扩查找用户可能感兴趣的近期热门方向", "", "", interestTerms)
	}

	return queries
}

func pulseSearchQuerySuffix(module string, year string) string {
	switch module {
	case pulseSourceInterestHot:
		return "emerging trends latest news " + year
	default:
		return "latest news " + year
	}
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
			slog.Warn("Pulse full JSON repair failed; trying per-module generation", "date", date, "error", repairErr)
			modulePayload, moduleErr := h.generatePulseModulesIndividually(date, userID, string(inputJSON))
			if moduleErr != nil {
				return nil, nil, fmt.Errorf("%w; repair_failed=%v; per_module_failed=%v; response_preview=%q", firstErr, repairErr, moduleErr, compactSnippet(rawResponse, 320))
			}
			payload = modulePayload
		} else if err := decodePulseGeneration(repairedResponse, &payload); err != nil {
			slog.Warn("Pulse repaired JSON still invalid; trying per-module generation", "date", date, "error", err)
			modulePayload, moduleErr := h.generatePulseModulesIndividually(date, userID, string(inputJSON))
			if moduleErr != nil {
				return nil, nil, fmt.Errorf("%w; original_error=%v; per_module_failed=%v; repaired_preview=%q", err, firstErr, moduleErr, compactSnippet(repairedResponse, 320))
			}
			payload = modulePayload
		}
	}
	requireSearchSources := hasSearchResults(searchEvidence)
	if err := validateGeneratedPulsePayload(payload, requireSearchSources); err != nil {
		slog.Warn("Pulse full payload failed validation; trying per-module generation", "date", date, "error", err)
		modulePayload, moduleErr := h.generatePulseModulesIndividually(date, userID, string(inputJSON))
		if moduleErr != nil {
			return nil, nil, fmt.Errorf("%w; per_module_failed=%v; response_preview=%q", err, moduleErr, compactSnippet(rawResponse, 320))
		}
		payload = modulePayload
		if err := validateGeneratedPulsePayload(payload, requireSearchSources); err != nil {
			return nil, nil, fmt.Errorf("%w; per_module_payload=%q", err, compactSnippet(mustJSON(payload), 320))
		}
	}

	modules, items := generatedPayloadToModels(date, payload, topics)
	if len(modules) == 0 {
		return nil, nil, fmt.Errorf("agent returned no pulse modules")
	}
	return modules, items, nil
}

func (h *PulseHandler) requestPulseGeneration(date string, userID string, inputJSON string) (string, error) {
	memoryEnabled := false
	resp, err := h.agent.Chat(bridge.ChatRequest{
		ConversationID: fmt.Sprintf("pulse-%s-%s", normalizedUserID(userID), date),
		UserID:         normalizedUserID(userID),
		Message:        pulseGenerationPrompt(),
		Stream:         false,
		AgentID:        "super_chat",
		ModePrompts: []string{
			"你是 Pulse 推荐预计算器。必须只输出一个合法 JSON 对象，不要 Markdown，不要解释。",
			"你必须基于 search_evidence 中的外网检索结果做新闻/资讯聚合总结，不能只改写 topic/keyword。",
			"每个 item 是一个资讯簇，必须包含 news_sources 数组，并且 signals 至少包含一个真实来源，格式为：搜索来源：标题 - URL。",
			"title 必须写成中文资讯标题，可以保留 GPT-5、Claude、OpenAI 等产品/公司名；禁止直接复制英文搜索标题或写成“近期资讯聚合：...”。",
			"summary 必须整合新闻簇并解释发生了什么、为什么推荐、哪些点需要核验；禁止拼接来源标题/snippet，禁止写“聚合 N 条来源，关键线索是...”。",
			"如果某模块没有搜索结果，items 可以为空，或明确说明搜索不足；禁止编造最新事实。",
		},
		ContextBlocks: []string{
			"Pulse generation input JSON:\n" + string(inputJSON),
		},
		MemoryEnabled: &memoryEnabled,
	})
	if err != nil {
		return "", err
	}

	return resp.Response, nil
}

func (h *PulseHandler) generatePulseModulesIndividually(date string, userID string, inputJSON string) (generatedPulsePayload, error) {
	payload := generatedPulsePayload{Modules: make([]generatedPulseModule, 0, len(pulseModuleOrder))}
	for _, key := range pulseModuleOrder {
		rawResponse, err := h.requestPulseModuleGeneration(date, userID, key, inputJSON)
		if err != nil {
			return payload, err
		}

		var module generatedPulseModule
		if err := decodePulseModuleGeneration(rawResponse, &module); err != nil {
			firstErr := err
			repairedResponse, repairErr := h.repairPulseModuleGeneration(date, userID, key, inputJSON, rawResponse, err)
			if repairErr != nil {
				return payload, fmt.Errorf("module %s: %w; repair_failed=%v; response_preview=%q", key, firstErr, repairErr, compactSnippet(rawResponse, 220))
			}
			if err := decodePulseModuleGeneration(repairedResponse, &module); err != nil {
				return payload, fmt.Errorf("module %s: %w; original_error=%v; repaired_preview=%q", key, err, firstErr, compactSnippet(repairedResponse, 220))
			}
		}

		module.Key = normalizePulseModuleKey(firstNonEmptyPulse(module.Key, key))
		if module.Key != key {
			return payload, fmt.Errorf("module %s: agent returned key %q", key, module.Key)
		}
		if strings.TrimSpace(module.Title) == "" || strings.TrimSpace(module.Summary) == "" {
			return payload, fmt.Errorf("module %s: missing title or summary", key)
		}
		payload.Modules = append(payload.Modules, module)
	}
	return payload, nil
}

func (h *PulseHandler) requestPulseModuleGeneration(date string, userID string, key string, inputJSON string) (string, error) {
	memoryEnabled := false
	resp, err := h.agent.Chat(bridge.ChatRequest{
		ConversationID: fmt.Sprintf("pulse-%s-%s-%s", normalizedUserID(userID), date, key),
		UserID:         normalizedUserID(userID),
		Message:        pulseModuleGenerationPrompt(key),
		Stream:         false,
		AgentID:        "super_chat",
		ModePrompts: []string{
			"你是 Pulse 单模块预计算器。只输出一个合法 JSON 对象，不要 Markdown，不要解释。",
			"你必须基于 search_evidence 中对应模块的外网检索结果做新闻/资讯聚合总结，不能只改写 topic/keyword。",
			"每个 item 是一个资讯簇，必须包含 news_sources 数组，并且 signals 至少包含一个真实来源，格式为：搜索来源：标题 - URL。",
			"title 必须写成中文资讯标题，可以保留 GPT-5、Claude、OpenAI 等产品/公司名；禁止直接复制英文搜索标题或写成“近期资讯聚合：...”。",
			"summary 必须整合新闻簇并解释发生了什么、为什么推荐、哪些点需要核验；禁止拼接来源标题/snippet，禁止写“聚合 N 条来源，关键线索是...”。",
			"如果对应模块没有搜索结果，items 可以为空，或明确说明搜索不足；禁止编造最新事实。",
		},
		ContextBlocks: []string{
			"Pulse generation input JSON:\n" + inputJSON,
		},
		MemoryEnabled: &memoryEnabled,
	})
	if err != nil {
		return "", err
	}
	return resp.Response, nil
}

func (h *PulseHandler) repairPulseModuleGeneration(date string, userID string, key string, inputJSON string, brokenJSON string, parseErr error) (string, error) {
	memoryEnabled := false
	resp, err := h.agent.Chat(bridge.ChatRequest{
		ConversationID: fmt.Sprintf("pulse-%s-%s-%s-json-repair", normalizedUserID(userID), date, key),
		UserID:         normalizedUserID(userID),
		Message:        pulseModuleJSONRepairPrompt(key, parseErr),
		Stream:         false,
		AgentID:        "super_chat",
		ModePrompts: []string{
			"你是 JSON 修复器。只输出一个合法 JSON 对象，不要 Markdown，不要解释。",
			"不得新增事实；只能修复语法并补齐必要字段。",
		},
		ContextBlocks: []string{
			"Original Pulse input JSON:\n" + inputJSON,
			"Broken Pulse module JSON:\n" + limitText(brokenJSON, 6000),
		},
		MemoryEnabled: &memoryEnabled,
	})
	if err != nil {
		return "", err
	}
	return resp.Response, nil
}

func (h *PulseHandler) repairPulseGeneration(date string, userID string, inputJSON string, brokenJSON string, parseErr error) (string, error) {
	memoryEnabled := false
	resp, err := h.agent.Chat(bridge.ChatRequest{
		ConversationID: fmt.Sprintf("pulse-%s-%s-json-repair", normalizedUserID(userID), date),
		UserID:         normalizedUserID(userID),
		Message:        pulseJSONRepairPrompt(parseErr),
		Stream:         false,
		AgentID:        "super_chat",
		ModePrompts: []string{
			"你是 JSON 修复器。只输出一个合法 JSON 对象，不要 Markdown，不要解释。",
			"不得新增事实；只能修复语法、补齐缺失逗号/引号/括号，并按输入信号补齐缺失的必要字段。",
		},
		ContextBlocks: []string{
			"Original Pulse input JSON:\n" + inputJSON,
			"Broken Pulse JSON:\n" + limitText(brokenJSON, 8000),
		},
		MemoryEnabled: &memoryEnabled,
	})
	if err != nil {
		return "", err
	}

	return resp.Response, nil
}

func pulseGenerationPrompt() string {
	return `请根据上下文中的 Pulse generation input JSON 预计算今日 Pulse。

只输出一个 JSON 对象，禁止 Markdown、注释、尾随逗号或任何解释。结构必须是：
{"modules":[{"key":"topic_hot","title":"...","summary":"...","items":[{"topic_id":"","topic_name":"","category":"...","title":"...","summary":"...","heat_score":80,"recommendation_reason":"...","signals":["..."],"quick_context":"...","key_points":["...","...","..."],"news_sources":[{"title":"...","url":"https://...","source":"...","snippet":"...","published_at":"..."}],"suggested_questions":["...","...","..."],"explore_prompt":"..."}]}]}

硬性要求：
- modules 必须且只能包含 topic_hot、memory、interest_hot 三个 key。
- 必须先阅读 search_evidence；推荐内容必须来自搜索结果的 title/snippet/url，而不是改写 topic/keyword。
- topic_hot 必须优先使用 module=topic_hot 的搜索结果；interest_hot 必须使用 module=interest_hot 的搜索结果；memory 可结合 memory_signals 和搜索结果。
- 每个 item 是一个“资讯簇”：聚合 2-5 条相关搜索结果；不要把每条搜索结果拆成独立 item。
- title 写成中文编辑标题，保留 GPT-5、Claude、OpenAI 等必要专名即可；禁止直接复制英文搜索标题，禁止写“近期资讯聚合：来源标题...”。
- summary 用 1-2 句整合新闻簇：说明发生了什么、主体/版本/时间/动作是什么、为什么推荐给用户、哪些点仍需核验。禁止拼接来源标题/snippet，禁止写“聚合 N 条来源，关键线索是...”。
- news_sources 必须包含 2-5 个来自 search_evidence.results 的来源对象，url 必须原样复制。
- 每个 item 的 signals 必须至少包含一个真实来源，格式为“搜索来源：标题 - URL”。
- quick_context 要综合多条来源，说明共同结论、差异和证据强弱；不要写空泛背景。
- items 总数 5-8 条；每个 item 至少 3 个 suggested_questions，必须基于该 item 的 title/summary/key_points/news_sources 个性化生成。
- suggested_questions 必须像真实用户会点击的任务型追问，例如：快速读懂、核验关键判断、提取时间线/关键数据、区分事实与观点、给后续跟踪清单。
- suggested_questions 里要点名具体技术、公司、地点、来源标题、数据或争议点；禁止使用“为什么值得关注/有哪些风险/这些来源说明什么趋势/对我意味着什么”这类泛化模板，也不要写成考试题或评审题。
- 所有面向用户的文本使用中文。
- 不要编造具体新闻事实；如果 search_evidence 为空或不足，在 signals 写明“外网搜索无可用结果/搜索失败”，并减少该模块 items。`
}

func pulseModuleGenerationPrompt(key string) string {
	return fmt.Sprintf(`请只生成 key=%s 的一个 Pulse 模块。

模块目的：%s
输出且只输出 JSON 对象，结构必须是：
{"key":"%s","title":"...","summary":"...","items":[{"topic_id":"","topic_name":"","category":"...","title":"...","summary":"...","heat_score":80,"recommendation_reason":"...","signals":["..."],"quick_context":"...","key_points":["...","...","..."],"news_sources":[{"title":"...","url":"https://...","source":"...","snippet":"...","published_at":"..."}],"suggested_questions":["...","...","..."],"explore_prompt":"..."}]}

要求：
- title、summary 和 items 必须基于 search_evidence 中 module=%s 的外网检索结果生成。
- 每个 item 是一个“资讯簇”：聚合 2-5 条相关搜索结果；不要把每条搜索结果拆成独立 item。
- item.title 写成中文编辑标题，保留 GPT-5、Claude、OpenAI 等必要专名即可；禁止直接复制英文搜索标题，禁止写“近期资讯聚合：来源标题...”。
- item.summary 用 1-2 句整合新闻簇：说明发生了什么、主体/版本/时间/动作是什么、为什么推荐给用户、哪些点仍需核验。禁止拼接来源标题/snippet，禁止写“聚合 N 条来源，关键线索是...”。
- quick_context 展开综合多条来源的背景、共同结论、差异和证据强弱。
- news_sources 必须包含 2-5 个来自 search_evidence.results 的来源对象，url 必须原样复制。
- 每个 item 的 signals 必须至少包含一个真实来源，格式为“搜索来源：标题 - URL”。
- quick_context 要总结搜索结果里的新信息，并说明证据强弱。
- %s
- 每个 item 至少 3 个 suggested_questions，必须基于该 item 的 title/summary/key_points/news_sources 个性化生成，问题要能直接点击提问。
- suggested_questions 必须像真实用户会点击的任务型追问，例如：快速读懂、核验关键判断、提取时间线/关键数据、区分事实与观点、给后续跟踪清单。
- suggested_questions 里要点名具体技术、公司、地点、来源标题、数据或争议点；禁止使用“为什么值得关注/有哪些风险/这些来源说明什么趋势/对我意味着什么”这类泛化模板，也不要写成考试题或评审题。
- 所有面向用户的文本使用中文。
- 不要编造具体新闻事实；如果没有可用搜索结果，在 signals 写明“外网搜索无可用结果/搜索失败”，并减少 items。`, key, pulseModulePurpose(key), key, key, pulseModuleItemGuidance(key))
}

func pulseJSONRepairPrompt(parseErr error) string {
	return fmt.Sprintf(`上一次 Pulse 预计算输出不是合法 JSON，解析错误是：%v。

请修复 Broken Pulse JSON，返回且只返回修复后的 JSON 对象。
必须保留 modules 数组，并包含 topic_hot、memory、interest_hot 三个模块。
每个 item 必须包含 suggested_questions 数组，至少 3 条，且每条都要引用 item 的具体标题、来源、关键点或摘要信息。`, parseErr)
}

func pulseModuleJSONRepairPrompt(key string, parseErr error) string {
	return fmt.Sprintf(`上一次 key=%s 的 Pulse 模块输出不是合法 JSON，解析错误是：%v。

请修复 Broken Pulse module JSON，返回且只返回修复后的 JSON 对象。
对象必须包含 key、title、summary、items；key 必须是 %s。
每个 item 必须包含 suggested_questions 数组，至少 3 条，且每条都要引用 item 的具体标题、来源、关键点或摘要信息。`, key, parseErr, key)
}

func pulseModulePurpose(key string) string {
	switch key {
	case pulseSourceTopicHot:
		return "关注 topic 热门话题推荐。围绕用户已订阅 topic 生成今日值得打开的知识入口。"
	case pulseSourceMemory:
		return "基于近日 memory 推荐。延续用户最近对话中的目标、问题和上下文。"
	case pulseSourceInterestHot:
		return "可能感兴趣的近日热门话题推荐。结合 topic 与 memory 外扩到可能值得追踪的方向。"
	default:
		return "Pulse 推荐。"
	}
}

func pulseModuleItemGuidance(key string) string {
	switch key {
	case pulseSourceTopicHot:
		return "为每个启用 topic 生成 1 条 item；如果没有启用 topic，items 可以为空但 title/summary 仍需个性化说明。"
	case pulseSourceMemory:
		return "根据 memory_signals 生成 1-2 条 item，优先选择最近最强信号。"
	case pulseSourceInterestHot:
		return "结合 interest_terms 生成 2-3 条 item，强调可能热门但必须说明是否缺少实时来源。"
	default:
		return "生成 1-2 条 item。"
	}
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

func decodePulseModuleGeneration(value string, module *generatedPulseModule) error {
	text := strings.TrimSpace(value)
	if err := json.Unmarshal([]byte(text), module); err == nil && (module.Key != "" || module.Title != "") {
		return nil
	}

	start := strings.Index(text, "{")
	end := strings.LastIndex(text, "}")
	if start < 0 || end <= start {
		return fmt.Errorf("agent response did not contain JSON")
	}
	jsonText := text[start : end+1]
	if err := json.Unmarshal([]byte(jsonText), module); err == nil && (module.Key != "" || module.Title != "") {
		return nil
	}

	var wrapper struct {
		Module  generatedPulseModule   `json:"module"`
		Modules []generatedPulseModule `json:"modules"`
	}
	if err := json.Unmarshal([]byte(jsonText), &wrapper); err != nil {
		return fmt.Errorf("decode pulse module JSON: %w", err)
	}
	if wrapper.Module.Key != "" || wrapper.Module.Title != "" {
		*module = wrapper.Module
		return nil
	}
	if len(wrapper.Modules) > 0 {
		*module = wrapper.Modules[0]
		return nil
	}
	return fmt.Errorf("agent response did not contain a pulse module")
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
			questionContext := pulseQuestionContext{
				Title:     itemTitle,
				Summary:   itemSummary,
				Module:    key,
				TopicName: topicName,
				Category:  generatedItem.Category,
				KeyPoints: generatedItem.KeyPoints,
				Context:   generatedItem.QuickContext,
				Sources:   newsSources,
			}
			detail := pulseItemDetail{
				RecommendationReason: limitText(generatedItem.RecommendationReason, 420),
				Signals:              limitStringSlice(generatedItem.Signals, 6, 180),
				QuickContext:         limitText(generatedItem.QuickContext, 900),
				KeyPoints:            limitStringSlice(generatedItem.KeyPoints, 5, 180),
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
				Summary:       limitText(itemSummary, 420),
				HeatScore:     normalizeHeatScore(generatedItem.HeatScore, key, index),
				DetailJSON:    mustJSON(detail),
				ExplorePrompt: limitText(firstNonEmptyPulse(generatedItem.ExplorePrompt, fmt.Sprintf("请展开「%s」，并说明为什么推荐给我。", itemTitle)), 600),
				CreatedAt:     now,
				UpdatedAt:     now,
			})
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

	items := []models.PulseItem{}
	perModuleCount := map[string]int{}
	for _, queryEvidence := range evidence {
		module := normalizePulseModuleKey(queryEvidence.Module)
		if module == "" || len(queryEvidence.Results) == 0 {
			continue
		}
		if perModuleCount[module] >= searchFallbackItemLimit(module) {
			continue
		}
		items = append(items, searchFallbackClusterItem(date, queryEvidence, perModuleCount[module]))
		perModuleCount[module]++
	}
	if len(items) == 0 {
		return buildFallbackPulse(date, topics, signals, searchErrors)
	}
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
		return "订阅 Topic 的外网新动向", fmt.Sprintf("已基于外网检索结果筛选 %d 条与订阅 topic 相关的新线索。", resultCount)
	case pulseSourceMemory:
		return "近日 Memory 的外网延伸", fmt.Sprintf("结合近期 memory 与外网检索结果，提炼 %d 条可以继续追踪的线索。", resultCount)
	case pulseSourceInterestHot:
		return "可能感兴趣的外网热门", fmt.Sprintf("从 topic 与 memory 外扩检索，筛出 %d 条可能值得关注的新话题。", resultCount)
	default:
		return "外网检索推荐", fmt.Sprintf("基于 %d 条外网检索结果生成。", resultCount)
	}
}

func searchFallbackItemLimit(module string) int {
	switch module {
	case pulseSourceTopicHot:
		return 3
	case pulseSourceMemory:
		return 2
	case pulseSourceInterestHot:
		return 3
	default:
		return 2
	}
}

func searchFallbackClusterItem(date string, queryEvidence pulseSearchEvidence, moduleIndex int) models.PulseItem {
	now := time.Now()
	module := normalizePulseModuleKey(queryEvidence.Module)
	results := queryEvidence.Results[:minInt(len(queryEvidence.Results), pulseSearchResultLimit)]
	sources := newsSourcesFromSearchResults(results, 5)
	title := searchFallbackClusterTitle(module, queryEvidence, results)
	summary := searchFallbackClusterSummary(queryEvidence, results)
	sourceSignals := []string{
		fmt.Sprintf("外网检索查询：%s", queryEvidence.Query),
		fmt.Sprintf("聚合来源数量：%d", len(results)),
	}
	for _, source := range sources[:minInt(len(sources), 3)] {
		sourceSignals = append(sourceSignals, fmt.Sprintf("搜索来源：%s - %s", firstNonEmptyPulse(source.Title, source.Source, "外网结果"), source.URL))
	}
	reason := fmt.Sprintf("这张卡聚合了查询「%s」下的 %d 条外网资讯，和「%s」相关，适合作为今日快速了解入口。", queryEvidence.Query, len(results), firstNonEmptyPulse(queryEvidence.TopicName, queryEvidence.Intent, moduleCategory(module)))
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
		RecommendationReason: limitText(reason, 420),
		Signals:              limitStringSlice(sourceSignals, 6, 220),
		QuickContext:         questionContext.Context,
		KeyPoints:            questionContext.KeyPoints,
		NewsSources:          sources,
		SuggestedQuestions:   personalizedPulseSuggestedQuestions(nil, questionContext),
		PrecomputedAt:        now.UTC().Format(time.RFC3339),
	}
	return models.PulseItem{
		ID:            pulseItemID(date, module, fmt.Sprintf("%s:%s:%d", queryEvidence.Query, results[0].URL, moduleIndex)),
		Date:          date,
		TopicID:       queryEvidence.TopicID,
		TopicName:     queryEvidence.TopicName,
		Source:        module,
		Category:      moduleCategory(module),
		Title:         limitText(title, 120),
		Summary:       limitText(summary, 420),
		HeatScore:     normalizeHeatScore(92-moduleIndex*4, module, moduleIndex),
		DetailJSON:    mustJSON(detail),
		ExplorePrompt: limitText(fmt.Sprintf("请基于这些新闻来源聚合展开并核验「%s」：\n%s\n\n请总结最新信息、可信度、为什么推荐给我，以及我下一步该追问什么。", title, newsSourcePromptLines(sources)), 900),
		CreatedAt:     now,
		UpdatedAt:     now,
	}
}

func searchFallbackClusterTitle(module string, queryEvidence pulseSearchEvidence, results []pulseSearchResult) string {
	focus := searchFallbackClusterFocus(module, queryEvidence, results)
	entities := searchFallbackClusterEntities(queryEvidence, results)
	change := searchFallbackClusterTitleChange(results)
	if len(entities) > 0 {
		return limitText(fmt.Sprintf("%s：%s %s", focus, strings.Join(entities[:minInt(len(entities), 3)], "、"), change), 120)
	}
	return limitText(fmt.Sprintf("%s：%s", focus, change), 120)
}

func searchFallbackClusterSummary(queryEvidence pulseSearchEvidence, results []pulseSearchResult) string {
	if len(results) == 0 {
		return ""
	}
	focus := searchFallbackClusterFocus(normalizePulseModuleKey(queryEvidence.Module), queryEvidence, results)
	entities := searchFallbackClusterEntities(queryEvidence, results)
	subject := focus
	if len(entities) > 0 {
		subject = fmt.Sprintf("%s（%s）", focus, strings.Join(entities[:minInt(len(entities), 3)], "、"))
	}
	change := searchFallbackClusterSummaryChange(results)
	aspects := strings.Join(searchFallbackClusterAspects(results), "、")
	sourcePhrase := "搜索结果"
	if len(results) > 1 {
		sourcePhrase = fmt.Sprintf("%d 条来源", len(results))
	}
	return limitText(fmt.Sprintf("%s集中指向%s：%s。推荐重点看%s；%s", sourcePhrase, subject, change, aspects, searchFallbackClusterUncertainty(results)), 420)
}

func searchFallbackClusterContext(queryEvidence pulseSearchEvidence, results []pulseSearchResult) string {
	if len(results) == 0 {
		return ""
	}
	parts := []string{"综合判断：" + searchFallbackClusterSummary(queryEvidence, results)}
	parts = append(parts, "来源线索：")
	for index, result := range results[:minInt(len(results), 4)] {
		published := ""
		if result.PublishedAt != "" {
			published = "（" + result.PublishedAt + "）"
		}
		parts = append(parts, fmt.Sprintf("%d. %s%s：%s", index+1, firstNonEmptyPulse(result.Title, "未命名来源"), published, searchResultSnippet(result)))
	}
	parts = append(parts, "证据提示：这是搜索结果聚合摘要，适合快速判断是否值得打开；具体事实、发布时间和上下文应以原文为准。")
	return limitText(strings.Join(parts, "\n"), 900)
}

func searchFallbackClusterKeyPoints(queryEvidence pulseSearchEvidence, results []pulseSearchResult) []string {
	focus := searchFallbackClusterFocus(normalizePulseModuleKey(queryEvidence.Module), queryEvidence, results)
	entities := searchFallbackClusterEntities(queryEvidence, results)
	entityText := firstNonEmptyPulse(strings.Join(entities[:minInt(len(entities), 3)], "、"), focus)
	points := []string{
		fmt.Sprintf("共同线索：%s正在出现新的资讯信号。", entityText),
		fmt.Sprintf("重点看点：%s。", strings.Join(searchFallbackClusterAspects(results), "、")),
		fmt.Sprintf("推荐理由：这组来源和「%s」相关，适合作为今日快速判断入口。", focus),
		"核验动作：打开原文确认发布时间、版本号/主体名称和官方口径，避免被搜索摘要误导。",
	}
	return limitStringSlice(points, 5, 180)
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
	text := strings.ToLower(searchFallbackResultsText(results))
	switch {
	case pulseTextHasAny(text, "expected", "reportedly", "rumor", "rumour", "预计", "传闻", "据称", "据报道"):
		return "发布时间与版本细节待核验"
	case pulseTextHasAny(text, "release", "released", "launch", "launched", "announce", "announces", "unveil", "unveils", "available", "发布", "推出", "宣布", "上线", "开放"):
		return "发布与开放信号待核验"
	case pulseTextHasAny(text, "benchmark", "performance", "state-of-the-art", "能力", "性能", "评测"):
		return "能力表现和评测口径待核验"
	default:
		return "新线索值得跟踪"
	}
}

func searchFallbackClusterSummaryChange(results []pulseSearchResult) string {
	text := strings.ToLower(searchFallbackResultsText(results))
	parts := []string{}
	if pulseTextHasAny(text, "expected", "reportedly", "rumor", "rumour", "预计", "传闻", "据称", "据报道") {
		parts = append(parts, "发布时间或版本号出现传闻/报道")
	}
	if pulseTextHasAny(text, "release", "released", "launch", "launched", "announce", "announces", "unveil", "unveils", "available", "发布", "推出", "宣布", "上线", "开放") {
		parts = append(parts, "发布、开放范围或产品可用性有新信息")
	}
	if pulseTextHasAny(text, "safe", "safety", "guardrail", "restricted", "安全", "限制", "风控") {
		parts = append(parts, "安全限制和访问门槛也是关键变量")
	}
	if pulseTextHasAny(text, "benchmark", "performance", "state-of-the-art", "capable", "能力", "性能", "评测") {
		parts = append(parts, "能力表现和评测口径需要对照来源核验")
	}
	if len(parts) == 0 {
		return "出现新的外部资讯信号，但具体事实仍需要打开来源核验"
	}
	return strings.Join(parts, "；")
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
		if strings.TrimSpace(source.URL) == "" {
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
	for _, question := range existing {
		cleaned := cleanSearchText(question)
		if cleaned == "" || pulseQuestionLooksGeneric(cleaned) {
			continue
		}
		if !pulseQuestionMentionsContext(cleaned, terms) && len([]rune(cleaned)) < 18 {
			continue
		}
		questions = appendUniqueStrings(questions, cleaned)
	}

	questions = append(questions, buildPulseSuggestedQuestions(ctx)...)
	questions = limitStringSlice(questions, 5, 160)
	if len(questions) >= 3 {
		return questions
	}

	focus := firstNonEmptyPulse(pulseQuestionFocus(ctx), pulseQuestionPhrase(ctx.TopicName), pulseQuestionPhrase(ctx.Query), moduleCategory(ctx.Module))
	anchor := firstNonEmptyPulse(pulseQuestionPhrase(ctx.TopicName), pulseQuestionPhrase(ctx.Category), moduleCategory(ctx.Module), "这个方向")
	questions = append(questions,
		fmt.Sprintf("用 5 分钟帮我读懂「%s」：结论、证据和待核验点。", focus),
		fmt.Sprintf("围绕「%s」，帮我列一个后续跟踪清单和搜索关键词。", anchor),
		fmt.Sprintf("请把「%s」拆成事实更新、行业观点和可能的营销表述。", focus),
	)
	return limitStringSlice(questions, 5, 160)
}

func buildPulseSuggestedQuestions(ctx pulseQuestionContext) []string {
	focus := pulseQuestionFocus(ctx)
	topic := firstNonEmptyPulse(pulseQuestionPhrase(ctx.TopicName), pulseQuestionPhrase(ctx.Category), moduleCategory(ctx.Module))
	sourceA := pulseSourceQuestionTitle(ctx.Sources, 0)
	sourceB := pulseSourceQuestionTitle(ctx.Sources, 1)
	summaryPoint := pulseQuestionPhrase(ctx.Summary)
	keyPoint := pulseDistinctQuestionPhrase(pulseQuestionPhraseFromStrings(ctx.KeyPoints), focus, sourceA)
	if keyPoint == "" {
		keyPoint = pulseDistinctQuestionPhrase(summaryPoint, focus, sourceA)
	}

	questions := []string{}
	if focus != "" {
		questions = append(questions, fmt.Sprintf("用 5 分钟帮我读懂「%s」：发生了什么、证据是什么、我该关注哪一点？", focus))
	}
	if keyPoint != "" {
		questions = append(questions, fmt.Sprintf("这条里「%s」这个判断靠谱吗？请按来源逐条核验。", keyPoint))
	}
	if sourceA != "" && sourceB != "" {
		questions = append(questions, fmt.Sprintf("把「%s」和「%s」分开看：哪些是事实更新，哪些只是观点？", sourceA, sourceB))
	}
	if sourceA != "" {
		questions = append(questions, fmt.Sprintf("帮我从「%s」提取时间线、关键数据和原文待确认点。", sourceA))
	}
	if topic != "" && focus != "" {
		questions = append(questions, fmt.Sprintf("如果继续跟踪「%s」，接下来 7 天我应该看哪些关键词、公司或指标？", topic))
	}
	if summaryPoint != "" && focus != "" {
		questions = append(questions, fmt.Sprintf("基于「%s」，帮我找出这组新闻里最值得继续查的一条线索。", summaryPoint))
	}
	return limitStringSlice(questions, 5, 160)
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

	items := []models.PulseItem{}
	for index, topic := range topics {
		if !topic.Enabled {
			continue
		}
		focus := topic.Name
		keywords := decodeKeywords(topic.Keywords)
		if len(keywords) > 0 {
			focus = strings.Join(keywords[:minInt(len(keywords), 3)], " / ")
		}
		title := fmt.Sprintf("围绕「%s」生成今日跟进问题", topic.Name)
		items = append(items, fallbackItem(date, pulseSourceTopicHot, index, title, fmt.Sprintf("外网搜索暂不可用；先基于订阅 topic「%s」和关键词「%s」生成待检索问题。", topic.Name, focus), topic.ID, topic.Name, "关注 Topic", searchErrors))
	}
	for index, signal := range signals[:minInt(len(signals), 2)] {
		title := fmt.Sprintf("延续最近对话：%s", signal.Focus)
		items = append(items, fallbackItem(date, pulseSourceMemory, index, title, fmt.Sprintf("外网搜索暂不可用；先基于最近对话中「%s」相关信号生成待检索问题。", signal.Theme), "", "", "近日 Memory", searchErrors))
	}
	interestTerms := collectInterestTerms(topics, signals)
	if len(interestTerms) == 0 {
		interestTerms = []string{"你的近期对话"}
	}
	for index, term := range interestTerms[:minInt(len(interestTerms), 3)] {
		title := fmt.Sprintf("从「%s」延伸一个近日可追踪话题", term)
		items = append(items, fallbackItem(date, pulseSourceInterestHot, index, title, "外网搜索暂不可用；暂以 topic/memory 信号生成待检索方向。", "", "", "可能兴趣", searchErrors))
	}
	return modules, items
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
	return []memoryPulseSignal{{
		Theme:    "工作台探索",
		Focus:    "建立一套适合你的每日推荐偏好",
		Count:    1,
		Keywords: []string{"冷启动"},
		Snippets: []string{"暂无近期 memory，先用冷启动推荐帮助建立偏好。"},
	}}
}

func collectInterestTerms(topics []models.PulseTopic, signals []memoryPulseSignal) []string {
	terms := []string{}
	for _, topic := range topics {
		if !topic.Enabled {
			continue
		}
		terms = appendUniqueStrings(terms, topic.Name)
		terms = appendUniqueStrings(terms, decodeKeywords(topic.Keywords)...)
	}
	for _, signal := range signals {
		terms = appendUniqueStrings(terms, signal.Theme, signal.Focus)
		terms = appendUniqueStrings(terms, signal.Keywords...)
	}
	return terms
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
		return fmt.Sprintf("等待检索的 %d 个订阅 Topic", len(topics)), searchIssue + "，这里只保留待检索问题入口，不作为最新热点总结。"
	case pulseSourceMemory:
		if len(signals) > 0 {
			return "等待检索的近日 Memory", fmt.Sprintf("%s；最近最强信号是「%s」，先生成可继续检索的问题入口。", searchIssue, signals[0].Theme)
		}
		return "等待更多 Memory 信号", searchIssue + "；继续使用工作台后，这里会基于近期对话和外网检索生成推荐。"
	case pulseSourceInterestHot:
		terms := collectInterestTerms(topics, signals)
		if len(terms) > 0 {
			return "等待检索的兴趣外扩", fmt.Sprintf("%s；基于「%s」等信号保留待检索方向。", searchIssue, strings.Join(terms[:minInt(len(terms), 3)], " / "))
		}
		return "冷启动兴趣探索", searchIssue + "；先生成少量探索问题，等 topic 和 memory 更丰富后再增强个性化。"
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
		if url == "" {
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
		Enabled:   topic.Enabled,
		CreatedAt: topic.CreatedAt,
		UpdatedAt: topic.UpdatedAt,
	}
}

func moduleResponses(modules []models.PulseModule, items []models.PulseItem) []pulseModuleResponse {
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
			Items:   itemResponses(moduleItems),
		})
	}
	return responses
}

func itemResponses(items []models.PulseItem) []pulseItemResponse {
	responses := make([]pulseItemResponse, 0, len(items))
	for _, item := range items {
		responses = append(responses, itemResponse(item))
	}
	return responses
}

func itemResponse(item models.PulseItem) pulseItemResponse {
	var detail pulseItemDetail
	_ = json.Unmarshal([]byte(item.DetailJSON), &detail)
	return pulseItemResponse{
		ID:            item.ID,
		Date:          item.Date,
		TopicID:       item.TopicID,
		TopicName:     item.TopicName,
		Source:        item.Source,
		Category:      item.Category,
		Title:         item.Title,
		Summary:       item.Summary,
		HeatScore:     item.HeatScore,
		Detail:        detail,
		ExplorePrompt: item.ExplorePrompt,
		CreatedAt:     item.CreatedAt,
		UpdatedAt:     item.UpdatedAt,
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
