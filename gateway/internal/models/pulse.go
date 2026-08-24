package models

import "time"

type PulseTopic struct {
	ID        string    `json:"id" gorm:"primaryKey"`
	UserID    string    `json:"user_id" gorm:"index;not null;default:0"`
	Name      string    `json:"name" gorm:"index"`
	Keywords  string    `json:"keywords,omitempty"` // JSON array
	Enabled   bool      `json:"enabled" gorm:"default:true"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
}

type PulseItem struct {
	ID            string    `json:"id" gorm:"primaryKey"`
	UserID        string    `json:"user_id" gorm:"index;not null;default:0"`
	Date          string    `json:"date" gorm:"index"`
	TopicID       string    `json:"topic_id,omitempty" gorm:"index"`
	TopicName     string    `json:"topic_name,omitempty"`
	Source        string    `json:"source"`
	Category      string    `json:"category,omitempty"`
	Title         string    `json:"title"`
	Summary       string    `json:"summary"`
	HeatScore     int       `json:"heat_score"`
	DetailJSON    string    `json:"detail_json,omitempty" gorm:"type:text"`
	ExplorePrompt string    `json:"explore_prompt,omitempty" gorm:"type:text"`
	CreatedAt     time.Time `json:"created_at"`
	UpdatedAt     time.Time `json:"updated_at"`
}

type PulseModule struct {
	ID        string    `json:"id" gorm:"primaryKey"`
	UserID    string    `json:"user_id" gorm:"index;not null;default:0"`
	Date      string    `json:"date" gorm:"index"`
	Key       string    `json:"key" gorm:"index"`
	Title     string    `json:"title"`
	Summary   string    `json:"summary" gorm:"type:text"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
}

type PulseEvent struct {
	ID           string    `json:"id" gorm:"primaryKey"`
	UserID       string    `json:"user_id" gorm:"index;not null;default:0"`
	Date         string    `json:"date" gorm:"index"`
	ItemID       string    `json:"item_id" gorm:"index;not null"`
	TopicID      string    `json:"topic_id,omitempty" gorm:"index"`
	TopicName    string    `json:"topic_name,omitempty"`
	Source       string    `json:"source,omitempty" gorm:"index"`
	EventType    string    `json:"event_type" gorm:"index;not null"`
	Value        int       `json:"value"`
	MetadataJSON string    `json:"metadata_json,omitempty" gorm:"type:text"`
	CreatedAt    time.Time `json:"created_at"`
}

// PulseScheduleState persists automatic refresh throttling per account. Keeping
// this in the shared database prevents a gateway restart from immediately
// retrying an expensive failed generation.
type PulseScheduleState struct {
	UserID              string     `json:"user_id" gorm:"primaryKey;not null"`
	LastDate            string     `json:"last_date,omitempty" gorm:"index"`
	LastAttemptAt       time.Time  `json:"last_attempt_at" gorm:"index"`
	LastSuccessAt       *time.Time `json:"last_success_at,omitempty"`
	LastStatus          string     `json:"last_status,omitempty" gorm:"index"`
	ConsecutiveFailures int        `json:"consecutive_failures"`
	LastError           string     `json:"last_error,omitempty" gorm:"type:text"`
	UpdatedAt           time.Time  `json:"updated_at"`
}
