package handlers

import (
	"net/http"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

// RecordActivity is called on a visible page open/resume or a real user gesture.
// Session validation and task polling deliberately do not update this timestamp.
func (h *AccountHandler) RecordActivity(c *gin.Context) {
	userID, ok := requireAccountSessionUserID(c)
	if !ok {
		return
	}
	now := time.Now()
	if err := database.DB.Model(&models.Account{}).
		Where("id = ? AND (last_active_at IS NULL OR last_active_at < ?)", userID, now).
		UpdateColumn("last_active_at", now).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to record account activity"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"status": "ok"})
}

// Existing messages, explicit Pulse actions and session creation preserve known
// activity from before page-activity tracking was introduced. LastUsedAt and model
// usage are excluded: polling and automatic generation can refresh them forever.
func accountActivityRecords() *gorm.DB {
	return database.DB.Table(`(
		SELECT id AS user_id, last_active_at AS active_at FROM accounts
		UNION ALL SELECT user_id, created_at AS active_at FROM messages WHERE role = 'user'
		UNION ALL SELECT user_id, created_at AS active_at FROM account_sessions
		UNION ALL SELECT user_id, created_at AS active_at FROM pulse_events
			WHERE event_type IN ('open', 'like', 'upvote', 'downvote', 'question_click')
	) AS activity`).
		Joins("JOIN accounts ON accounts.id = activity.user_id")
}

func recentAccountActivity(now time.Time) *gorm.DB {
	return accountActivityRecords().
		Where("activity.active_at > ? AND activity.active_at <= ?", now.Add(-pulseActiveAccountWindow), now).
		Group("activity.user_id")
}
