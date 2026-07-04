package handlers

import (
	"crypto/rand"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
	"golang.org/x/crypto/bcrypt"
)

type AdminHandler struct {
	agent      *bridge.AgentClient
	syncer     *ConfigSyncer
	sessionsMu sync.Mutex
	sessions   map[string]time.Time
}

var llmProviders = []string{"claude", "openai", "gemini", "deepseek", "doubao", "minimax", "ollama"}

const (
	adminPasswordSettingKey = "admin.password"
	adminSessionHeader      = "X-Admin-Session"
	adminSessionTTL         = 12 * time.Hour
	defaultAdminPassword    = "admin123"
)

func NewAdminHandler(agent *bridge.AgentClient, syncers ...*ConfigSyncer) *AdminHandler {
	syncer := NewConfigSyncer(agent)
	if len(syncers) > 0 && syncers[0] != nil {
		syncer = syncers[0]
	}
	return &AdminHandler{agent: agent, syncer: syncer, sessions: map[string]time.Time{}}
}

// maskKey masks an API key for display: shows first 4 and last 4 chars
func maskKey(key string) string {
	if len(key) <= 8 {
		if len(key) == 0 {
			return ""
		}
		return "****"
	}
	return key[:4] + "****" + key[len(key)-4:]
}

func isAPIKeyField(key string) bool {
	return strings.HasSuffix(key, ".api_key")
}

func isSecretSetting(key string) bool {
	return isAPIKeyField(key) || key == adminPasswordSettingKey
}

// GetSettings returns all settings with API keys masked
func (h *AdminHandler) GetSettings(c *gin.Context) {
	var settings []models.Setting
	if err := database.DB.Find(&settings).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load settings"})
		return
	}

	result := make(map[string]string)
	for _, s := range settings {
		if isSecretSetting(s.Key) {
			result[s.Key] = maskKey(s.Value)
		} else {
			result[s.Key] = s.Value
		}
	}

	c.JSON(http.StatusOK, gin.H{"settings": result})
}

type AdminLoginRequest struct {
	Password string `json:"password" binding:"required"`
}

func (h *AdminHandler) Login(c *gin.Context) {
	var req AdminLoginRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}
	if !h.verifyAdminPassword(req.Password) {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "admin password is incorrect"})
		return
	}
	token, err := h.createAdminSession()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to create admin session"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"token": token, "expires_in": int(adminSessionTTL.Seconds())})
}

func (h *AdminHandler) Session(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"status": "ok"})
}

func (h *AdminHandler) RequireAuth() gin.HandlerFunc {
	return func(c *gin.Context) {
		if !h.validateAdminSession(c.GetHeader(adminSessionHeader)) {
			c.JSON(http.StatusUnauthorized, gin.H{"error": "admin login required"})
			c.Abort()
			return
		}
		c.Next()
	}
}

