package database

import (
	"path/filepath"
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/models"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

func TestInitMigratesLegacyKnowledgeIntoDriveOnce(t *testing.T) {
	dbPath := filepath.Join(t.TempDir(), "assistant.db")
	legacyDB, err := gorm.Open(sqlite.Open(dbPath), &gorm.Config{})
	if err != nil {
		t.Fatalf("open legacy database: %v", err)
	}
	if err := legacyDB.AutoMigrate(&models.KnowledgeProject{}, &models.KnowledgeDocument{}); err != nil {
		t.Fatalf("create legacy schema: %v", err)
	}
	now := time.Now().Add(-time.Hour)
	project := models.KnowledgeProject{
		ID:          "legacy-project",
		UserID:      "alice",
		Name:        "RAG 资料",
		Description: "旧项目说明",
		CreatedAt:   now,
		UpdatedAt:   now,
	}
	document := models.KnowledgeDocument{
		ID:        "legacy-document",
		UserID:    "alice",
		ProjectID: project.ID,
		Title:     "检索笔记",
		Summary:   "旧摘要",
		TagsJSON:  `["RAG","检索"]`,
		Content:   "# 检索笔记\n\n需要召回和重排。",
		CreatedAt: now,
		UpdatedAt: now,
	}
	if err := legacyDB.Create(&project).Error; err != nil {
		t.Fatalf("create legacy project: %v", err)
	}
	if err := legacyDB.Create(&document).Error; err != nil {
		t.Fatalf("create legacy document: %v", err)
	}

	if err := Init(dbPath); err != nil {
		t.Fatalf("initialize migrated database: %v", err)
	}
	assertLegacyKnowledgeMigration(t)

	if err := DB.Delete(&models.DriveItem{}, "user_id = ? AND type = ?", "alice", "file").Error; err != nil {
		t.Fatalf("delete migrated file: %v", err)
	}
	if err := Init(dbPath); err != nil {
		t.Fatalf("initialize migrated database again: %v", err)
	}
	var fileCount int64
	if err := DB.Model(&models.DriveItem{}).
		Where("user_id = ? AND type = ?", "alice", "file").
		Count(&fileCount).Error; err != nil {
		t.Fatalf("count drive files after second init: %v", err)
	}
	if fileCount != 0 {
		t.Fatalf("expected completed migration not to recreate deleted files, got %d", fileCount)
	}
	var marker models.Setting
	if err := DB.First(&marker, "key = ?", legacyKnowledgeMigrationMarkerKey).Error; err != nil {
		t.Fatalf("load migration marker: %v", err)
	}
	if marker.Value != "completed" {
		t.Fatalf("unexpected migration marker: %#v", marker)
	}
}

func assertLegacyKnowledgeMigration(t *testing.T) {
	t.Helper()
	var items []models.DriveItem
	if err := DB.Where("user_id = ?", "alice").Order("type asc, name asc").Find(&items).Error; err != nil {
		t.Fatalf("load migrated drive items: %v", err)
	}
	if len(items) != 4 {
		t.Fatalf("expected root, knowledge folder, project folder and document once, got %#v", items)
	}
	var file models.DriveItem
	if err := DB.First(&file, "user_id = ? AND type = ? AND name = ?", "alice", "file", "检索笔记.md").Error; err != nil {
		t.Fatalf("load migrated document: %v", err)
	}
	if file.Content != "# 检索笔记\n\n需要召回和重排。" || file.Summary != "旧摘要" {
		t.Fatalf("legacy document was not preserved: %#v", file)
	}
	var projectFolder models.DriveItem
	if err := DB.First(&projectFolder, "id = ?", file.ParentID).Error; err != nil {
		t.Fatalf("load migrated project folder: %v", err)
	}
	if projectFolder.Name != "RAG 资料" || projectFolder.Summary != "旧项目说明" {
		t.Fatalf("legacy project was not preserved: %#v", projectFolder)
	}
}
