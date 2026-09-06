package connect

import (
	"errors"
	"strings"

	"github.com/aan/agent-assistant-gateway/internal/models"
	"gorm.io/gorm"
)

const MaxNoteLength = 500

// SetNote changes only connection metadata, without affecting its persona or session.
func (s *Service) SetNote(user, id, note string) (models.ConnectConnection, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	c, err := s.Get(user, id)
	if err != nil {
		return c, err
	}
	note = strings.TrimSpace(note)
	if len([]rune(note)) > MaxNoteLength {
		return c, ErrInvalid
	}
	err = s.db.Model(&c).Update("note", note).Error
	return c, err
}

// Delete removes connection state and credentials while preserving normal chat history.
// A scrubbed tombstone reserves the creation request ID so a delayed retry cannot resurrect it.
func (s *Service) Delete(user, id string) error {
	s.mu.Lock()
	var c models.ConnectConnection
	err := s.db.Unscoped().First(&c, "id = ? AND user_id = ?", id, user).Error
	if err != nil || c.DeletedAt.Valid {
		s.mu.Unlock()
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return ErrNotFound
		}
		return err
	}
	var active []models.ConnectTurn
	err = s.db.Transaction(func(tx *gorm.DB) error {
		if err := tx.Where("connection_id = ? AND status = ?", id, "running").Find(&active).Error; err != nil {
			return err
		}
		for _, model := range []any{&models.ConnectDelivery{}, &models.ConnectCheck{}, &models.ConnectTurn{}, &models.ConnectSource{}} {
			if err := tx.Where("connection_id = ?", id).Delete(model).Error; err != nil {
				return err
			}
		}
		if err := tx.Model(&c).Updates(map[string]any{
			"secret": "", "remote_key": nil, "remote_id": "", "sender": "",
			"name": "", "note": "", "role_id": "default", "next_action": "", "last_error": "",
			"desired_state": "disconnected", "status": "deleted", "generation": c.Generation + 1,
			"last_inbound_at": nil, "last_outbound_at": nil, "last_check_at": nil,
		}).Error; err != nil {
			return err
		}
		return tx.Delete(&c).Error
	})
	if err == nil {
		for key, cancel := range s.workers {
			if strings.HasPrefix(key, id+":") {
				cancel()
			}
		}
		for _, turn := range active {
			if cancel := s.running[turn.ID]; cancel != nil {
				cancel()
			}
		}
	}
	s.mu.Unlock()
	if err == nil && s.runner != nil {
		for _, turn := range active {
			go s.runner.Cancel(turn.RunID)
		}
	}
	return err
}