func (h *AdminHandler) GetCosts(c *gin.Context) {
	var accounts []models.Account
	if err := database.DB.Order("created_at asc").Find(&accounts).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load accounts"})
		return
	}

	filter, err := costReportFilterFromRequest(c)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	usageQuery := database.DB.Order("created_at desc")
	if filter.FromTime != nil {
		usageQuery = usageQuery.Where("created_at >= ?", *filter.FromTime)
	}
	if filter.ToExclusiveTime != nil {
		usageQuery = usageQuery.Where("created_at < ?", *filter.ToExclusiveTime)
	}

	var usages []models.TokenUsage
	if err := usageQuery.Find(&usages).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load token usage"})
		return
	}
	tokenUsageRecordCount := len(usages)
	messageIDsWithUsage := make(map[uint]bool, len(usages))
	for _, usage := range usages {
		if usage.MessageID > 0 {
			messageIDsWithUsage[usage.MessageID] = true
		}
	}
	traceUsages, traceParseErrors := traceFallbackTokenUsages(messageIDsWithUsage, filter.FromTime, filter.ToExclusiveTime)
	usages = append(usages, traceUsages...)

	accountByID := make(map[string]*CostAccountSummary, len(accounts))
	for _, account := range accounts {
		_, available, note := accountPasswordForAdmin(account)
		accountSummary := &CostAccountSummary{
			ID:                account.ID,
			Name:              account.Name,
			PasswordSet:       account.PasswordHash != "",
			PasswordAvailable: available,
			PasswordNote:      note,
			CreatedAt:         account.CreatedAt,
			UpdatedAt:         account.UpdatedAt,
		}
		accountByID[account.ID] = accountSummary
	}

	moduleByKey := map[string]*CostModuleSummary{}
	accountModuleByKey := map[string]*CostModuleSummary{}
	allActiveDays := map[string]bool{}
	activeAccounts := map[string]bool{}
	accountActiveDays := map[string]map[string]bool{}
	moduleActiveDays := map[string]map[string]bool{}
	moduleActiveAccounts := map[string]map[string]bool{}
	accountModuleActiveDays := map[string]map[string]bool{}
	dailyByDate := map[string]*CostDailySummary{}
	dailyActiveAccounts := map[string]map[string]bool{}
	summary := CostReportSummary{
		TotalAccounts:        len(accountByID),
		TokenUsageRecords:    tokenUsageRecordCount,
		TraceFallbackRecords: len(traceUsages),
		TraceParseErrors:     traceParseErrors,
		AccuracyNote:         costAccuracyNote(len(traceUsages), traceParseErrors),
	}
	for _, account := range accountByID {
		if account.PasswordAvailable {
			summary.AccountsWithPasswords += 1
		}
	}

	for _, usage := range usages {
		userID := normalizedUserID(usage.UserID)
		usageDay := costUsageDay(usage.CreatedAt)
		allActiveDays[usageDay] = true
		activeAccounts[userID] = true
		ensureDaySet(accountActiveDays, userID)[usageDay] = true

		accountSummary := accountByID[userID]
		if accountSummary == nil {
			accountSummary = &CostAccountSummary{
				ID:           userID,
				Name:         "Unknown account " + userID,
				PasswordNote: "account record was not found",
			}
			accountByID[userID] = accountSummary
			summary.TotalAccounts += 1
		}

		addUsageTotals(&summary.CostTotals, usage)
		addUsageTotals(&accountSummary.CostTotals, usage)
		dailySummary := dailyByDate[usageDay]
		if dailySummary == nil {
			dailySummary = &CostDailySummary{Date: usageDay}
			dailyByDate[usageDay] = dailySummary
		}
		addUsageTotals(&dailySummary.CostTotals, usage)
		if dailyActiveAccounts[usageDay] == nil {
			dailyActiveAccounts[usageDay] = map[string]bool{}
		}
		dailyActiveAccounts[usageDay][userID] = true

		agentID := strings.TrimSpace(usage.AgentID)
		if agentID == "" {
			agentID = superChatAgentID
		}
		runtime := strings.TrimSpace(usage.Runtime)
		moduleKey := agentID + "\x00" + runtime
		moduleSummary := moduleByKey[moduleKey]
		if moduleSummary == nil {
			moduleSummary = &CostModuleSummary{
				AgentID:    agentID,
				ModuleName: moduleDisplayName(agentID),
				Runtime:    runtime,
			}
			moduleByKey[moduleKey] = moduleSummary
		}
		addUsageTotals(&moduleSummary.CostTotals, usage)
		ensureDaySet(moduleActiveDays, moduleKey)[usageDay] = true
		if moduleActiveAccounts[moduleKey] == nil {
			moduleActiveAccounts[moduleKey] = map[string]bool{}
		}
		moduleActiveAccounts[moduleKey][userID] = true

		accountModuleKey := userID + "\x00" + agentID + "\x00" + runtime
		accountModuleSummary := accountModuleByKey[accountModuleKey]
		if accountModuleSummary == nil {
			accountModuleSummary = &CostModuleSummary{
				AccountID:    userID,
				AccountName:  accountSummary.Name,
				AgentID:      agentID,
				ModuleName:   moduleDisplayName(agentID),
				Runtime:      runtime,
				AccountCount: 1,
			}
			accountModuleByKey[accountModuleKey] = accountModuleSummary
		}
		addUsageTotals(&accountModuleSummary.CostTotals, usage)
		ensureDaySet(accountModuleActiveDays, accountModuleKey)[usageDay] = true
	}

	accountSummaries := make([]CostAccountSummary, 0, len(accountByID))
	for _, account := range accountByID {
		account.ActiveDays = len(accountActiveDays[account.ID])
		account.DailyAverage = averageCostTotals(account.CostTotals, account.ActiveDays)
		accountSummaries = append(accountSummaries, *account)
	}
	sort.Slice(accountSummaries, func(i, j int) bool {
		if accountSummaries[i].CreatedAt.Equal(accountSummaries[j].CreatedAt) {
			return accountSummaries[i].ID < accountSummaries[j].ID
		}
		return accountSummaries[i].CreatedAt.Before(accountSummaries[j].CreatedAt)
	})

	historicalUserSummaries := costAccountsWithUsage(accountSummaries)
	sort.Slice(historicalUserSummaries, func(i, j int) bool {
		if historicalUserSummaries[i].TotalTokens != historicalUserSummaries[j].TotalTokens {
			return historicalUserSummaries[i].TotalTokens > historicalUserSummaries[j].TotalTokens
		}
		return historicalUserSummaries[i].ID < historicalUserSummaries[j].ID
	})
	dailyUserSummaries := append([]CostAccountSummary(nil), historicalUserSummaries...)
	sort.Slice(dailyUserSummaries, func(i, j int) bool {
		left := dailyUserSummaries[i].DailyAverage.TotalTokens
		right := dailyUserSummaries[j].DailyAverage.TotalTokens
		if left != right {
			return left > right
		}
		if dailyUserSummaries[i].TotalTokens != dailyUserSummaries[j].TotalTokens {
			return dailyUserSummaries[i].TotalTokens > dailyUserSummaries[j].TotalTokens
		}
		return dailyUserSummaries[i].ID < dailyUserSummaries[j].ID
	})

	moduleSummaries := make([]CostModuleSummary, 0, len(moduleByKey))
	for key, module := range moduleByKey {
		module.AccountCount = len(moduleActiveAccounts[key])
		module.ActiveDays = len(moduleActiveDays[key])
		module.DailyAverage = averageCostTotals(module.CostTotals, module.ActiveDays)
		moduleSummaries = append(moduleSummaries, *module)
	}
	sort.Slice(moduleSummaries, func(i, j int) bool {
		if moduleSummaries[i].TotalTokens != moduleSummaries[j].TotalTokens {
			return moduleSummaries[i].TotalTokens > moduleSummaries[j].TotalTokens
		}
		return moduleSummaries[i].AgentID < moduleSummaries[j].AgentID
	})

	accountModuleSummaries := make([]CostModuleSummary, 0, len(accountModuleByKey))
	for key, module := range accountModuleByKey {
		module.ActiveDays = len(accountModuleActiveDays[key])
		module.DailyAverage = averageCostTotals(module.CostTotals, module.ActiveDays)
		accountModuleSummaries = append(accountModuleSummaries, *module)
	}
	sort.Slice(accountModuleSummaries, func(i, j int) bool {
		if accountModuleSummaries[i].AccountName != accountModuleSummaries[j].AccountName {
			return accountModuleSummaries[i].AccountName < accountModuleSummaries[j].AccountName
		}
		if accountModuleSummaries[i].TotalTokens != accountModuleSummaries[j].TotalTokens {
			return accountModuleSummaries[i].TotalTokens > accountModuleSummaries[j].TotalTokens
		}
		return accountModuleSummaries[i].AgentID < accountModuleSummaries[j].AgentID
	})

	summary.ActiveDays = len(allActiveDays)
	summary.ActiveAccounts = len(activeAccounts)
	for _, days := range accountActiveDays {
		summary.AccountActiveDays += len(days)
	}
	summary.DailyAverage = averageCostTotals(summary.CostTotals, summary.ActiveDays)
	summary.DailyAveragePerActiveAccount = averageCostTotals(summary.CostTotals, summary.AccountActiveDays)
	dailySeries := costDailySeries(dailyByDate, dailyActiveAccounts, filter)

	c.JSON(http.StatusOK, CostReportResponse{
		Summary:         summary,
		Filter:          filter.Response(),
		DailySeries:     dailySeries,
		Accounts:        accountSummaries,
		HistoricalUsers: historicalUserSummaries,
		DailyUsers:      dailyUserSummaries,
		Modules:         moduleSummaries,
		AccountModules:  accountModuleSummaries,
	})
}

