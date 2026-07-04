package handlers

import (
	"encoding/json"
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

func TestAdminCostsReturnsAccountsAndModuleUsage(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}

	hash, err := hashAccountPassword("hashed-pass")
	if err != nil {
		t.Fatalf("hash password: %v", err)
	}
	now := time.Now().UTC()
	accounts := []models.Account{
		{
			ID:           "acct-a",
			Name:         "Alice",
			NameKey:      accountNameKey("Alice"),
			PasswordHash: "hash-a",
			PasswordView: "plain-a",
			CreatedAt:    now.Add(-3 * time.Hour),
			UpdatedAt:    now.Add(-3 * time.Hour),
		},
		{
			ID:           "acct-b",
			Name:         "Bob",
			NameKey:      accountNameKey("Bob"),
			PasswordHash: hash,
			CreatedAt:    now.Add(-2 * time.Hour),
			UpdatedAt:    now.Add(-2 * time.Hour),
		},
	}
	if err := database.DB.Create(&accounts).Error; err != nil {
		t.Fatalf("create accounts: %v", err)
	}
	usages := []models.TokenUsage{
		{
			UserID:         "acct-a",
			ConversationID: "conv-a",
			MessageID:      1,
			RunID:          "run-a",
			AgentID:        "super_chat",
			Runtime:        "self",
			ModelUsed:      "model-a",
			InputTokens:    10,
			OutputTokens:   5,
			TotalTokens:    15,
			CreatedAt:      now.Add(-30 * time.Minute),
		},
		{
			UserID:         "acct-a",
			ConversationID: "conv-a",
			MessageID:      2,
			RunID:          "run-b",
			AgentID:        "deep_research_v1",
			Runtime:        "self",
			ModelUsed:      "model-b",
			InputTokens:    20,
			OutputTokens:   7,
			TotalTokens:    27,
			CreatedAt:      now.Add(-20 * time.Minute),
		},
		{
			UserID:         "acct-b",
			ConversationID: "conv-b",
			MessageID:      3,
			RunID:          "run-c",
			AgentID:        "super_chat",
			Runtime:        "self",
			ModelUsed:      "model-a",
			InputTokens:    3,
			OutputTokens:   4,
			TotalTokens:    7,
			ImageCount:     1,
			CreatedAt:      now.Add(-10 * time.Minute),
		},
	}
	if err := database.DB.Create(&usages).Error; err != nil {
		t.Fatalf("create usages: %v", err)
	}

	router := gin.New()
	handler := &AdminHandler{}
	router.GET("/api/admin/costs", handler.GetCosts)

	req := httptest.NewRequest(http.MethodGet, "/api/admin/costs", nil)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	var payload CostReportResponse
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if payload.Summary.TotalTokens != 49 || payload.Summary.InputTokens != 33 || payload.Summary.OutputTokens != 16 || payload.Summary.RequestCount != 3 {
		t.Fatalf("unexpected summary: %#v", payload.Summary)
	}
	if payload.Summary.AccountsWithPasswords != 1 {
		t.Fatalf("expected only one visible password, got %#v", payload.Summary)
	}

	alice := findCostAccount(payload.Accounts, "acct-a")
	if alice == nil || !alice.PasswordAvailable || alice.Password != "" || alice.TotalTokens != 42 {
		t.Fatalf("unexpected Alice account summary: %#v", alice)
	}
	bob := findCostAccount(payload.Accounts, "acct-b")
	if bob == nil || bob.PasswordAvailable || bob.PasswordSet != true || bob.TotalTokens != 7 {
		t.Fatalf("unexpected Bob account summary: %#v", bob)
	}

	aliceResearch := findCostModule(payload.Modules, "acct-a", "deep_research_v1")
	if aliceResearch == nil || aliceResearch.TotalTokens != 27 || aliceResearch.ModuleName != "Deep Research" {
		t.Fatalf("unexpected Alice research module summary: %#v", aliceResearch)
	}
}

