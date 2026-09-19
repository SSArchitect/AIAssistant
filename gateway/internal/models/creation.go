package models

import "time"

// Definitions and provenance live above Drive; media bytes only live in DriveItem.
type CreationDefinition struct {
	ID         string    `json:"id" gorm:"primaryKey"`
	UserID     string    `json:"-" gorm:"index;not null"`
	Kind       string    `json:"kind" gorm:"index"` // workflow, workflow_template, image_template, video_template
	Name       string    `json:"name"`
	Definition string    `json:"definition" gorm:"type:text"`
	CreatedAt  time.Time `json:"created_at"`
	UpdatedAt  time.Time `json:"updated_at"`
}
type CreationRun struct {
	ID              string    `json:"id" gorm:"primaryKey"`
	UserID          string    `json:"-" gorm:"index;not null"`
	WorkflowID      string    `json:"workflow_id" gorm:"index"`
	Name            string    `json:"name"`
	Definition      string    `json:"definition" gorm:"type:text"`
	Status          string    `json:"status" gorm:"index"`
	Progress        string    `json:"progress" gorm:"type:text"`
	Error           string    `json:"error,omitempty"`
	CreatedAt       time.Time `json:"created_at"`
	UpdatedAt       time.Time `json:"updated_at"`
	ProjectID       string    `json:"project_id,omitempty" gorm:"index"`
	ProjectRevision int       `json:"project_revision,omitempty"`
	ProjectNodeID   string    `json:"project_node_id,omitempty"`
	NodeRevision    int       `json:"node_revision,omitempty"`
	RequestID       string    `json:"request_id,omitempty" gorm:"index"`
	Snapshot        string    `json:"snapshot,omitempty" gorm:"type:text"`
}

// The project owns dialogue, review decisions and versioned artifact definitions.
// Media contents continue to live solely in DriveItem.
type CreationProject struct {
	NameLocked         bool      `json:"-"`
	AutomaticStatus    string    `json:"automatic_status,omitempty" gorm:"index"`
	AutomaticRequestID string    `json:"-"`
	ID                 string    `json:"id" gorm:"primaryKey"`
	UserID             string    `json:"-" gorm:"index;not null"`
	Name               string    `json:"name"`
	Revision           int       `json:"revision"`
	Document           string    `json:"document" gorm:"type:text"`
	CanvasLayout       string    `json:"canvas_layout" gorm:"type:text"`
	LayoutRevision     int       `json:"layout_revision"`
	Planning           bool      `json:"planning"`
	PlanningRequestID  string    `json:"-"`
	Error              string    `json:"error,omitempty"`
	CreatedAt          time.Time `json:"created_at"`
	UpdatedAt          time.Time `json:"updated_at"`
}
type CreationProjectVersion struct {
	ID        string    `json:"id" gorm:"primaryKey"`
	UserID    string    `json:"-" gorm:"index;not null"`
	ProjectID string    `json:"project_id" gorm:"index"`
	Revision  int       `json:"revision"`
	Plan      string    `json:"plan" gorm:"type:text"`
	CreatedAt time.Time `json:"created_at"`
}
type CreationAsset struct {
	ProjectID      string    `json:"project_id" gorm:"index;not null;default:''"`
	ID             string    `json:"id" gorm:"primaryKey"`
	UserID         string    `json:"-" gorm:"uniqueIndex:creation_asset_file;not null"`
	DriveItemID    string    `json:"drive_item_id" gorm:"uniqueIndex:creation_asset_file;not null"`
	Source         string    `json:"source"`
	RunID          string    `json:"run_id,omitempty" gorm:"index"`
	NodeID         string    `json:"node_id,omitempty"`
	ProviderTaskID string    `json:"provider_task_id,omitempty"`
	CreatedAt      time.Time `json:"created_at"`
}

// Small cached previews are stored separately so asset metadata never reads media bytes.
type CreationThumbnail struct {
	DriveItemID     string `gorm:"primaryKey"`
	SourceUpdatedAt time.Time
	Content         []byte `gorm:"type:blob"`
}