func (h *AdminHandler) GetAccountPassword(c *gin.Context) {
	accountID := strings.TrimSpace(c.Param("id"))
	if accountID == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "account id is required"})
		return
	}
	var account models.Account
	if err := database.DB.First(&account, "id = ?", normalizedUserID(accountID)).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "account was not found"})
		return
	}
	password, available, note := accountPasswordForAdmin(account)
	c.JSON(http.StatusOK, gin.H{
		"id":                 account.ID,
		"name":               account.Name,
		"password":           password,
		"password_set":       account.PasswordHash != "",
		"password_available": available,
		"password_note":      note,
	})
}

type UpdateSettingsRequest struct {
	Settings  map[string]string `json:"settings" binding:"required"`
	Validate  bool              `json:"validate"`
	Providers []string          `json:"providers"`
}

type CostTotals struct {
	RequestCount             int        `json:"request_count"`
	InputTokens              int        `json:"input_tokens"`
	OutputTokens             int        `json:"output_tokens"`
	TotalTokens              int        `json:"total_tokens"`
	CachedInputTokens        int        `json:"cached_input_tokens"`
	CacheCreationInputTokens int        `json:"cache_creation_input_tokens"`
	ImageCount               int        `json:"image_count"`
	LastUsedAt               *time.Time `json:"last_used_at,omitempty"`
}

type CostAverageTotals struct {
	RequestCount             float64 `json:"request_count"`
	InputTokens              float64 `json:"input_tokens"`
	OutputTokens             float64 `json:"output_tokens"`
	TotalTokens              float64 `json:"total_tokens"`
	CachedInputTokens        float64 `json:"cached_input_tokens"`
	CacheCreationInputTokens float64 `json:"cache_creation_input_tokens"`
	ImageCount               float64 `json:"image_count"`
}

type CostReportFilter struct {
	From string `json:"from,omitempty"`
	To   string `json:"to,omitempty"`
	Days int    `json:"days,omitempty"`
}

type costReportFilter struct {
	FromTime        *time.Time
	ToExclusiveTime *time.Time
	FromDate        string
	ToDate          string
	Days            int
}

