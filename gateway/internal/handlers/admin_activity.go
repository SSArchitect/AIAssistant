package handlers

import (
	"time"

	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
)

type AdminActivitySummary struct {
	AsOf              time.Time `json:"as_of"`
	WindowDays        int       `json:"window_days"`
	ActiveAccounts    int       `json:"active_accounts"`
	InactiveAccounts  int       `json:"inactive_accounts"`
	MessagingAccounts int       `json:"messaging_accounts"`
}

type AdminAccountActivity struct {
	LastActiveAt                *time.Time `json:"last_active_at,omitempty"`
	LastMessageAt               *time.Time `json:"last_message_at,omitempty"`
	UserMessages7Days           int        `json:"user_messages_7d"`
	AutomaticGenerationEligible bool       `json:"automatic_generation_eligible"`
	LastBackgroundAt            *time.Time `json:"last_background_at,omitempty"`
	BackgroundCost              CostTotals `json:"background_cost"`
}

func isBackgroundUsage(agentID string) bool {
	return agentID == pulseBackgroundAgentID || agentID == focusTodayBackgroundAgentID
}

// Activity and last-seen timestamps are current/all-history values, independent
// of the report's cost date range. BackgroundCost follows that selected range.
func loadAdminAccountActivity(accounts map[string]*CostAccountSummary, now time.Time) (AdminActivitySummary, error) {
	summary := AdminActivitySummary{AsOf: now, WindowDays: int(pulseActiveAccountWindow / (24 * time.Hour))}
	type row struct {
		UserID       string
		LastSeen     int64
		MessageCount int
	}
	var activity []row
	if err := accountActivityRecords().Where("activity.active_at <= ?", now).
		Select("activity.user_id, MAX(unixepoch(activity.active_at)) AS last_seen").
		Group("activity.user_id").Scan(&activity).Error; err != nil {
		return summary, err
	}
	for _, r := range activity {
		if a := accounts[r.UserID]; a != nil && a.Exists {
			at := time.Unix(r.LastSeen, 0)
			a.LastActiveAt = &at
		}
	}
	var eligible []string
	if err := recentAccountActivity(now).Pluck("activity.user_id", &eligible).Error; err != nil {
		return summary, err
	}
	for _, id := range eligible {
		if a := accounts[id]; a != nil && a.Exists {
			a.AutomaticGenerationEligible = true
		}
	}
	var messages []row
	if err := database.DB.Model(&models.Message{}).
		Select("user_id, MAX(unixepoch(created_at)) AS last_seen, SUM(CASE WHEN created_at > ? THEN 1 ELSE 0 END) AS message_count", now.Add(-pulseActiveAccountWindow)).
		Where("role = ? AND created_at <= ?", "user", now).Group("user_id").Scan(&messages).Error; err != nil {
		return summary, err
	}
	for _, r := range messages {
		if a := accounts[r.UserID]; a != nil && a.Exists {
			at := time.Unix(r.LastSeen, 0)
			a.LastMessageAt = &at
			a.UserMessages7Days = r.MessageCount
		}
	}
	var background []row
	if err := database.DB.Model(&models.TokenUsage{}).
		Select("user_id, MAX(unixepoch(created_at)) AS last_seen").
		Where("agent_id IN ? AND created_at <= ?", []string{pulseBackgroundAgentID, focusTodayBackgroundAgentID}, now).
		Group("user_id").Scan(&background).Error; err != nil {
		return summary, err
	}
	for _, r := range background {
		if a := accounts[r.UserID]; a != nil && a.Exists {
			at := time.Unix(r.LastSeen, 0)
			a.LastBackgroundAt = &at
		}
	}
	for _, a := range accounts {
		if !a.Exists {
			continue
		}
		if a.AutomaticGenerationEligible {
			summary.ActiveAccounts++
		} else {
			summary.InactiveAccounts++
		}
		if a.UserMessages7Days > 0 {
			summary.MessagingAccounts++
		}
	}
	return summary, nil
}
