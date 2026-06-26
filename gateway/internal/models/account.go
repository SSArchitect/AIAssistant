package models

import "time"

type Account struct {
	ID           string    `json:"id" gorm:"primaryKey;size:64"`
	Name         string    `json:"name" gorm:"index;not null"`
	NameKey      string    `json:"-" gorm:"size:64;uniqueIndex"`
	PasswordHash string    `json:"-" gorm:"type:text"`
	CreatedAt    time.Time `json:"created_at"`
	UpdatedAt    time.Time `json:"updated_at"`
}

type AccountSession struct {
	TokenHash  string    `json:"-" gorm:"primaryKey;size:64"`
	UserID     string    `json:"user_id" gorm:"index;not null"`
	CreatedAt  time.Time `json:"created_at"`
	LastUsedAt time.Time `json:"last_used_at"`
}
