package models

import "time"

type TodoItem struct {
	ID                   string     `json:"id" gorm:"primaryKey"`
	UserID               string     `json:"user_id" gorm:"index;not null;default:0"`
	Title                string     `json:"title" gorm:"index;not null"`
	Notes                string     `json:"notes,omitempty" gorm:"type:text"`
	Status               string     `json:"status" gorm:"index;not null;default:open"`
	StartDate            string     `json:"start_date,omitempty" gorm:"index"`
	DueDate              string     `json:"due_date,omitempty" gorm:"index"`
	DueTime              string     `json:"due_time,omitempty"`
	Timezone             string     `json:"timezone,omitempty"`
	RepeatRule           string     `json:"repeat_rule,omitempty" gorm:"index;not null;default:once"`
	Priority             string     `json:"priority" gorm:"index;not null;default:normal"`
	TagsJSON             string     `json:"tags_json,omitempty" gorm:"type:text"`
	Source               string     `json:"source" gorm:"index;not null;default:manual"`
	OriginConversationID string     `json:"origin_conversation_id,omitempty" gorm:"index"`
	OriginMessageID      uint       `json:"origin_message_id,omitempty" gorm:"index"`
	OriginRunID          string     `json:"origin_run_id,omitempty" gorm:"index"`
	CreatedAt            time.Time  `json:"created_at"`
	UpdatedAt            time.Time  `json:"updated_at"`
	CompletedAt          *time.Time `json:"completed_at,omitempty"`
}

type TodoCompletion struct {
	ID             string    `json:"id" gorm:"primaryKey"`
	TodoID         string    `json:"todo_id" gorm:"index:idx_todo_completion_occurrence,unique;not null"`
	UserID         string    `json:"user_id" gorm:"index;not null;default:0"`
	OccurrenceDate string    `json:"occurrence_date" gorm:"index:idx_todo_completion_occurrence,unique;not null"`
	CompletedAt    time.Time `json:"completed_at"`
	CreatedAt      time.Time `json:"created_at"`
	UpdatedAt      time.Time `json:"updated_at"`
}

type TodoSuggestion struct {
	ID                   string     `json:"id" gorm:"primaryKey"`
	UserID               string     `json:"user_id" gorm:"index;not null;default:0"`
	Title                string     `json:"title" gorm:"index;not null"`
	Notes                string     `json:"notes,omitempty" gorm:"type:text"`
	ProposedStartDate    string     `json:"proposed_start_date,omitempty" gorm:"index"`
	ProposedDueDate      string     `json:"proposed_due_date,omitempty" gorm:"index"`
	Priority             string     `json:"priority" gorm:"index;not null;default:normal"`
	Confidence           int        `json:"confidence" gorm:"not null;default:60"`
	Reason               string     `json:"reason,omitempty" gorm:"type:text"`
	EvidenceJSON         string     `json:"evidence_json,omitempty" gorm:"type:text"`
	Source               string     `json:"source" gorm:"index;not null;default:conversation"`
	State                string     `json:"state" gorm:"index;not null;default:pending"`
	AcceptedTodoID       string     `json:"accepted_todo_id,omitempty" gorm:"index"`
	OriginConversationID string     `json:"origin_conversation_id,omitempty" gorm:"index"`
	OriginMessageID      uint       `json:"origin_message_id,omitempty" gorm:"index"`
	OriginRunID          string     `json:"origin_run_id,omitempty" gorm:"index"`
	CreatedAt            time.Time  `json:"created_at"`
	UpdatedAt            time.Time  `json:"updated_at"`
	ResolvedAt           *time.Time `json:"resolved_at,omitempty"`
}
