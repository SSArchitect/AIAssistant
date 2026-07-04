package handlers

import (
	"log/slog"
	"net/http"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
)

type AdminHandler struct {
	agent  *bridge.AgentClient
	syncer *ConfigSyncer
}

var llmProviders = []string{"claude", "openai", "gemini", "deepseek", "doubao", "minimax", "ollama"}

func NewAdminHandler(agent *bridge.AgentClient, syncers ...*ConfigSyncer) *AdminHandler {
	syncer := NewConfigSyncer(agent)
	if len(syncers) > 0 && syncers[0] != nil {
		syncer = syncers[0]
	}
	return &AdminHandler{agent: agent, syncer: syncer}
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

// GetSettings returns all settings with API keys masked
func (h *AdminHandler) GetSettings(c *gin.Context) {
	var settings []models.Setting
	if err := database.DB.Find(&settings).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load settings"})
		return
	}

	result := make(map[string]string)
	for _, s := range settings {
		if isAPIKeyField(s.Key) {
			result[s.Key] = maskKey(s.Value)
		} else {
			result[s.Key] = s.Value
		}
	}

	c.JSON(http.StatusOK, gin.H{"settings": result})
}

func (h *AdminHandler) GetCosts(c *gin.Context) {
	var accounts []models.Account
	if err := database.DB.Order("created_at asc").Find(&accounts).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load accounts"})
		return
	}

	usageQuery := database.DB.Order("created_at desc")
	if rawDays := strings.TrimSpace(c.Query("days")); rawDays != "" {
		days, err := strconv.Atoi(rawDays)
		if err != nil || days <= 0 {
			c.JSON(http.StatusBadRequest, gin.H{"error": "invalid days"})
			return
		}
		usageQuery = usageQuery.Where("created_at >= ?", time.Now().AddDate(0, 0, -days))
	}

	var usages []models.TokenUsage
	if err := usageQuery.Find(&usages).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load token usage"})
		return
	}

	accountByID := make(map[string]*CostAccountSummary, len(accounts))
	for _, account := range accounts {
		password, available, note := accountPasswordForAdmin(account)
		accountSummary := &CostAccountSummary{
			ID:                account.ID,
			Name:              account.Name,
			Password:          password,
			PasswordSet:       account.PasswordHash != "",
			PasswordAvailable: available,
			PasswordNote:      note,
			CreatedAt:         account.CreatedAt,
			UpdatedAt:         account.UpdatedAt,
		}
		accountByID[account.ID] = accountSummary
	}

	moduleByKey := map[string]*CostModuleSummary{}
	summary := CostReportSummary{TotalAccounts: len(accountByID)}
	for _, account := range accountByID {
		if account.PasswordAvailable {
			summary.AccountsWithPasswords += 1
		}
	}

	for _, usage := range usages {
		userID := normalizedUserID(usage.UserID)
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

		agentID := strings.TrimSpace(usage.AgentID)
		if agentID == "" {
			agentID = superChatAgentID
		}
		moduleKey := userID + "\x00" + agentID + "\x00" + strings.TrimSpace(usage.Runtime)
		moduleSummary := moduleByKey[moduleKey]
		if moduleSummary == nil {
			moduleSummary = &CostModuleSummary{
				AccountID:   userID,
				AccountName: accountSummary.Name,
				AgentID:     agentID,
				ModuleName:  moduleDisplayName(agentID),
				Runtime:     usage.Runtime,
			}
			moduleByKey[moduleKey] = moduleSummary
		}
		addUsageTotals(&moduleSummary.CostTotals, usage)
	}

	accountSummaries := make([]CostAccountSummary, 0, len(accountByID))
	for _, account := range accountByID {
		accountSummaries = append(accountSummaries, *account)
	}
	sort.Slice(accountSummaries, func(i, j int) bool {
		if accountSummaries[i].TotalTokens != accountSummaries[j].TotalTokens {
			return accountSummaries[i].TotalTokens > accountSummaries[j].TotalTokens
		}
		if accountSummaries[i].CreatedAt.Equal(accountSummaries[j].CreatedAt) {
			return accountSummaries[i].ID < accountSummaries[j].ID
		}
		return accountSummaries[i].CreatedAt.Before(accountSummaries[j].CreatedAt)
	})

	moduleSummaries := make([]CostModuleSummary, 0, len(moduleByKey))
	for _, module := range moduleByKey {
		moduleSummaries = append(moduleSummaries, *module)
	}
	sort.Slice(moduleSummaries, func(i, j int) bool {
		if moduleSummaries[i].AccountName != moduleSummaries[j].AccountName {
			return moduleSummaries[i].AccountName < moduleSummaries[j].AccountName
		}
		if moduleSummaries[i].TotalTokens != moduleSummaries[j].TotalTokens {
			return moduleSummaries[i].TotalTokens > moduleSummaries[j].TotalTokens
		}
		return moduleSummaries[i].AgentID < moduleSummaries[j].AgentID
	})

	c.JSON(http.StatusOK, CostReportResponse{
		Summary:  summary,
		Accounts: accountSummaries,
		Modules:  moduleSummaries,
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

type CostReportSummary struct {
	TotalAccounts         int `json:"total_accounts"`
	AccountsWithPasswords int `json:"accounts_with_passwords"`
	CostTotals
}

type CostAccountSummary struct {
	ID                string    `json:"id"`
	Name              string    `json:"name"`
	Password          string    `json:"password"`
	PasswordSet       bool      `json:"password_set"`
	PasswordAvailable bool      `json:"password_available"`
	PasswordNote      string    `json:"password_note"`
	CreatedAt         time.Time `json:"created_at"`
	UpdatedAt         time.Time `json:"updated_at"`
	CostTotals
}

type CostModuleSummary struct {
	AccountID   string `json:"account_id"`
	AccountName string `json:"account_name"`
	AgentID     string `json:"agent_id"`
	ModuleName  string `json:"module_name"`
	Runtime     string `json:"runtime"`
	CostTotals
}

type CostReportResponse struct {
	Summary  CostReportSummary    `json:"summary"`
	Accounts []CostAccountSummary `json:"accounts"`
	Modules  []CostModuleSummary  `json:"modules"`
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
		// Skip empty API key values (don't overwrite existing)
		if isAPIKeyField(key) && (value == "" || strings.Contains(value, "****")) {
			continue
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
