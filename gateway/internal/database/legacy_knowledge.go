package database

import (
	"path/filepath"
	"strings"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/google/uuid"
	"gorm.io/gorm"
)

const (
	legacyDriveFolderType             = "folder"
	legacyDriveFileType               = "file"
	legacyKnowledgeMigrationMarkerKey = "migration.legacy_knowledge_to_drive.v1"
)

// migrateLegacyKnowledgeToDrive preserves data created by the retired
// /api/projects knowledge store. Existing legacy tables are intentionally left
// in place; migrated Drive items use deterministic IDs so startup is idempotent.
func migrateLegacyKnowledgeToDrive(db *gorm.DB) error {
	var marker models.Setting
	if err := db.First(&marker, "key = ?", legacyKnowledgeMigrationMarkerKey).Error; err == nil {
		return nil
	} else if err != gorm.ErrRecordNotFound {
		return err
	}
	if !db.Migrator().HasTable(&models.KnowledgeProject{}) &&
		!db.Migrator().HasTable(&models.KnowledgeDocument{}) {
		return nil
	}

	var projects []models.KnowledgeProject
	if db.Migrator().HasTable(&models.KnowledgeProject{}) {
		if err := db.Order("user_id asc, sort_order asc, created_at asc").Find(&projects).Error; err != nil {
			return err
		}
	}
	var documents []models.KnowledgeDocument
	if db.Migrator().HasTable(&models.KnowledgeDocument{}) {
		if err := db.Order("user_id asc, created_at asc").Find(&documents).Error; err != nil {
			return err
		}
	}
	if len(projects) == 0 && len(documents) == 0 {
		return markLegacyKnowledgeMigrationComplete(db)
	}

	projectFolders := make(map[string]string, len(projects))
	knowledgeFolders := make(map[string]string)
	for _, project := range projects {
		userID := normalizeLegacyKnowledgeUserID(project.UserID)
		knowledgeFolderID, err := ensureLegacyKnowledgeFolder(db, userID, knowledgeFolders)
		if err != nil {
			return err
		}
		folderID := uuid.NewSHA1(
			uuid.NameSpaceOID,
			[]byte("legacy-knowledge-project:"+userID+":"+project.ID),
		).String()
		createdAt, updatedAt := legacyKnowledgeTimes(project.CreatedAt, project.UpdatedAt)
		folder := models.DriveItem{
			ID:        folderID,
			UserID:    userID,
			ParentID:  knowledgeFolderID,
			Type:      legacyDriveFolderType,
			Name:      legacyKnowledgeName(project.Name, "未命名项目"),
			Summary:   strings.TrimSpace(project.Description),
			CreatedAt: createdAt,
			UpdatedAt: updatedAt,
		}
		if err := db.Where("id = ?", folderID).Attrs(folder).FirstOrCreate(&folder).Error; err != nil {
			return err
		}
		projectFolders[legacyKnowledgeProjectKey(userID, project.ID)] = folder.ID
	}

	orphanFolders := make(map[string]string)
	for _, document := range documents {
		userID := normalizeLegacyKnowledgeUserID(document.UserID)
		parentID := projectFolders[legacyKnowledgeProjectKey(userID, document.ProjectID)]
		if parentID == "" {
			knowledgeFolderID, err := ensureLegacyKnowledgeFolder(db, userID, knowledgeFolders)
			if err != nil {
				return err
			}
			parentID, err = ensureLegacyOrphanFolder(db, userID, knowledgeFolderID, orphanFolders)
			if err != nil {
				return err
			}
		}
		fileID := uuid.NewSHA1(
			uuid.NameSpaceOID,
			[]byte("legacy-knowledge-document:"+userID+":"+document.ID),
		).String()
		name := legacyKnowledgeName(document.Title, document.SourceName)
		if name == "" {
			name = "未命名文档"
		}
		if filepath.Ext(name) == "" {
			name += ".md"
		}
		content := strings.TrimSpace(strings.ReplaceAll(document.Content, "\u0000", ""))
		summary := strings.TrimSpace(document.Summary)
		if summary == "" {
			summary = legacyKnowledgeSummary(content)
		}
		createdAt, updatedAt := legacyKnowledgeTimes(document.CreatedAt, document.UpdatedAt)
		file := models.DriveItem{
			ID:        fileID,
			UserID:    userID,
			ParentID:  parentID,
			Type:      legacyDriveFileType,
			Name:      name,
			MimeType:  "text/markdown; charset=utf-8",
			Size:      int64(len([]byte(content))),
			Summary:   summary,
			TagsJSON:  document.TagsJSON,
			Content:   content,
			CreatedAt: createdAt,
			UpdatedAt: updatedAt,
		}
		if err := db.Where("id = ?", fileID).Attrs(file).FirstOrCreate(&file).Error; err != nil {
			return err
		}
	}
	return markLegacyKnowledgeMigrationComplete(db)
}

