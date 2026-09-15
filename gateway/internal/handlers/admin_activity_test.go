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

func TestAdminActivitySeparatesVisitsMessagesAndBackgroundCosts(t *testing.T) {
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatal(err)
	}
	now := time.Now().Add(-time.Minute)
	old := now.Add(-10 * 24 * time.Hour)
	for _, account := range []models.Account{
		{ID: "viewer", Name: "Viewer", NameKey: "viewer", LastActiveAt: &now},
		{ID: "chatter", Name: "Chatter", NameKey: "chatter"},
		{ID: "background", Name: "Background only", NameKey: "background", LastActiveAt: &old},
	} {
		if err := database.DB.Create(&account).Error; err != nil {
			t.Fatal(err)
		}
	}
	for _, message := range []models.Message{
		{UserID: "chatter", Role: "user", Content: "recent", CreatedAt: now},
		{UserID: "chatter", Role: "user", Content: "old", CreatedAt: old},
		{UserID: "background", Role: "assistant", Content: "generated", CreatedAt: now},
	} {
		if err := database.DB.Create(&message).Error; err != nil {
			t.Fatal(err)
		}
	}
	for _, usage := range []models.TokenUsage{
		{UserID: "chatter", AgentID: superChatAgentID, TotalTokens: 70, CreatedAt: now},
		{UserID: "chatter", AgentID: focusTodayBackgroundAgentID, TotalTokens: 30, CreatedAt: now},
		{UserID: "background", AgentID: pulseBackgroundAgentID, TotalTokens: 100, CreatedAt: now},
		{UserID: "background", AgentID: pulseBackgroundAgentID, TotalTokens: 1000, CreatedAt: old},
	} {
		if err := database.DB.Create(&usage).Error; err != nil {
			t.Fatal(err)
		}
	}
	router := gin.New()
	router.GET("/api/admin/costs", (&AdminHandler{}).GetCosts)
	for _, tc := range []struct {
		name, from, to string
		background     int
		requests       int
	}{
		{"recent cost window", now.Add(-24 * time.Hour).Format("2006-01-02"), now.Format("2006-01-02"), 130, 2},
		{"old cost window", old.Format("2006-01-02"), old.Format("2006-01-02"), 1000, 1},
	} {
		t.Run(tc.name, func(t *testing.T) {
			recorder := httptest.NewRecorder()
			router.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/api/admin/costs?from="+tc.from+"&to="+tc.to, nil))
			if recorder.Code != http.StatusOK {
				t.Fatalf("report failed: %d %s", recorder.Code, recorder.Body.String())
			}
			var report CostReportResponse
			if err := json.Unmarshal(recorder.Body.Bytes(), &report); err != nil {
				t.Fatal(err)
			}
			if report.Activity.WindowDays != 7 || report.Activity.ActiveAccounts != 2 || report.Activity.InactiveAccounts != 2 || report.Activity.MessagingAccounts != 1 || report.Activity.AsOf.IsZero() {
				t.Fatalf("activity must stay current regardless of cost filter: %#v", report.Activity)
			}
			if report.Summary.BackgroundCost.TotalTokens != tc.background || report.Summary.BackgroundCost.RequestCount != tc.requests {
				t.Fatalf("background costs must follow date filter: %#v", report.Summary.BackgroundCost)
			}
			viewer := findCostAccount(report.Accounts, "viewer")
			chatter := findCostAccount(report.Accounts, "chatter")
			background := findCostAccount(report.Accounts, "background")
			if viewer == nil || !viewer.AutomaticGenerationEligible || viewer.LastActiveAt == nil || viewer.UserMessages7Days != 0 || viewer.RequestCount != 0 {
				t.Fatalf("visits without any model usage must appear as active: %#v", viewer)
			}
			if chatter == nil || chatter.UserMessages7Days != 1 || chatter.LastMessageAt == nil || !chatter.AutomaticGenerationEligible {
				t.Fatalf("unexpected chat activity: %#v", chatter)
			}
			if background == nil || background.AutomaticGenerationEligible || background.LastMessageAt != nil || background.LastBackgroundAt == nil || background.LastBackgroundAt.Unix() != now.Unix() {
				t.Fatalf("background consumption must not count as real activity: %#v", background)
			}
			for _, account := range report.Accounts {
				if got := NewPulseHandler().accountEligibleForAutomaticPulse(account.ID, report.Activity.AsOf); got != account.AutomaticGenerationEligible {
					t.Fatalf("admin and scheduler disagree for %s", account.ID)
				}
			}
		})
	}
}

func TestAdminActivityBoundaryAndMissingHistory(t *testing.T) {
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, 9, 15, 8, 0, 0, 0, time.UTC)
	cutoff := now.Add(-pulseActiveAccountWindow)
	if err := database.DB.Model(&models.Account{}).Where("id = ?", models.DefaultAccountID).UpdateColumn("last_active_at", cutoff).Error; err != nil {
		t.Fatal(err)
	}
	accounts := map[string]*CostAccountSummary{
		models.DefaultAccountID: {ID: models.DefaultAccountID, Exists: true},
		"deleted":               {ID: "deleted", Exists: false},
	}
	summary, err := loadAdminAccountActivity(accounts, now)
	if err != nil {
		t.Fatal(err)
	}
	if summary.ActiveAccounts != 0 || summary.InactiveAccounts != 1 || accounts[models.DefaultAccountID].LastActiveAt == nil {
		t.Fatalf("seven-day boundary or deleted-account handling failed: %#v", summary)
	}
	if err := database.DB.Migrator().DropTable(&models.PulseEvent{}); err != nil {
		t.Fatal(err)
	}
	if _, err := loadAdminAccountActivity(accounts, now); err == nil {
		t.Fatal("report must not present a failed activity query as zero activity")
	}
}
