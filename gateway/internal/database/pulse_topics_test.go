package database

import (
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/models"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

func TestMigrateLegacyPulseTopicsRemovesExcludedRows(t *testing.T) {
	db, err := gorm.Open(sqlite.Open(t.TempDir()+"/pulse-topics.db"), &gorm.Config{})
	if err != nil {
		t.Fatalf("open database: %v", err)
	}
	if err := db.AutoMigrate(&models.PulseTopic{}); err != nil {
		t.Fatalf("migrate schema: %v", err)
	}
	if err := db.Exec("ALTER TABLE pulse_topics ADD COLUMN enabled numeric NOT NULL DEFAULT 1").Error; err != nil {
		t.Fatalf("add legacy column: %v", err)
	}
	now := time.Now()
	topics := []models.PulseTopic{
		{ID: "current", UserID: "alice", Name: "AI", CreatedAt: now, UpdatedAt: now},
		{ID: "excluded", UserID: "alice", Name: "Legacy", CreatedAt: now, UpdatedAt: now},
	}
	if err := db.Create(&topics).Error; err != nil {
		t.Fatalf("seed topics: %v", err)
	}
	if err := db.Model(&models.PulseTopic{}).Where("id = ?", "excluded").Update("enabled", false).Error; err != nil {
		t.Fatalf("mark legacy topic: %v", err)
	}

	if err := migrateLegacyPulseTopics(db); err != nil {
		t.Fatalf("migrate legacy topics: %v", err)
	}

	var remaining []models.PulseTopic
	if err := db.Order("id asc").Find(&remaining).Error; err != nil {
		t.Fatalf("load remaining topics: %v", err)
	}
	if len(remaining) != 1 || remaining[0].ID != "current" {
		t.Fatalf("expected only the current topic, got %#v", remaining)
	}
}