type CostReportSummary struct {
	TotalAccounts                int               `json:"total_accounts"`
	AccountsWithPasswords        int               `json:"accounts_with_passwords"`
	ActiveAccounts               int               `json:"active_accounts"`
	ActiveDays                   int               `json:"active_days"`
	AccountActiveDays            int               `json:"account_active_days"`
	DailyAverage                 CostAverageTotals `json:"daily_average"`
	DailyAveragePerActiveAccount CostAverageTotals `json:"daily_average_per_active_account"`
	TokenUsageRecords            int               `json:"token_usage_records"`
	TraceFallbackRecords         int               `json:"trace_fallback_records"`
	TraceParseErrors             int               `json:"trace_parse_errors"`
	AccuracyNote                 string            `json:"accuracy_note"`
	CostTotals
}

type CostDailySummary struct {
	Date           string `json:"date"`
	ActiveAccounts int    `json:"active_accounts"`
	CostTotals
}

type CostAccountSummary struct {
	ID                string            `json:"id"`
	Name              string            `json:"name"`
	Password          string            `json:"password,omitempty"`
	PasswordSet       bool              `json:"password_set"`
	PasswordAvailable bool              `json:"password_available"`
	PasswordNote      string            `json:"password_note"`
	CreatedAt         time.Time         `json:"created_at"`
	UpdatedAt         time.Time         `json:"updated_at"`
	ActiveDays        int               `json:"active_days"`
	DailyAverage      CostAverageTotals `json:"daily_average"`
	CostTotals
}

type CostModuleSummary struct {
	AccountID    string            `json:"account_id"`
	AccountName  string            `json:"account_name"`
	AgentID      string            `json:"agent_id"`
	ModuleName   string            `json:"module_name"`
	Runtime      string            `json:"runtime"`
	AccountCount int               `json:"account_count"`
	ActiveDays   int               `json:"active_days"`
	DailyAverage CostAverageTotals `json:"daily_average"`
	CostTotals
}

type CostReportResponse struct {
	Summary         CostReportSummary    `json:"summary"`
	Filter          CostReportFilter     `json:"filter"`
	DailySeries     []CostDailySummary   `json:"daily_series"`
	Accounts        []CostAccountSummary `json:"accounts"`
	HistoricalUsers []CostAccountSummary `json:"historical_users"`
	DailyUsers      []CostAccountSummary `json:"daily_users"`
	Modules         []CostModuleSummary  `json:"modules"`
	AccountModules  []CostModuleSummary  `json:"account_modules,omitempty"`
}

// UpdateSettings saves settings and syncs to Python agent
func (h *AdminHandler) UpdateSettings(c *gin.Context) {
	var req UpdateSettingsRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}

	touchedProviders := make(map[string]bool)

	// Save each setting
	for key, value := range req.Settings {
		// Skip empty or masked secret values (don't overwrite existing).
		if isSecretSetting(key) && (value == "" || strings.Contains(value, "****")) {
			continue
		}
		if key == adminPasswordSettingKey {
			hashed, err := hashAdminPassword(value)
			if err != nil {
				c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to secure admin password"})
				return
			}
			value = hashed
		}

		setting := models.Setting{Key: key, Value: value}
		if err := database.DB.Save(&setting).Error; err != nil {
			slog.Error("Failed to save setting", "key", key, "error", err)
			c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to save setting: " + key})
			return
		}

		if provider, ok := providerForValidationSetting(key); ok {
			touchedProviders[provider] = true
		}
	}

	for provider := range touchedProviders {
		if err := h.markValidationPending(provider); err != nil {
			slog.Warn("Failed to mark provider validation pending", "provider", provider, "error", err)
		}
	}

	// Sync to Python agent
	if err := h.syncer.SyncToAgent(); err != nil {
		slog.Warn("Failed to sync config to agent", "error", err)
		// Don't fail — settings are saved, agent sync can be retried
	}

	payload := gin.H{"status": "ok"}
	if req.Validate {
		providers := normalizeProviders(req.Providers)
		if len(providers) == 0 {
			for provider := range touchedProviders {
				providers = append(providers, provider)
			}
		}
		if len(providers) == 0 {
			settings, err := h.syncer.SettingsMap()
			if err == nil {
				providers = configuredProviders(settings)
			}
		}
		payload["validation"] = h.validateProviders(providers)
	}

	c.JSON(http.StatusOK, payload)
}

type TestProviderRequest struct {
	Provider string `json:"provider" binding:"required"`
}

type ValidateProvidersRequest struct {
	Provider  string   `json:"provider"`
	Providers []string `json:"providers"`
}

// TestProvider tests a provider's connectivity via the Python agent
func (h *AdminHandler) TestProvider(c *gin.Context) {
	var req TestProviderRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}

	// First sync latest config
	if err := h.syncer.SyncToAgent(); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to sync config: " + err.Error()})
		return
	}

	// Ask agent to test
	result, err := h.agent.TestProvider(req.Provider)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "test failed: " + err.Error()})
		return
	}

	c.JSON(http.StatusOK, result)
}

