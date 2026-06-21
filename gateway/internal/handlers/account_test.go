package handlers

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"

	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
)

func TestAccountCreateRequiresPasswordAndReturnsToken(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	router := gin.New()
	handler := NewAccountHandler()
	router.POST("/api/accounts", handler.Create)

	body := bytes.NewBufferString(`{"name":"Alice","password":"secret"}`)
	req := httptest.NewRequest(http.MethodPost, "/api/accounts", body)
	req.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusCreated {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	var payload accountAuthResponse
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if payload.Account.Name != "Alice" || !payload.Account.PasswordSet || payload.Token == "" {
		t.Fatalf("unexpected account auth payload: %#v", payload)
	}

	var account models.Account
	if err := database.DB.First(&account, "id = ?", payload.Account.ID).Error; err != nil {
		t.Fatalf("load account: %v", err)
	}
	if account.PasswordHash == "" || account.PasswordHash == "secret" {
		t.Fatalf("expected password hash, got %q", account.PasswordHash)
	}
}

func TestAccountLoginInitializesPasswordForLegacyAccount(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	router := gin.New()
	handler := NewAccountHandler()
	router.POST("/api/accounts/login", handler.Login)

	body := bytes.NewBufferString(`{"id":"0","password":"first-pass"}`)
	req := httptest.NewRequest(http.MethodPost, "/api/accounts/login", body)
	req.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	var payload accountAuthResponse
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if payload.Account.ID != "0" || !payload.Account.PasswordSet || payload.Token == "" {
		t.Fatalf("unexpected login payload: %#v", payload)
	}

	badBody := bytes.NewBufferString(`{"id":"0","password":"wrong-pass"}`)
	badReq := httptest.NewRequest(http.MethodPost, "/api/accounts/login", badBody)
	badReq.Header.Set("Content-Type", "application/json")
	badRecorder := httptest.NewRecorder()
	router.ServeHTTP(badRecorder, badReq)
	if badRecorder.Code != http.StatusUnauthorized {
		t.Fatalf("expected bad password to fail, got %d: %s", badRecorder.Code, badRecorder.Body.String())
	}
}
