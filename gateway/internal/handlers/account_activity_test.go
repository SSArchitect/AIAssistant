package handlers

import (
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
)

func TestAccountActivityRequiresSessionAndUsesItsAccount(t *testing.T) {
	dbPath := filepath.Join(t.TempDir(), "assistant.db")
	if err := database.Init(dbPath); err != nil {
		t.Fatal(err)
	}
	if err := database.DB.Create(&models.Account{ID: "other", Name: "Other", NameKey: "other"}).Error; err != nil {
		t.Fatal(err)
	}
	token, err := createAccountSession(models.DefaultAccountID)
	if err != nil {
		t.Fatal(err)
	}
	router := gin.New()
	router.POST("/api/accounts/activity", NewAccountHandler().RecordActivity)
	for _, badToken := range []string{"", "invalid"} {
		req := httptest.NewRequest(http.MethodPost, "/api/accounts/activity?user_id=other", nil)
		req.Header.Set("X-Account-Session", badToken)
		recorder := httptest.NewRecorder()
		router.ServeHTTP(recorder, req)
		if recorder.Code != http.StatusUnauthorized {
			t.Fatalf("untrusted activity accepted: %d", recorder.Code)
		}
	}
	before := time.Now()
	req := httptest.NewRequest(http.MethodPost, "/api/accounts/activity?user_id=other", strings.NewReader(`{"user_id":"other","last_active_at":"2099-01-01"}`))
	req.Header.Set("X-Account-Session", token)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)
	if recorder.Code != http.StatusOK {
		t.Fatalf("activity failed: %d %s", recorder.Code, recorder.Body.String())
	}
	var account, other models.Account
	if err := database.DB.First(&account, "id = ?", models.DefaultAccountID).Error; err != nil {
		t.Fatal(err)
	}
	if err := database.DB.First(&other, "id = ?", "other").Error; err != nil {
		t.Fatal(err)
	}
	if account.LastActiveAt == nil || account.LastActiveAt.Before(before) || account.LastActiveAt.After(time.Now()) {
		t.Fatalf("activity must use the server's time: %v", account.LastActiveAt)
	}
	if other.LastActiveAt != nil {
		t.Fatal("body/query identity overrode the authenticated account")
	}
	// The new activity field must survive a gateway/database restart.
	if err := database.Init(dbPath); err != nil {
		t.Fatal(err)
	}
	var restored models.Account
	if err := database.DB.First(&restored, "id = ?", models.DefaultAccountID).Error; err != nil {
		t.Fatal(err)
	}
	if restored.LastActiveAt == nil || !restored.LastActiveAt.Equal(*account.LastActiveAt) {
		t.Fatal("page activity was not persisted across restart")
	}
}

func TestAccountSessionPollingDoesNotRecordPageActivity(t *testing.T) {
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatal(err)
	}
	token, err := createAccountSession(models.DefaultAccountID)
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := accountSessionUserID(token); !ok {
		t.Fatal("session rejected")
	}
	var account models.Account
	if err := database.DB.First(&account, "id = ?", models.DefaultAccountID).Error; err != nil {
		t.Fatal(err)
	}
	if account.LastActiveAt != nil {
		t.Fatal("session validation must not extend page activity")
	}
}