func markLegacyKnowledgeMigrationComplete(db *gorm.DB) error {
	return db.Save(&models.Setting{
		Key:       legacyKnowledgeMigrationMarkerKey,
		Value:     "completed",
		UpdatedAt: time.Now(),
	}).Error
}

func ensureLegacyKnowledgeFolder(
	db *gorm.DB,
	userID string,
	cache map[string]string,
) (string, error) {
	if folderID := cache[userID]; folderID != "" {
		return folderID, nil
	}
	rootID := uuid.NewSHA1(uuid.NameSpaceOID, []byte("drive-root:"+userID)).String()
	now := time.Now()
	root := models.DriveItem{
		ID:        rootID,
		UserID:    userID,
		Type:      legacyDriveFolderType,
		Name:      "我的网盘",
		CreatedAt: now,
		UpdatedAt: now,
	}
	if err := db.Where("id = ?", rootID).Attrs(root).FirstOrCreate(&root).Error; err != nil {
		return "", err
	}

	var folder models.DriveItem
	err := db.Where(
		"user_id = ? AND parent_id = ? AND type = ? AND lower(name) = lower(?)",
		userID,
		rootID,
		legacyDriveFolderType,
		"知识库",
	).First(&folder).Error
	if err == nil {
		cache[userID] = folder.ID
		return folder.ID, nil
	}
	if err != gorm.ErrRecordNotFound {
		return "", err
	}

	folderID := uuid.NewSHA1(uuid.NameSpaceOID, []byte("drive-knowledge:"+userID)).String()
	folder = models.DriveItem{
		ID:        folderID,
		UserID:    userID,
		ParentID:  rootID,
		Type:      legacyDriveFolderType,
		Name:      "知识库",
		CreatedAt: now,
		UpdatedAt: now,
	}
	if err := db.Where("id = ?", folderID).Attrs(folder).FirstOrCreate(&folder).Error; err != nil {
		return "", err
	}
	cache[userID] = folder.ID
	return folder.ID, nil
}

func ensureLegacyOrphanFolder(
	db *gorm.DB,
	userID string,
	knowledgeFolderID string,
	cache map[string]string,
) (string, error) {
	if folderID := cache[userID]; folderID != "" {
		return folderID, nil
	}
	folderID := uuid.NewSHA1(uuid.NameSpaceOID, []byte("legacy-knowledge-orphans:"+userID)).String()
	now := time.Now()
	folder := models.DriveItem{
		ID:        folderID,
		UserID:    userID,
		ParentID:  knowledgeFolderID,
		Type:      legacyDriveFolderType,
		Name:      "未分类",
		CreatedAt: now,
		UpdatedAt: now,
	}
	if err := db.Where("id = ?", folderID).Attrs(folder).FirstOrCreate(&folder).Error; err != nil {
		return "", err
	}
	cache[userID] = folder.ID
	return folder.ID, nil
}

func normalizeLegacyKnowledgeUserID(value string) string {
	if value = strings.TrimSpace(value); value != "" {
		return value
	}
	return models.DefaultAccountID
}

func legacyKnowledgeProjectKey(userID, projectID string) string {
	return userID + "\x00" + strings.TrimSpace(projectID)
}

func legacyKnowledgeName(value, fallback string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		value = strings.TrimSpace(fallback)
	}
	value = strings.ReplaceAll(value, "/", "-")
	value = strings.ReplaceAll(value, "\\", "-")
	value = strings.Join(strings.Fields(value), " ")
	runes := []rune(value)
	if len(runes) > 120 {
		value = strings.TrimSpace(string(runes[:120]))
	}
	return value
}

func legacyKnowledgeSummary(content string) string {
	content = strings.Join(strings.Fields(content), " ")
	runes := []rune(content)
	if len(runes) > 320 {
		return strings.TrimSpace(string(runes[:320])) + "..."
	}
	return content
}

func legacyKnowledgeTimes(createdAt, updatedAt time.Time) (time.Time, time.Time) {
	now := time.Now()
	if createdAt.IsZero() {
		createdAt = now
	}
	if updatedAt.IsZero() {
		updatedAt = createdAt
	}
	return createdAt, updatedAt
}
