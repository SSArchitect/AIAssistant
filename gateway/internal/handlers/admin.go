package handlers

import (
	"log/slog"
	"net/http"
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

type UpdateSettingsRequest struct {
	Settings  map[string]string `json:"settings" binding:"required"`
	Validate  bool              `json:"validate"`
	Providers []string          `json:"providers"`
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
