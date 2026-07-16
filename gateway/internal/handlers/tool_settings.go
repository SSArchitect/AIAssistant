package handlers

import (
	"encoding/json"
	"net/http"
	"sort"
	"strings"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
)

const (
	toolSettingPrefix = "tool."
	toolEnabledSuffix = ".enabled"
	toolPolicySuffix  = ".policy"
	mcpEnabledKey     = "mcp.enabled"
	mcpServersKey     = "mcp.servers"
)

type UpdateToolSettingsRequest struct {
	Settings map[string]string `json:"settings" binding:"required"`
}

func (h *ChatHandler) UpdateToolSettings(c *gin.Context) {
	var req UpdateToolSettingsRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}

	userID := requestUserID(c)
	updates := make(map[string]string)
	for key, value := range req.Settings {
		normalizedKey := strings.TrimSpace(key)
		normalizedValue := strings.TrimSpace(value)
		if err := validateUserToolSetting(normalizedKey, normalizedValue); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}
		updates[normalizedKey] = normalizedValue
	}

	if err := saveUserSettings(userID, updates); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to save tool settings"})
		return
	}

	settings, err := loadUserSettings(userID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load tool settings"})
		return
	}
	c.JSON(http.StatusOK, gin.H{
		"status":        "ok",
		"user_settings": settings,
		"mcp":           mcpConfigFromSettings(settings),
		"disabled":      disabledToolsFromSettings(settings),
		"policies":      toolPoliciesFromSettings(settings),
	})
}

func validateUserToolSetting(key string, value string) error {
	switch {
	case isToolEnabledSetting(key):
		if _, ok := parseBoolSetting(value); !ok {
			return badToolSettingError("tool enabled settings must be true or false")
		}
		return nil
	case isToolPolicySetting(key):
		if !isValidToolPolicy(value) {
			return badToolSettingError("tool policy settings must be auto, confirm, or deny")
		}
		return nil
	case key == mcpEnabledKey:
		if _, ok := parseBoolSetting(value); !ok {
			return badToolSettingError("mcp.enabled must be true or false")
		}
		return nil
	case key == mcpServersKey:
		if value == "" {
			return nil
		}
		var parsed interface{}
		if err := json.Unmarshal([]byte(value), &parsed); err != nil {
			return badToolSettingError("mcp.servers must be valid JSON")
		}
		switch parsed.(type) {
		case []interface{}, map[string]interface{}:
			return nil
		default:
			return badToolSettingError("mcp.servers must be a JSON array or object")
		}
	default:
		return badToolSettingError("unsupported tool setting: " + key)
	}
}

type badToolSettingError string

func (e badToolSettingError) Error() string {
	return string(e)
}

func loadUserSettings(userID string) (map[string]string, error) {
	var settings []models.UserSetting
	if err := database.DB.
		Where("user_id = ?", normalizedUserID(userID)).
		Find(&settings).Error; err != nil {
		return nil, err
	}

	result := make(map[string]string, len(settings))
	for _, setting := range settings {
		result[setting.Key] = setting.Value
	}
	return result, nil
}

func saveUserSettings(userID string, updates map[string]string) error {
	normalized := normalizedUserID(userID)
	now := time.Now()
	for key, value := range updates {
		setting := models.UserSetting{
			UserID:    normalized,
			Key:       key,
			Value:     value,
			UpdatedAt: now,
		}
		if err := database.DB.Save(&setting).Error; err != nil {
			return err
		}
	}
	return nil
}

func disabledToolsForUser(userID string) ([]string, error) {
	settings, err := loadUserSettings(userID)
	if err != nil {
		return nil, err
	}
	return disabledToolsFromSettings(settings), nil
}

func toolRuntimeSettingsForUser(userID string) ([]string, map[string]string, error) {
	settings, err := loadUserSettings(userID)
	if err != nil {
		return nil, nil, err
	}
	return disabledToolsFromSettings(settings), toolPoliciesFromSettings(settings), nil
}

