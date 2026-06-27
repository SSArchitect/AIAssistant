package models

import "time"

type Setting struct {
	Key       string    `json:"key" gorm:"primaryKey"`
	Value     string    `json:"value"`
	UpdatedAt time.Time `json:"updated_at"`
}

type UserSetting struct {
	UserID    string    `json:"user_id" gorm:"primaryKey;size:64"`
	Key       string    `json:"key" gorm:"primaryKey;size:160"`
	Value     string    `json:"value"`
	UpdatedAt time.Time `json:"updated_at"`
}