// ValidateProvider validates one or more provider credentials and stores the result.
func (h *AdminHandler) ValidateProvider(c *gin.Context) {
	var req ValidateProvidersRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}

	providers := normalizeProviders(req.Providers)
	if req.Provider != "" {
		providers = normalizeProviders([]string{req.Provider})
		if len(providers) == 0 {
			c.JSON(http.StatusBadRequest, gin.H{"error": "unknown provider: " + req.Provider})
			return
		}
	} else if len(req.Providers) > 0 && len(providers) == 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "no valid providers"})
		return
	}

	if len(providers) == 0 {
		settings, err := h.syncer.SettingsMap()
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load settings: " + err.Error()})
			return
		}
		providers = configuredProviders(settings)
	}

	if len(providers) == 0 {
		c.JSON(http.StatusOK, gin.H{"validation": map[string]*bridge.ValidateProviderResponse{}})
		return
	}

	if err := h.syncer.SyncToAgent(); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to sync config: " + err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"validation": h.validateProviders(providers)})
}

type ListModelsRequest struct {
	Provider string `json:"provider" binding:"required"`
}

// ListModels fetches available models for a provider
func (h *AdminHandler) ListModels(c *gin.Context) {
	var req ListModelsRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}

	// Sync config first so the agent uses latest API keys
	if err := h.syncer.SyncToAgent(); err != nil {
		slog.Warn("Failed to sync config before listing models", "error", err)
	}

	result, err := h.agent.ListModels(req.Provider)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to list models: " + err.Error()})
		return
	}

	c.JSON(http.StatusOK, result)
}

// SyncToAgent is a public wrapper for startup sync
func (h *AdminHandler) SyncToAgent() error {
	return h.syncer.SyncToAgent()
}

func (h *AdminHandler) validateProviders(providers []string) map[string]*bridge.ValidateProviderResponse {
	settings, err := h.syncer.SettingsMap()
	if err != nil {
		settings = map[string]string{}
	}

	results := make(map[string]*bridge.ValidateProviderResponse)
	for _, provider := range normalizeProviders(providers) {
		result, err := h.agent.ValidateProvider(provider)
		if err != nil {
			result = &bridge.ValidateProviderResponse{
				Success:     false,
				Status:      "error",
				Provider:    provider,
				Message:     err.Error(),
				ModelCount:  0,
				ValidatedAt: time.Now().UTC().Format(time.RFC3339),
			}
		}
		if result.Provider == "" {
			result.Provider = provider
		}
		result.Message = sanitizeValidationMessage(provider, result.Message, settings)
		if err := h.persistValidationResult(provider, result); err != nil {
			slog.Warn("Failed to persist provider validation", "provider", provider, "error", err)
		}
		results[provider] = result
	}
	return results
}

func (h *AdminHandler) persistValidationResult(provider string, result *bridge.ValidateProviderResponse) error {
	fields := map[string]string{
		"validation_status":      result.Status,
		"validation_message":     result.Message,
		"validation_checked_at":  result.ValidatedAt,
		"validation_model_count": strconv.Itoa(result.ModelCount),
	}
	for suffix, value := range fields {
		if err := saveSetting("llm."+provider+"."+suffix, value); err != nil {
			return err
		}
	}
	return nil
}

func (h *AdminHandler) markValidationPending(provider string) error {
	fields := map[string]string{
		"validation_status":     "pending",
		"validation_message":    "Settings changed; validation is required.",
		"validation_checked_at": "",
	}
	for suffix, value := range fields {
		if err := saveSetting("llm."+provider+"."+suffix, value); err != nil {
			return err
		}
	}
	return nil
}

func saveSetting(key string, value string) error {
	return database.DB.Save(&models.Setting{Key: key, Value: value}).Error
}

func providerForValidationSetting(key string) (string, bool) {
	parts := strings.Split(key, ".")
	if len(parts) < 3 || parts[0] != "llm" {
		return "", false
	}
	provider := parts[1]
	field := parts[2]
	if !knownProvider(provider) {
		return "", false
	}
	if field == "api_key" {
		return provider, true
	}
	if (provider == "openai" || provider == "minimax") && field == "base_url" {
		return provider, true
	}
	if provider == "ollama" && field == "base_url" {
		return provider, true
	}
	return "", false
}

func normalizeProviders(providers []string) []string {
	seen := make(map[string]bool)
	result := make([]string, 0, len(providers))
	for _, provider := range providers {
		provider = strings.ToLower(strings.TrimSpace(provider))
		if !knownProvider(provider) || seen[provider] {
			continue
		}
		seen[provider] = true
		result = append(result, provider)
	}
	return result
}

func knownProvider(provider string) bool {
	for _, item := range llmProviders {
		if provider == item {
			return true
		}
	}
	return false
}

