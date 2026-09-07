package models

import (
	"time"

	"gorm.io/gorm"
)

// ConnectConnection is a stable user integration, not a network socket.
type ConnectConnection struct {
	ID             string         `json:"id" gorm:"primaryKey"`
	UserID         string         `json:"-" gorm:"uniqueIndex:idx_connect_request,priority:1;index"`
	RequestID      string         `json:"-" gorm:"uniqueIndex:idx_connect_request,priority:2"`
	RequestHash    string         `json:"-"`
	Kind           string         `json:"kind"`
	Name           string         `json:"name"`
	Note           string         `json:"note" gorm:"default:''"`
	RoleID         string         `json:"role_id" gorm:"default:default"`
	RemoteKey      *string        `json:"-" gorm:"uniqueIndex"`
	RemoteID       string         `json:"remote_id,omitempty"`
	Sender         string         `json:"sender,omitempty"`
	Secret         string         `json:"-"`
	DesiredState   string         `json:"desired_state"`
	Status         string         `json:"status"`
	Generation     uint64         `json:"generation"`
	NextAction     string         `json:"next_action,omitempty"`
	LastError      string         `json:"last_error,omitempty"`
	LastInboundAt  *time.Time     `json:"last_inbound_at,omitempty"`
	LastOutboundAt *time.Time     `json:"last_outbound_at,omitempty"`
	LastCheckAt    *time.Time     `json:"last_check_at,omitempty"`
	CreatedAt      time.Time      `json:"created_at"`
	UpdatedAt      time.Time      `json:"updated_at"`
	DeletedAt      gorm.DeletedAt `json:"-" gorm:"index"`
}
type ConnectSource struct {
	ID             string     `json:"id" gorm:"primaryKey"`
	ConnectionID   string     `json:"connection_id" gorm:"index"`
	UserID         string     `json:"-" gorm:"index"`
	Peer           string     `json:"peer"`
	Sender         string     `json:"sender"`
	Thread         string     `json:"thread,omitempty"`
	Epoch          uint64     `json:"epoch"`
	ConversationID string     `json:"conversation_id"`
	ContextSecret  string     `json:"-"`
	LastMessageAt  *time.Time `json:"-"`
	CreatedAt      time.Time  `json:"created_at"`
	UpdatedAt      time.Time  `json:"updated_at"`
}
type ConnectTurn struct {
	Request        string    `json:"-"`
	UserMessageID  uint      `json:"-"`
	ID             string    `json:"id" gorm:"primaryKey"`
	SourceID       string    `json:"source_id" gorm:"uniqueIndex:idx_connect_message,priority:1;index"`
	ExternalID     string    `json:"-" gorm:"uniqueIndex:idx_connect_message,priority:2"`
	PayloadHash    string    `json:"-"`
	ConnectionID   string    `json:"connection_id" gorm:"index"`
	Generation     uint64    `json:"-"`
	UserID         string    `json:"-" gorm:"index"`
	ConversationID string    `json:"conversation_id"`
	RunID          string    `json:"run_id"`
	RoleID         string    `json:"role_id" gorm:"default:default"`
	Text           string    `json:"text"`
	Status         string    `json:"status" gorm:"index"`
	Result         string    `json:"-"`
	Error          string    `json:"error,omitempty"`
	CreatedAt      time.Time `json:"created_at" gorm:"index"`
	UpdatedAt      time.Time `json:"updated_at"`
}
type ConnectDelivery struct {
	ID           string    `json:"id" gorm:"primaryKey"`
	TurnID       string    `json:"turn_id" gorm:"index"`
	ConnectionID string    `json:"connection_id" gorm:"index"`
	SourceID     string    `json:"source_id"`
	Generation   uint64    `json:"-"`
	Part         int       `json:"part"`
	Text         string    `json:"text"`
	Status       string    `json:"status" gorm:"index"`
	RemoteID     string    `json:"remote_id,omitempty"`
	Attempts     int       `json:"attempts"`
	RetryAt      time.Time `json:"retry_at"`
	LastError    string    `json:"last_error,omitempty"`
	CreatedAt    time.Time `json:"created_at"`
	UpdatedAt    time.Time `json:"updated_at"`
}
type ConnectCheck struct {
	ID           string    `json:"id" gorm:"primaryKey"`
	ConnectionID string    `json:"connection_id" gorm:"index"`
	Generation   uint64    `json:"generation"`
	Status       string    `json:"status"`
	Results      string    `json:"results"`
	CreatedAt    time.Time `json:"created_at"`
}
