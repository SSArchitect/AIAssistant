package handlers

import (
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
)

func TestPulseActivityEligibilitySourcesAndBoundary(t *testing.T) {
	now := time.Date(2026, 9, 15, 8, 0, 0, 0, time.UTC)
	for _, tc := range []struct {
		name string
		kind string
		age  time.Duration
		want bool
	}{
		{"recent page visit", "page", time.Hour, true},
		{"seven days without a visit", "page", 7 * 24 * time.Hour, false},
		{"just inside seven days", "page", 7*24*time.Hour - time.Second, true},
		{"old page visit", "page", 8 * 24 * time.Hour, false},
		{"future activity", "page", -time.Hour, false},
		{"chat without browser session", "user", time.Hour, true},
		{"old chat", "user", 8 * 24 * time.Hour, false},
		{"assistant output", "assistant", time.Hour, false},
		{"recent login", "login", time.Hour, true},
		{"old login with current polling", "login", 8 * 24 * time.Hour, false},
		{"opened a Pulse card", "open", time.Hour, true},
		{"Pulse like", "like", time.Hour, true},
		{"automatic exposure", "exposure", time.Hour, false},
		{"background token usage", "usage", time.Hour, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
				t.Fatal(err)
			}
			at := now.Add(-tc.age)
			userID := models.DefaultAccountID
			var err error
			switch tc.kind {
			case "page":
				err = database.DB.Model(&models.Account{}).Where("id = ?", userID).UpdateColumn("last_active_at", at).Error
			case "user", "assistant":
				err = database.DB.Create(&models.Message{UserID: userID, Role: tc.kind, Content: "test", CreatedAt: at}).Error
			case "login":
				err = database.DB.Create(&models.AccountSession{TokenHash: "test", UserID: userID, CreatedAt: at, LastUsedAt: now}).Error
			case "usage":
				err = database.DB.Create(&models.TokenUsage{UserID: userID, AgentID: pulseBackgroundAgentID, TotalTokens: 100, CreatedAt: at}).Error
			default:
				err = database.DB.Create(&models.PulseEvent{ID: "event", UserID: userID, ItemID: "item", EventType: tc.kind, CreatedAt: at}).Error
			}
			if err != nil {
				t.Fatal(err)
			}
			if got := NewPulseHandler().accountEligibleForAutomaticPulse(userID, now); got != tc.want {
				t.Fatalf("eligible=%v, want %v", got, tc.want)
			}
		})
	}
}

func TestPulseActivityCheckFailsClosed(t *testing.T) {
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatal(err)
	}
	if err := database.DB.Migrator().DropTable(&models.PulseEvent{}); err != nil {
		t.Fatal(err)
	}
	handler := NewPulseHandler()
	if handler.accountEligibleForAutomaticPulse(models.DefaultAccountID, time.Now()) {
		t.Fatal("a failed activity query must not permit automatic generation")
	}
	if got := handler.scheduledPulseUserIDs(); len(got) != 0 {
		t.Fatalf("a failed activity query returned scheduled accounts: %v", got)
	}
}

func TestPulseInactiveAccountCanManuallyRefresh(t *testing.T) {
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatal(err)
	}
	requests := make(chan struct{}, 100)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests <- struct{}{}
		http.NotFound(w, r)
	}))
	defer server.Close()
	handler := NewPulseHandler(bridge.NewAgentClient(server.URL, time.Second))
	date := time.Now().Format("2006-01-02")
	if !handler.startPulseGeneration(date, models.DefaultAccountID, true, "manual_refresh") {
		t.Fatal("manual refresh should be allowed even without previous activity")
	}
	waitPulseActivityJob(t, handler, date)
	if len(requests) == 0 {
		t.Fatal("manual refresh did not reach the agent")
	}
}

func TestPulseSchedulerIgnoresPollingOnlySessions(t *testing.T) {
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatal(err)
	}
	now := time.Now()
	if err := database.DB.Create(&models.AccountSession{
		TokenHash: "polling-only", UserID: models.DefaultAccountID,
		CreatedAt: now.Add(-30 * 24 * time.Hour), LastUsedAt: now,
	}).Error; err != nil {
		t.Fatal(err)
	}
	if got := NewPulseHandler().scheduledPulseUserIDs(); len(got) != 0 {
		t.Fatalf("automatic polling must not qualify an inactive account: %v", got)
	}
}

func TestPulseAutomaticEntrypointsRejectInactiveAccounts(t *testing.T) {
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.NotFound(w, r)
	}))
	defer server.Close()
	handler := NewPulseHandler(bridge.NewAgentClient(server.URL, time.Second))
	date := time.Now().Format("2006-01-02")
	for _, reason := range []string{"scheduled:test", "get_quality_refresh"} {
		if handler.startPulseGeneration(date, models.DefaultAccountID, true, reason) {
			// Drain any mistakenly started work before the next test swaps the DB.
			waitPulseActivityJob(t, handler, date)
			t.Errorf("inactive account started automatic Pulse: %s", reason)
		}
	}
	for _, reason := range []string{"scheduled:test", "get_cache_miss"} {
		if handler.startFocusTodayBackfill(date, models.DefaultAccountID, reason) {
			waitPulseActivityJob(t, handler, date)
			t.Errorf("inactive account started automatic Focus Today: %s", reason)
		}
	}
	var attempts int64
	if err := database.DB.Model(&models.PulseScheduleState{}).Count(&attempts).Error; err != nil {
		t.Fatal(err)
	}
	if attempts != 0 {
		t.Errorf("skipped inactive accounts must not consume cooldown: %d", attempts)
	}
}

func waitPulseActivityJob(t *testing.T, handler *PulseHandler, date string) {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for handler.pulseGenerationActive(date, models.DefaultAccountID) && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if handler.pulseGenerationActive(date, models.DefaultAccountID) {
		t.Fatal("background job did not finish")
	}
}