func TestAdminLoginAndAccountPasswordEndpoint(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}
	if err := database.DB.Create(&models.Account{
		ID:           "acct-a",
		Name:         "Alice",
		NameKey:      accountNameKey("Alice"),
		PasswordHash: "hash-a",
		PasswordView: "plain-a",
		CreatedAt:    time.Now(),
		UpdatedAt:    time.Now(),
	}).Error; err != nil {
		t.Fatalf("create account: %v", err)
	}

	router := gin.New()
	handler := NewAdminHandler(nil)
	router.POST("/api/admin/login", handler.Login)
	protected := router.Group("/api/admin")
	protected.Use(handler.RequireAuth())
	protected.GET("/accounts/:id/password", handler.GetAccountPassword)

	badReq := httptest.NewRequest(http.MethodGet, "/api/admin/accounts/acct-a/password", nil)
	badRecorder := httptest.NewRecorder()
	router.ServeHTTP(badRecorder, badReq)
	if badRecorder.Code != http.StatusUnauthorized {
		t.Fatalf("expected protected endpoint to require login, got %d", badRecorder.Code)
	}

	loginReq := httptest.NewRequest(http.MethodPost, "/api/admin/login", strings.NewReader(`{"password":"admin123"}`))
	loginReq.Header.Set("Content-Type", "application/json")
	loginRecorder := httptest.NewRecorder()
	router.ServeHTTP(loginRecorder, loginReq)
	if loginRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected login status %d: %s", loginRecorder.Code, loginRecorder.Body.String())
	}
	var loginPayload map[string]interface{}
	if err := json.Unmarshal(loginRecorder.Body.Bytes(), &loginPayload); err != nil {
		t.Fatalf("decode login: %v", err)
	}
	token, _ := loginPayload["token"].(string)
	if token == "" {
		t.Fatalf("expected admin token in login response: %#v", loginPayload)
	}

	req := httptest.NewRequest(http.MethodGet, "/api/admin/accounts/acct-a/password", nil)
	req.Header.Set(adminSessionHeader, token)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)
	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected password status %d: %s", recorder.Code, recorder.Body.String())
	}
	var payload map[string]interface{}
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode password response: %v", err)
	}
	if payload["password"] != "plain-a" || payload["password_available"] != true {
		t.Fatalf("unexpected password payload: %#v", payload)
	}
}

func TestAdminCostsUsesTraceFallbackWithoutDoubleCounting(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}
	now := time.Now().UTC()
	if err := database.DB.Create(&models.Account{
		ID:        "acct-a",
		Name:      "Alice",
		NameKey:   accountNameKey("Alice"),
		CreatedAt: now,
		UpdatedAt: now,
	}).Error; err != nil {
		t.Fatalf("create account: %v", err)
	}
	trace := `[
		{"type":"model.completed","payload":{"usage":{"input":100,"output":50}}},
		{"type":"run.completed","payload":{"tokens_used":{"input":7,"output":3,"input_cached":2}}}
	]`
	if err := database.DB.Create(&models.Message{
		ConversationID: "conv-a",
		UserID:         "acct-a",
		Role:           "assistant",
		Content:        "done",
		ModelUsed:      "model-a",
		RunID:          "run-a",
		TraceEvents:    trace,
		CreatedAt:      now,
	}).Error; err != nil {
		t.Fatalf("create message: %v", err)
	}

	router := gin.New()
	handler := &AdminHandler{}
	router.GET("/api/admin/costs", handler.GetCosts)
	req := httptest.NewRequest(http.MethodGet, "/api/admin/costs", nil)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)
	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	var payload CostReportResponse
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if payload.Summary.TotalTokens != 10 || payload.Summary.InputTokens != 7 || payload.Summary.OutputTokens != 3 || payload.Summary.CachedInputTokens != 2 {
		t.Fatalf("trace fallback should use run.completed aggregate, got %#v", payload.Summary)
	}
	if payload.Summary.TraceFallbackRecords != 1 || payload.Summary.TokenUsageRecords != 0 {
		t.Fatalf("unexpected source counts: %#v", payload.Summary)
	}
}

func findCostAccount(accounts []CostAccountSummary, id string) *CostAccountSummary {
	for i := range accounts {
		if accounts[i].ID == id {
			return &accounts[i]
		}
	}
	return nil
}

func findCostModule(modules []CostModuleSummary, accountID string, agentID string) *CostModuleSummary {
	for i := range modules {
		if modules[i].AccountID == accountID && modules[i].AgentID == agentID {
			return &modules[i]
		}
	}
	return nil
}