func configuredProviders(settings map[string]string) []string {
	providers := make([]string, 0, len(llmProviders))
	for _, provider := range llmProviders {
		if provider == "ollama" {
			if settings["llm.ollama.base_url"] != "" || settings["llm.ollama.model"] != "" {
				providers = append(providers, provider)
			}
			continue
		}
		if settings["llm."+provider+".api_key"] != "" {
			providers = append(providers, provider)
		}
	}
	return providers
}

func sanitizeValidationMessage(provider string, message string, settings map[string]string) string {
	apiKey := settings["llm."+provider+".api_key"]
	if apiKey == "" {
		return message
	}
	return strings.ReplaceAll(message, apiKey, maskKey(apiKey))
}

func (h *AdminHandler) verifyAdminPassword(password string) bool {
	password = strings.TrimSpace(password)
	if password == "" {
		return false
	}
	configured := strings.TrimSpace(os.Getenv("ADMIN_PASSWORD"))
	if configured == "" {
		var setting models.Setting
		if err := database.DB.First(&setting, "key = ?", adminPasswordSettingKey).Error; err == nil {
			configured = strings.TrimSpace(setting.Value)
		}
	}
	if configured == "" {
		configured = defaultAdminPassword
	}
	if strings.HasPrefix(configured, "$2a$") || strings.HasPrefix(configured, "$2b$") || strings.HasPrefix(configured, "$2y$") {
		return bcrypt.CompareHashAndPassword([]byte(configured), []byte(password)) == nil
	}
	return subtle.ConstantTimeCompare([]byte(configured), []byte(password)) == 1
}

func (h *AdminHandler) createAdminSession() (string, error) {
	tokenBytes := make([]byte, 32)
	if _, err := rand.Read(tokenBytes); err != nil {
		return "", err
	}
	token := base64.RawURLEncoding.EncodeToString(tokenBytes)
	expiresAt := time.Now().Add(adminSessionTTL)

	h.sessionsMu.Lock()
	defer h.sessionsMu.Unlock()
	if h.sessions == nil {
		h.sessions = map[string]time.Time{}
	}
	now := time.Now()
	for existing, expiry := range h.sessions {
		if now.After(expiry) {
			delete(h.sessions, existing)
		}
	}
	h.sessions[token] = expiresAt
	return token, nil
}

func (h *AdminHandler) validateAdminSession(token string) bool {
	token = strings.TrimSpace(token)
	if token == "" {
		return false
	}
	h.sessionsMu.Lock()
	defer h.sessionsMu.Unlock()
	if h.sessions == nil {
		return false
	}
	expiresAt, ok := h.sessions[token]
	if !ok {
		return false
	}
	if time.Now().After(expiresAt) {
		delete(h.sessions, token)
		return false
	}
	h.sessions[token] = time.Now().Add(adminSessionTTL)
	return true
}

func hashAdminPassword(password string) (string, error) {
	password = strings.TrimSpace(password)
	if password == "" {
		return "", nil
	}
	if strings.HasPrefix(password, "$2a$") || strings.HasPrefix(password, "$2b$") || strings.HasPrefix(password, "$2y$") {
		return password, nil
	}
	hashed, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if err != nil {
		return "", err
	}
	return string(hashed), nil
}

func accountPasswordForAdmin(account models.Account) (string, bool, string) {
	password := strings.TrimSpace(account.PasswordView)
	if password != "" {
		return password, true, ""
	}
	if strings.TrimSpace(account.PasswordHash) != "" {
		return "", false, "password is hashed and cannot be recovered"
	}
	return "", false, "password is not set"
}

func costAccuracyNote(traceFallbackRecords int, traceParseErrors int) string {
	parts := []string{"统计包含 token_usages 新账本"}
	if traceFallbackRecords > 0 {
		parts = append(parts, "并从历史消息 trace_events 兜底补入未迁移用量")
	}
	parts = append(parts, "用户日均按有请求的用户活跃日计算")
	parts = append(parts, "不包含此前未落库的 Pulse 后台预计算和失败限流请求")
	if traceParseErrors > 0 {
		parts = append(parts, "有少量历史 trace 解析失败")
	}
	return strings.Join(parts, "；") + "。"
}

func costReportFilterFromRequest(c *gin.Context) (costReportFilter, error) {
	filter := costReportFilter{}
	if rawDays := strings.TrimSpace(c.Query("days")); rawDays != "" {
		days, err := strconv.Atoi(rawDays)
		if err != nil || days <= 0 {
			return filter, fmt.Errorf("invalid days")
		}
		from := time.Now().AddDate(0, 0, -days)
		filter.FromTime = &from
		filter.FromDate = costUsageDay(from)
		filter.Days = days
	}

	if rawFrom := strings.TrimSpace(c.Query("from")); rawFrom != "" {
		from, err := parseCostDate(rawFrom)
		if err != nil {
			return filter, fmt.Errorf("invalid from date")
		}
		filter.FromTime = &from
		filter.FromDate = rawFrom
		filter.Days = 0
	}
	if rawTo := strings.TrimSpace(c.Query("to")); rawTo != "" {
		to, err := parseCostDate(rawTo)
		if err != nil {
			return filter, fmt.Errorf("invalid to date")
		}
		toExclusive := to.AddDate(0, 0, 1)
		filter.ToExclusiveTime = &toExclusive
		filter.ToDate = rawTo
	}
	if filter.FromTime != nil && filter.ToExclusiveTime != nil && !filter.FromTime.Before(*filter.ToExclusiveTime) {
		return filter, fmt.Errorf("from date must be before or equal to to date")
	}
	return filter, nil
}

