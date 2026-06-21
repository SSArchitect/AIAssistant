package handlers

import (
	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
)

type ConfigSyncer struct {
	agent *bridge.AgentClient
}

func NewConfigSyncer(agent *bridge.AgentClient) *ConfigSyncer {
	return &ConfigSyncer{agent: agent}
}

// SyncToAgent reads all persisted settings and sends them to the Python agent.
func (s *ConfigSyncer) SyncToAgent() error {
	configMap, err := s.SettingsMap()
	if err != nil {
		return err
	}
	return s.agent.UpdateConfig(configMap)
}

func (s *ConfigSyncer) SettingsMap() (map[string]string, error) {
	var settings []models.Setting
	if err := database.DB.Find(&settings).Error; err != nil {
		return nil, err
	}

	configMap := make(map[string]string)
	for _, setting := range settings {
		configMap[setting.Key] = setting.Value
	}
	return configMap, nil
}
