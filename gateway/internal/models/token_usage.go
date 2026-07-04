package models

import "time"

type TokenUsage struct {
	ID                       uint      `json:"id" gorm:"primaryKey;autoIncrement"`
	UserID                   string    `json:"user_id" gorm:"index;not null;default:0"`
	ConversationID           string    `json:"conversation_id" gorm:"index;not null"`
	MessageID                uint      `json:"message_id" gorm:"index;not null"`
	RunID                    string    `json:"run_id" gorm:"index"`
	AgentID                  string    `json:"agent_id" gorm:"index;not null;default:super_chat"`
	Runtime                  string    `json:"runtime"`
	ModelUsed                string    `json:"model_used"`
	InputTokens              int       `json:"input_tokens"`
	OutputTokens             int       `json:"output_tokens"`
	TotalTokens              int       `json:"total_tokens"`
	CachedInputTokens        int       `json:"cached_input_tokens"`
	CacheCreationInputTokens int       `json:"cache_creation_input_tokens"`
	ImageCount               int       `json:"image_count"`
	UsageJSON                string    `json:"usage_json" gorm:"type:text"`
	CreatedAt                time.Time `json:"created_at"`
}
