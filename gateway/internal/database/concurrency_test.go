package database

import (
	"database/sql"
	"path/filepath"
	"testing"

	"github.com/aan/agent-assistant-gateway/internal/models"
)

func TestWALReadersContinueDuringWriterTransaction(t *testing.T) {
	path := filepath.Join(t.TempDir(), "concurrent.db")
	if err := Init(path); err != nil {
		t.Fatal(err)
	}
	pool, _ := DB.DB()
	t.Cleanup(func() { pool.Close() })
	var mode string
	if err := DB.Raw("PRAGMA journal_mode").Scan(&mode).Error; err != nil {
		t.Fatal(err)
	}
	if mode != "wal" {
		t.Fatalf("journal_mode=%s, want wal", mode)
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
	if _, err := tx.Exec("UPDATE accounts SET name = 'pending' WHERE id = '0'"); err != nil {
		t.Fatal(err)
	}
	var account models.Account
	if err := DB.First(&account, "id = ?", "0").Error; err != nil {
		t.Fatal(err)
	}
	if account.Name == "pending" {
		t.Fatal("reader saw uncommitted write")
	}
	if err := tx.Commit(); err != nil {
		t.Fatal(err)
	}
	if err := DB.First(&account, "id = ?", "0").Error; err != nil || account.Name != "pending" {
		t.Fatalf("committed write missing: %v, %s", err, account.Name)
	}
}
