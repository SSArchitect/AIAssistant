package handlers

import (
	"database/sql"
	"errors"
	"path/filepath"
	"sync/atomic"
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"gorm.io/gorm"
)

func waitForSessionTouch(t *testing.T, db *gorm.DB, token string) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if _, pending := accountSessionTouches.Load(accountSessionTouchKey{db, accountSessionTokenHash(token)}); !pending {
			return
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatal("background session touch did not drain")
}

func TestSessionValidationThrottlesWritesAndHonorsRevocation(t *testing.T) {
	if err := database.Init(filepath.Join(t.TempDir(), "session.db")); err != nil {
		t.Fatal(err)
	}
	pool, _ := database.DB.DB()
	t.Cleanup(func() { pool.Close() })
	token, err := createAccountSession("alice")
	if err != nil {
		t.Fatal(err)
	}
	var updates atomic.Int32
	database.DB.Callback().Update().Before("gorm:update").Register("test:count_session_writes", func(tx *gorm.DB) {
		if tx.Statement.Table == "account_sessions" {
			updates.Add(1)
		}
	})
	for i := 0; i < 15; i++ {
		if uid, ok := accountSessionUserID(token); !ok || uid != "alice" {
			t.Fatal("valid session rejected")
		}
	}
	if updates.Load() != 0 {
		t.Fatalf("fresh session caused %d writes", updates.Load())
	}
	if err := database.DB.Delete(&models.AccountSession{}, "token_hash = ?", accountSessionTokenHash(token)).Error; err != nil {
		t.Fatal(err)
	}
	if _, ok := accountSessionUserID(token); ok {
		t.Fatal("revoked session cached as valid")
	}
	if _, ok := accountSessionUserID("invalid"); ok {
		t.Fatal("invalid token accepted")
	}
}

func TestStaleSessionAuthenticationDoesNotWaitForWriter(t *testing.T) {
	path := filepath.Join(t.TempDir(), "session.db")
	if err := database.Init(path); err != nil {
		t.Fatal(err)
	}
	db := database.DB
	pool, _ := db.DB()
	t.Cleanup(func() { pool.Close() })
	token, err := createAccountSession("alice")
	if err != nil {
		t.Fatal(err)
	}
	old := time.Now().Add(-time.Hour)
	if err := db.Model(&models.AccountSession{}).Where("token_hash = ?", accountSessionTokenHash(token)).Update("last_used_at", old).Error; err != nil {
		t.Fatal(err)
	}
	writer, err := sql.Open("sqlite3", path+"?_busy_timeout=50")
	if err != nil {
		t.Fatal(err)
	}
	defer writer.Close()
	tx, err := writer.Begin()
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Rollback()
	if _, err := tx.Exec("UPDATE accounts SET name = name WHERE id = '0'"); err != nil {
		t.Fatal(err)
	}
	attempted := make(chan struct{}, 1)
	finished := make(chan struct{}, 1)
	var updates atomic.Int32
	db.Callback().Update().Before("gorm:begin_transaction").Register("test:touch_start", func(tx *gorm.DB) {
		if tx.Statement.Table == "account_sessions" {
			updates.Add(1)
			select {
			case attempted <- struct{}{}:
			default:
			}
		}
	})
	db.Callback().Update().After("gorm:commit_or_rollback_transaction").Register("test:touch_end", func(tx *gorm.DB) {
		if tx.Statement.Table == "account_sessions" {
			select {
			case finished <- struct{}{}:
			default:
			}
		}
	})
	authenticated := make(chan bool, 1)
	go func() { uid, ok := accountSessionUserID(token); authenticated <- ok && uid == "alice" }()
	select {
	case ok := <-authenticated:
		if !ok {
			t.Fatal("valid session rejected while writer is active")
		}
	case <-time.After(time.Second):
		t.Fatal("authentication blocked on telemetry write")
	}
	select {
	case <-attempted:
	case <-time.After(time.Second):
		t.Fatal("no background touch")
	}
	for i := 0; i < 10; i++ {
		if _, ok := accountSessionUserID(token); !ok {
			t.Fatal("session rejected")
		}
	}
	if updates.Load() != 1 {
		t.Fatalf("concurrent touch not coalesced: %d", updates.Load())
	}
	if err := tx.Commit(); err != nil {
		t.Fatal(err)
	}
	select {
	case <-finished:
	case <-time.After(2 * time.Second):
		t.Fatal("touch did not finish")
	}
	var session models.AccountSession
	if err := db.First(&session, "token_hash = ?", accountSessionTokenHash(token)).Error; err != nil {
		t.Fatal(err)
	}
	if !session.LastUsedAt.After(old) {
		t.Fatal("background usage timestamp was not saved")
	}
	waitForSessionTouch(t, db, token)
}

func TestSessionUsageWriteFailureDoesNotRejectLoginAndCanRetry(t *testing.T) {
	if err := database.Init(filepath.Join(t.TempDir(), "session.db")); err != nil {
		t.Fatal(err)
	}
	db := database.DB
	pool, _ := db.DB()
	t.Cleanup(func() { pool.Close() })
	token, err := createAccountSession("alice")
	if err != nil {
		t.Fatal(err)
	}
	old := time.Now().Add(-time.Hour)
	if err := db.Model(&models.AccountSession{}).Where("token_hash = ?", accountSessionTokenHash(token)).Update("last_used_at", old).Error; err != nil {
		t.Fatal(err)
	}
	db.Callback().Update().Before("gorm:begin_transaction").Register("test:fail_usage", func(tx *gorm.DB) { tx.AddError(errors.New("simulated busy writer")) })
	if uid, ok := accountSessionUserID(token); !ok || uid != "alice" {
		t.Fatal("usage failure rejected login")
	}
	waitForSessionTouch(t, db, token)
	var session models.AccountSession
	if err := db.First(&session, "token_hash = ?", accountSessionTokenHash(token)).Error; err != nil {
		t.Fatal(err)
	}
	if !session.LastUsedAt.Equal(old) {
		t.Fatal("failed write changed timestamp")
	}
	db.Callback().Update().Remove("test:fail_usage")
	if _, ok := accountSessionUserID(token); !ok {
		t.Fatal("retry rejected login")
	}
	waitForSessionTouch(t, db, token)
	if err := db.First(&session, "token_hash = ?", accountSessionTokenHash(token)).Error; err != nil {
		t.Fatal(err)
	}
	if !session.LastUsedAt.After(old) {
		t.Fatal("usage write did not retry")
	}
}
