package models

import "time"

type DriveItem struct {
	ID                     string    `json:"id" gorm:"primaryKey"`
	UserID                 string    `json:"user_id" gorm:"index;not null;default:0"`
	ParentID               string    `json:"parent_id,omitempty" gorm:"index"`
	Type                   string    `json:"type" gorm:"index;not null"`
	Name                   string    `json:"name" gorm:"index;not null"`
	MimeType               string    `json:"mime_type,omitempty"`
	Encoding               string    `json:"encoding,omitempty"`
	Size                   int64     `json:"size"`
	Summary                string    `json:"summary,omitempty" gorm:"type:text"`
	TagsJSON               string    `json:"tags_json,omitempty" gorm:"type:text"`
	Content                string    `json:"content,omitempty" gorm:"type:text"`
	ExtractedText          string    `json:"extracted_text,omitempty" gorm:"type:text"`
	ExtractionStatus       string    `json:"extraction_status,omitempty" gorm:"index;size:32"`
	ExtractionError        string    `json:"extraction_error,omitempty" gorm:"type:text"`
	ExtractionMetadataJSON string    `json:"extraction_metadata_json,omitempty" gorm:"type:text"`
	ShareEnabled           bool      `json:"share_enabled" gorm:"index;not null;default:false"`
	ShareToken             string    `json:"share_token,omitempty" gorm:"index;size:64"`
	CreatedAt              time.Time `json:"created_at"`
	UpdatedAt              time.Time `json:"updated_at"`
}