func parseCostDate(value string) (time.Time, error) {
	return time.ParseInLocation("2006-01-02", strings.TrimSpace(value), time.Local)
}

func (filter costReportFilter) Response() CostReportFilter {
	return CostReportFilter{
		From: filter.FromDate,
		To:   filter.ToDate,
		Days: filter.Days,
	}
}

func costDailySeries(dailyByDate map[string]*CostDailySummary, activeAccounts map[string]map[string]bool, filter costReportFilter) []CostDailySummary {
	for date, accounts := range activeAccounts {
		summary := dailyByDate[date]
		if summary == nil {
			summary = &CostDailySummary{Date: date}
			dailyByDate[date] = summary
		}
		summary.ActiveAccounts = len(accounts)
	}

	if filter.FromTime != nil && filter.ToExclusiveTime != nil {
		for day := dayStart(*filter.FromTime); day.Before(*filter.ToExclusiveTime); day = day.AddDate(0, 0, 1) {
			date := costUsageDay(day)
			if dailyByDate[date] == nil {
				dailyByDate[date] = &CostDailySummary{Date: date}
			}
		}
	}

	series := make([]CostDailySummary, 0, len(dailyByDate))
	for _, summary := range dailyByDate {
		series = append(series, *summary)
	}
	sort.Slice(series, func(i, j int) bool {
		return series[i].Date < series[j].Date
	})
	return series
}

func dayStart(value time.Time) time.Time {
	local := value.In(time.Local)
	return time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.Local)
}

func traceFallbackTokenUsages(existingMessageIDs map[uint]bool, since *time.Time, before *time.Time) ([]models.TokenUsage, int) {
	query := database.DB.
		Where("role = ? AND trace_events <> ''", "assistant").
		Order("created_at desc")
	if since != nil {
		query = query.Where("created_at >= ?", *since)
	}
	if before != nil {
		query = query.Where("created_at < ?", *before)
	}
	var messages []models.Message
	if err := query.Find(&messages).Error; err != nil {
		slog.Warn("Failed to load message trace usage fallback", "error", err)
		return nil, 0
	}

	usages := make([]models.TokenUsage, 0)
	parseErrors := 0
	for _, message := range messages {
		if existingMessageIDs[message.ID] {
			continue
		}
		usage, ok, parseErr := traceUsageForMessage(message)
		if parseErr {
			parseErrors += 1
		}
		if !ok {
			continue
		}
		usages = append(usages, usage)
	}
	return usages, parseErrors
}

func traceUsageForMessage(message models.Message) (models.TokenUsage, bool, bool) {
	var events []bridge.RunEvent
	if err := json.Unmarshal([]byte(message.TraceEvents), &events); err != nil {
		return models.TokenUsage{}, false, true
	}
	if events == nil {
		return models.TokenUsage{}, false, false
	}

	for i := len(events) - 1; i >= 0; i-- {
		event := events[i]
		if event.Type != "run.completed" {
			continue
		}
		if usage, ok := usageBreakdownFromPayload(event.Payload); ok {
			return tokenUsageFromBreakdown(message, events, usage, "trace_fallback"), true, false
		}
	}

	total := tokenUsageBreakdown{}
	for _, event := range events {
		if event.Type == "run.completed" {
			continue
		}
		if usage, ok := usageBreakdownFromPayload(event.Payload); ok {
			addTokenUsageBreakdown(&total, usage)
		}
	}
	if !total.hasTrackedCost() {
		return models.TokenUsage{}, false, false
	}
	return tokenUsageFromBreakdown(message, events, total, "trace_fallback"), true, false
}

func usageBreakdownFromPayload(payload map[string]interface{}) (tokenUsageBreakdown, bool) {
	total := tokenUsageBreakdown{}
	for _, key := range []string{"tokens_used", "usage", "token_usage"} {
		if usageMap, ok := usageMapFromValue(payload[key]); ok {
			addTokenUsageBreakdown(&total, normalizeTokenUsage(usageMap))
		}
	}
	for _, key := range []string{"response", "result", "metadata", "meta"} {
		nested, ok := payload[key].(map[string]interface{})
		if !ok {
			continue
		}
		for _, usageKey := range []string{"tokens_used", "usage", "token_usage"} {
			if usageMap, ok := usageMapFromValue(nested[usageKey]); ok {
				addTokenUsageBreakdown(&total, normalizeTokenUsage(usageMap))
			}
		}
	}
	return total, total.hasTrackedCost()
}

