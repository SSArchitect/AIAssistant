package handlers

import (
	"context"
	"sync"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/models"
	"gorm.io/gorm"
)

const accountSessionTouchInterval = 5 * time.Minute

var accountSessionTouches sync.Map
var accountSessionTouchSlots = make(chan struct{}, 2)

type accountSessionTouchKey struct {
	db        *gorm.DB
	tokenHash string
}

// Usage bookkeeping must never delay authentication. We still query the session
// on every request, so deletion/revocation takes effect without a cache TTL.
func touchAccountSessionAsync(db *gorm.DB, session models.AccountSession, now time.Time) {
	cutoff := now.Add(-accountSessionTouchInterval)
	if session.LastUsedAt.After(cutoff) {
		return
	}
	key := accountSessionTouchKey{db, session.TokenHash}
	if _, pending := accountSessionTouches.LoadOrStore(key, struct{}{}); pending {
		return
	}
	select {
	case accountSessionTouchSlots <- struct{}{}:
	default:
		accountSessionTouches.Delete(key)
		return // Best effort; a later request can retry.
	}
	go func() {
		defer func() { <-accountSessionTouchSlots; accountSessionTouches.Delete(key) }()
		ctx, cancel := context.WithTimeout(context.Background(), time.Second)
		defer cancel()
		// Capture the DB handle; never use a later global DB or resurrect a deleted session.
		db.WithContext(ctx).Model(&models.AccountSession{}).
			Where("token_hash = ? AND last_used_at <= ?", session.TokenHash, cutoff).
			Update("last_used_at", now)
	}()
}
