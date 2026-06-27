package models

import "time"

type Conversation struct {
	ID        string    `json:"id" gorm:"primaryKey"`
	UserID    string    `json:"user_id" gorm:"index;not null;default:0"`
	AgentID   string    `json:"agent_id" gorm:"not null;default:super_chat"`
	Title     string    `json:"title"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
}

type Message struct {
	ID             uint      `json:"id" gorm:"primaryKey;autoIncrement"`
	ConversationID string    `json:"conversation_id" gorm:"index"`
	UserID         string    `json:"user_id" gorm:"index;not null;default:0"`
	Role           string    `json:"role"` // "user", "assistant"
	Content        string    `json:"content"`
	SkillsUsed     string    `json:"skills_used,omitempty"` // JSON array
	Citations      string    `json:"citations,omitempty"`   // JSON array
	ModelUsed      string    `json:"model_used,omitempty"`
	Runtime        string    `json:"runtime,omitempty"`
	RunID          string    `json:"run_id,omitempty" gorm:"index"`
	TraceEvents    string    `json:"trace_events,omitempty"` // JSON array
	FollowUps      string    `json:"follow_ups,omitempty"`   // JSON array
	ErrorType      string    `json:"error_type,omitempty"`
	CreatedAt      time.Time `json:"created_at"`
}
