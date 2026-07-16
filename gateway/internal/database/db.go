package database

import (
	"os"
	"path/filepath"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/models"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

var DB *gorm.DB

func Init(dbPath string) error {
	dir := filepath.Dir(dbPath)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return err
	}

	var err error
	DB, err = gorm.Open(sqlite.Open(dbPath+"?_busy_timeout=5000"), &gorm.Config{
		Logger: logger.Default.LogMode(logger.Warn),
	})
	if err != nil {
		return err
	}

	if err := DB.AutoMigrate(
		&models.Account{},
		&models.AccountSession{},
		&models.Conversation{},
		&models.Message{},
		&models.TokenUsage{},
		&models.Setting{},
		&models.UserSetting{},
		&models.PulseTopic{},
		&models.PulseItem{},
		&models.PulseModule{},
		&models.PulseEvent{},
		&models.TodoItem{},
		&models.TodoCompletion{},
		&models.TodoSuggestion{},
		&models.DriveItem{},
	); err != nil {
		return err
	}
	if err := migrateLegacyKnowledgeToDrive(DB); err != nil {
		return err
	}

	return ensureDefaultAccount()
}

func ensureDefaultAccount() error {
	now := time.Now()
	account := models.Account{
		ID:        models.DefaultAccountID,
		Name:      models.DefaultAccountName,
		CreatedAt: now,
		UpdatedAt: now,
	}
	return DB.FirstOrCreate(&account, models.Account{ID: models.DefaultAccountID}).Error
}
