package database

import (
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/models"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

func TestMigrateDisabledPulseTopicsDeletesOnlyDisabledRows(t *testing.T) {
	db, err := gorm.Open(sqlite.Open(t.TempDir()+"/pulse-topics.db"), &gorm.Config{})
	if err != nil {
		t.Fatalf("open database: %v", err)
	}
	if err := db.AutoMigrate(&models.PulseTopic{}); err != nil {
		t.Fatalf("migrate schema: %v", err)
	}
	now := time.Now()
	topics := []models.PulseTopic{
		{ID: "active", UserID: "alice", Name: "AI", Enabled: true, CreatedAt: now, UpdatedAt: now},
		{ID: "disabled", UserID: "alice", Name: "Legacy", Enabled: false, CreatedAt: now, UpdatedAt: now},
	}
	if err := db.Create(&topics).Error; err != nil {
		t.Fatalf("seed topics: %v", err)
	}
	if err := db.Model(&models.PulseTopic{}).Where("id = ?", "disabled").Update("enabled", false).Error; err != nil {
		t.Fatalf("disable legacy topic: %v", err)
	}

	if err := migrateDisabledPulseTopics(db); err != nil {
		t.Fatalf("migrate disabled topics: %v", err)
	}

	var remaining []models.PulseTopic
	if err := db.Order("id asc").Find(&remaining).Error; err != nil {
		t.Fatalf("load remaining topics: %v", err)
	}
	if len(remaining) != 1 || remaining[0].ID != "active" {
		t.Fatalf("expected only active topic, got %#v", remaining)
	}
}
