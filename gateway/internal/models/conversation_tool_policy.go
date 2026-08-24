package models

import "time"

// ConversationToolPolicy stores a tool permission that applies only to one conversation.
type ConversationToolPolicy struct {
	UserID         string    `json:"user_id" gorm:"primaryKey;size:64"`
	ConversationID string    `json:"conversation_id" gorm:"primaryKey;size:64;index"`
	ToolName       string    `json:"tool_name" gorm:"primaryKey;size:128"`
	Policy         string    `json:"policy" gorm:"size:16;not null"`
	UpdatedAt      time.Time `json:"updated_at"`
}
