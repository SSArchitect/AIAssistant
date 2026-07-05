package models

import "time"

type KnowledgeProject struct {
	ID          string    `json:"id" gorm:"primaryKey"`
	UserID      string    `json:"user_id" gorm:"index;not null;default:0"`
	Name        string    `json:"name" gorm:"index;not null"`
	Description string    `json:"description,omitempty" gorm:"type:text"`
	SortOrder   int       `json:"sort_order" gorm:"index;not null;default:0"`
	CreatedAt   time.Time `json:"created_at"`
	UpdatedAt   time.Time `json:"updated_at"`
}

type KnowledgeDocument struct {
	ID               string    `json:"id" gorm:"primaryKey"`
	UserID           string    `json:"user_id" gorm:"index;not null;default:0"`
	ProjectID        string    `json:"project_id" gorm:"index;not null"`
	SourceDocumentID string    `json:"source_document_id,omitempty" gorm:"index"`
	Type             string    `json:"type" gorm:"index;not null;default:source"`
	Title            string    `json:"title" gorm:"index;not null"`
	SourceName       string    `json:"source_name,omitempty"`
	Summary          string    `json:"summary" gorm:"type:text"`
	TagsJSON         string    `json:"tags_json,omitempty" gorm:"type:text"`
	Content          string    `json:"content" gorm:"type:text"`
	CreatedAt        time.Time `json:"created_at"`
	UpdatedAt        time.Time `json:"updated_at"`
}

type KnowledgeLink struct {
	ID             string    `json:"id" gorm:"primaryKey"`
	UserID         string    `json:"user_id" gorm:"index;not null;default:0"`
	ProjectID      string    `json:"project_id" gorm:"index;not null"`
	FromDocumentID string    `json:"from_document_id" gorm:"index;not null"`
	ToDocumentID   string    `json:"to_document_id" gorm:"index;not null"`
	Relation       string    `json:"relation" gorm:"index;not null"`
	Explanation    string    `json:"explanation,omitempty" gorm:"type:text"`
	Confidence     int       `json:"confidence" gorm:"not null;default:60"`
	CreatedAt      time.Time `json:"created_at"`
	UpdatedAt      time.Time `json:"updated_at"`
}
