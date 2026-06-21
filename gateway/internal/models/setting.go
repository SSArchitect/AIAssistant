package models

import "time"

type Setting struct {
	Key       string    `json:"key" gorm:"primaryKey"`
	Value     string    `json:"value"`
	UpdatedAt time.Time `json:"updated_at"`
}