func disabledToolsFromSettings(settings map[string]string) []string {
	disabled := make([]string, 0)
	for key, value := range settings {
		if !isToolEnabledSetting(key) {
			continue
		}
		enabled, ok := parseBoolSetting(value)
		if ok && !enabled {
			disabled = append(disabled, toolNameFromEnabledSetting(key))
		}
	}
	sort.Strings(disabled)
	return disabled
}

func toolPoliciesFromSettings(settings map[string]string) map[string]string {
	policies := make(map[string]string)
	for key, value := range settings {
		if !isToolPolicySetting(key) {
			continue
		}
		normalized := strings.ToLower(strings.TrimSpace(value))
		if isValidToolPolicy(normalized) {
			policies[toolNameFromPolicySetting(key)] = normalized
		}
	}
	return policies
}

func applyToolUserSettings(resp *bridge.SkillListResponse, settings map[string]string) {
	disabled := disabledToolsFromSettings(settings)
	disabledSet := make(map[string]bool, len(disabled))
	for _, name := range disabled {
		disabledSet[name] = true
	}

	for i := range resp.Skills {
		tool := &resp.Skills[i]
		userEnabled := (*bool)(nil)
		if value, ok := settings[toolEnabledSettingKey(tool.Name)]; ok {
			if parsed, valid := parseBoolSetting(value); valid {
				userEnabled = &parsed
			}
		}
		tool.UserEnabled = userEnabled
		tool.EffectiveEnabled = tool.Enabled && !disabledSet[tool.Name]
		tool.UserPolicy = ""
		if value, ok := settings[toolPolicySettingKey(tool.Name)]; ok && isValidToolPolicy(value) {
			tool.UserPolicy = strings.ToLower(strings.TrimSpace(value))
		}
		tool.EffectivePolicy = tool.UserPolicy
		if tool.EffectivePolicy == "" {
			tool.EffectivePolicy = strings.ToLower(strings.TrimSpace(tool.DefaultPolicy))
		}
		if !isValidToolPolicy(tool.EffectivePolicy) {
			tool.EffectivePolicy = "auto"
		}
		tool.Configurable = true
	}
	resp.UserSettings = settings
	resp.MCP = mcpConfigFromSettings(settings)
	resp.Disabled = disabled
	resp.Policies = toolPoliciesFromSettings(settings)
}

func mcpConfigFromSettings(settings map[string]string) bridge.ToolMCPConfig {
	enabled, ok := parseBoolSetting(settings[mcpEnabledKey])
	if !ok {
		enabled = false
	}
	return bridge.ToolMCPConfig{
		Enabled: enabled,
		Servers: settings[mcpServersKey],
	}
}

func isToolEnabledSetting(key string) bool {
	return strings.HasPrefix(key, toolSettingPrefix) &&
		strings.HasSuffix(key, toolEnabledSuffix) &&
		toolNameFromEnabledSetting(key) != ""
}

func isToolPolicySetting(key string) bool {
	return strings.HasPrefix(key, toolSettingPrefix) &&
		strings.HasSuffix(key, toolPolicySuffix) &&
		toolNameFromPolicySetting(key) != ""
}

func toolEnabledSettingKey(toolName string) string {
	return toolSettingPrefix + strings.TrimSpace(toolName) + toolEnabledSuffix
}

func toolPolicySettingKey(toolName string) string {
	return toolSettingPrefix + strings.TrimSpace(toolName) + toolPolicySuffix
}

func toolNameFromEnabledSetting(key string) string {
	name := strings.TrimPrefix(key, toolSettingPrefix)
	name = strings.TrimSuffix(name, toolEnabledSuffix)
	return strings.TrimSpace(name)
}

func toolNameFromPolicySetting(key string) string {
	name := strings.TrimPrefix(key, toolSettingPrefix)
	name = strings.TrimSuffix(name, toolPolicySuffix)
	return strings.TrimSpace(name)
}

func isValidToolPolicy(value string) bool {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case "auto", "confirm", "deny":
		return true
	default:
		return false
	}
}

func parseBoolSetting(value string) (bool, bool) {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case "true", "1", "yes", "on":
		return true, true
	case "false", "0", "no", "off":
		return false, true
	default:
		return false, false
	}
}
