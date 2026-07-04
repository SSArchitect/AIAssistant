package handlers

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
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
	if alice == nil || !alice.PasswordAvailable || alice.Password != "plain-a" || alice.TotalTokens != 42 {
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
