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
