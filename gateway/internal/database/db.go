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
	DB, err = gorm.Open(sqlite.Open(dbPath), &gorm.Config{
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
		&models.Setting{},
		&models.PulseTopic{},
		&models.PulseItem{},
		&models.PulseModule{},
		&models.PulseEvent{},
	); err != nil {
		return err
	}

	return ensureDefaultAccount()
}

func ensureDefaultAccount() error {
	now := time.Now()
	account := models.Account{
		ID:        "0",
		Name:      "默认帐号",
		CreatedAt: now,
		UpdatedAt: now,
	}
	return DB.FirstOrCreate(&account, models.Account{ID: "0"}).Error
}
