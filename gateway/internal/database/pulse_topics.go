package database

import (
	"github.com/aan/agent-assistant-gateway/internal/models"
	"gorm.io/gorm"
)

// Pulse Topics now have a single lifecycle: present or deleted. Remove legacy
// disabled rows during startup so old data cannot reappear as a third state.
func migrateDisabledPulseTopics(db *gorm.DB) error {
	return db.Where("enabled = ?", false).Delete(&models.PulseTopic{}).Error
}