func usageMapFromValue(value interface{}) (map[string]int, bool) {
	result := map[string]int{}
	switch typed := value.(type) {
	case map[string]int:
		for key, number := range typed {
			result[key] = number
		}
	case map[string]interface{}:
		for key, raw := range typed {
			switch number := raw.(type) {
			case int:
				result[key] = number
			case int64:
				result[key] = int(number)
			case float64:
				result[key] = int(number)
			case json.Number:
				if value, err := number.Int64(); err == nil {
					result[key] = int(value)
				}
			}
		}
	default:
		return nil, false
	}
	for _, value := range result {
		if value != 0 {
			return result, true
		}
	}
	return result, len(result) > 0
}

func addTokenUsageBreakdown(total *tokenUsageBreakdown, usage tokenUsageBreakdown) {
	if total == nil {
		return
	}
	total.InputTokens += usage.InputTokens
	total.OutputTokens += usage.OutputTokens
	total.TotalTokens += usage.TotalTokens
	total.CachedInputTokens += usage.CachedInputTokens
	total.CacheCreationInputTokens += usage.CacheCreationInputTokens
	total.ImageCount += usage.ImageCount
}

func tokenUsageFromBreakdown(message models.Message, events []bridge.RunEvent, usage tokenUsageBreakdown, runtime string) models.TokenUsage {
	usageJSON, _ := json.Marshal(map[string]int{
		"input":                usage.InputTokens,
		"output":               usage.OutputTokens,
		"total":                usage.TotalTokens,
		"input_cached":         usage.CachedInputTokens,
		"input_cache_creation": usage.CacheCreationInputTokens,
		"images":               usage.ImageCount,
	})
	return models.TokenUsage{
		UserID:                   normalizedUserID(message.UserID),
		ConversationID:           message.ConversationID,
		MessageID:                message.ID,
		RunID:                    message.RunID,
		AgentID:                  storedRunAgentID(message.ConversationID, events),
		Runtime:                  firstNonEmpty(message.Runtime, runtime),
		ModelUsed:                message.ModelUsed,
		InputTokens:              usage.InputTokens,
		OutputTokens:             usage.OutputTokens,
		TotalTokens:              usage.TotalTokens,
		CachedInputTokens:        usage.CachedInputTokens,
		CacheCreationInputTokens: usage.CacheCreationInputTokens,
		ImageCount:               usage.ImageCount,
		UsageJSON:                string(usageJSON),
		CreatedAt:                message.CreatedAt,
	}
}

func addUsageTotals(totals *CostTotals, usage models.TokenUsage) {
	if totals == nil {
		return
	}
	totals.RequestCount += 1
	totals.InputTokens += usage.InputTokens
	totals.OutputTokens += usage.OutputTokens
	totals.TotalTokens += usage.TotalTokens
	totals.CachedInputTokens += usage.CachedInputTokens
	totals.CacheCreationInputTokens += usage.CacheCreationInputTokens
	totals.ImageCount += usage.ImageCount
	if totals.LastUsedAt == nil || usage.CreatedAt.After(*totals.LastUsedAt) {
		lastUsedAt := usage.CreatedAt
		totals.LastUsedAt = &lastUsedAt
	}
}

func costUsageDay(value time.Time) string {
	if value.IsZero() {
		return "unknown"
	}
	return value.Local().Format("2006-01-02")
}

func ensureDaySet(collection map[string]map[string]bool, key string) map[string]bool {
	if collection[key] == nil {
		collection[key] = map[string]bool{}
	}
	return collection[key]
}

func averageCostTotals(totals CostTotals, denominator int) CostAverageTotals {
	if denominator <= 0 {
		return CostAverageTotals{}
	}
	return CostAverageTotals{
		RequestCount:             float64(totals.RequestCount) / float64(denominator),
		InputTokens:              float64(totals.InputTokens) / float64(denominator),
		OutputTokens:             float64(totals.OutputTokens) / float64(denominator),
		TotalTokens:              float64(totals.TotalTokens) / float64(denominator),
		CachedInputTokens:        float64(totals.CachedInputTokens) / float64(denominator),
		CacheCreationInputTokens: float64(totals.CacheCreationInputTokens) / float64(denominator),
		ImageCount:               float64(totals.ImageCount) / float64(denominator),
	}
}

func costAccountsWithUsage(accounts []CostAccountSummary) []CostAccountSummary {
	result := make([]CostAccountSummary, 0, len(accounts))
	for _, account := range accounts {
		if account.RequestCount == 0 && account.TotalTokens == 0 && account.ImageCount == 0 {
			continue
		}
		result = append(result, account)
	}
	return result
}

func moduleDisplayName(agentID string) string {
	switch strings.TrimSpace(agentID) {
	case "", superChatAgentID:
		return "Super Chat"
	case "deep_research_v1":
		return "Deep Research"
	case "image_generation_v1":
		return "Image Generation"
	case "weight_loss_v1":
		return "Weight Loss"
	default:
		return agentID
	}
}
