package connect

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"gorm.io/gorm"
)

func pause(ctx context.Context, d time.Duration) bool {
	timer := time.NewTimer(d)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-timer.C:
		return true
	}
}
func (s *Service) Start() {
	s.once.Do(func() {
		// Only a single gateway process owns this SQLite-backed worker. Never replay uncertain sends.
		s.db.Model(&models.ConnectDelivery{}).Where("status = ?", "sending").Updates(map[string]any{"status": "unknown", "last_error": "服务重启前的发送结果未确认"})
		s.db.Model(&models.ConnectTurn{}).Where("status = ?", "running").Update("status", "queued") // Runner resumes by stable run ID.
		s.wg.Add(2)
		go func() {
			defer s.wg.Done()
			for s.ctx.Err() == nil {
				s.supervise()
				s.dispatch()
				if !pause(s.ctx, time.Second) {
					return
				}
			}
		}()
		go func() {
			defer s.wg.Done()
			for s.ctx.Err() == nil {
				s.deliver()
				if !pause(s.ctx, time.Second) {
					return
				}
			}
		}()
	})
}
func (s *Service) supervise() {
	var connections []models.ConnectConnection
	if s.db.Where("desired_state = ? AND status <> ?", "enabled", "error").Find(&connections).Error != nil {
		return
	}
	for _, c := range connections {
		if _, ok := s.adapters[c.Kind]; !ok {
			continue
		}
		key := fmt.Sprintf("%s:%d", c.ID, c.Generation)
		s.mu.Lock()
		if s.ctx.Err() != nil {
			s.mu.Unlock()
			return
		}
		fresh, e := s.Get(c.UserID, c.ID)
		if e != nil || fresh.Generation != c.Generation || fresh.DesiredState != "enabled" || fresh.Status == "error" {
			s.mu.Unlock()
			continue
		}
		c = fresh
		if _, exists := s.workers[key]; exists {
			s.mu.Unlock()
			continue
		}
		ctx, cancel := context.WithCancel(s.ctx)
		s.workers[key] = cancel
		s.wg.Add(1)
		s.mu.Unlock()
		go func(c models.ConnectConnection) {
			defer s.wg.Done()
			defer func() { s.mu.Lock(); delete(s.workers, key); s.mu.Unlock() }()
			cfg, err := s.open(c.ID, c.Secret)
			if err != nil {
				return
			}
			for c.Status == "awaiting_auth" || c.Status == "connecting" {
				next, e := s.authenticate(ctx, c, cfg)
				if e != nil || next.Status == "error" {
					return
				}
				c = next
				cfg, err = s.open(c.ID, c.Secret)
				if err != nil {
					return
				}
				if c.Status == "awaiting_auth" && !pause(ctx, 2*time.Second) {
					return
				}
			}
			for ctx.Err() == nil {
				err = s.adapters[c.Kind].Listen(ctx, cfg, func(in Inbound) error {
					_, e := s.Accept(c.ID, c.Generation, in)
					if errors.Is(e, ErrForbidden) || errors.Is(e, ErrConflict) || errors.Is(e, ErrInvalid) {
						return nil
					}
					return e
				}, func() {
					s.mu.Lock()
					defer s.mu.Unlock()
					fresh, e := s.Get(c.UserID, c.ID)
					if e == nil && fresh.Generation == c.Generation && fresh.DesiredState == "enabled" {
						status := "connected"
						if fresh.Sender == "" {
							status = "awaiting_pairing"
						}
						s.db.Model(&fresh).Updates(map[string]any{"last_error": "", "status": status})
					}
				})
				if ctx.Err() != nil {
					return
				}
				s.db.Model(&models.ConnectConnection{}).Where("id = ? AND generation = ? AND desired_state = ?", c.ID, c.Generation, "enabled").Updates(map[string]any{"last_error": publicError(err), "status": "degraded"})
				if !pause(ctx, 10*time.Second) {
					return
				}
				fresh, e := s.Get(c.UserID, c.ID)
				if e != nil || fresh.Generation != c.Generation {
					return
				}
				cfg, err = s.open(c.ID, fresh.Secret)
				if err != nil {
					return
				}
			}
		}(c)
	}
}
func (s *Service) dispatch() {
	if s.runner == nil {
		return
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.ctx.Err() != nil {
		return
	}
	if len(s.running) >= 4 {
		return
	}
	var queued []models.ConnectTurn
	if s.db.Where("status = ?", "queued").Order("created_at ASC").Limit(50).Find(&queued).Error != nil {
		return
	}
	for _, t := range queued {
		if len(s.running) >= 4 {
			return
		}
		var count int64
		s.db.Model(&models.ConnectTurn{}).Where("source_id = ? AND status = ?", t.SourceID, "running").Count(&count)
		if count > 0 {
			continue
		}
		var c models.ConnectConnection
		if s.db.First(&c, "id = ?", t.ConnectionID).Error != nil || c.DesiredState != "enabled" || c.Generation != t.Generation {
			s.db.Model(&t).Update("status", "cancelled")
			continue
		}
		if err := s.db.Transaction(func(tx *gorm.DB) error {
			if t.UserMessageID == 0 {
				m := models.Message{ConversationID: t.ConversationID, UserID: t.UserID, Role: "user", Content: t.Text}
				if err := tx.Create(&m).Error; err != nil {
					return err
				}
				t.UserMessageID = m.ID
			}
			q := tx.Model(&t).Where("status = ?", "queued").Updates(map[string]any{"status": "running", "user_message_id": t.UserMessageID})
			if q.Error != nil {
				return q.Error
			}
			if q.RowsAffected != 1 {
				return ErrConflict
			}
			return nil
		}); err != nil {
			continue
		}
		ctx, cancel := context.WithTimeout(s.ctx, 30*time.Minute)
		s.running[t.ID] = cancel
		s.wg.Add(1)
		go func(t models.ConnectTurn) {
			defer s.wg.Done()
			defer func() { cancel(); s.mu.Lock(); delete(s.running, t.ID); s.mu.Unlock() }()
			notice := time.AfterFunc(10*time.Second, func() { s.enqueueNotice(t, "working", "已收到，正在处理；完成后会发送完整结果。") })
			defer notice.Stop()
			result, err := s.runner.Run(ctx, t, func(event bridge.RunEvent) {
				if event.Type == "approval.required" {
					if ready, ok := event.Payload["ready"].(bool); ok && ready {
						s.enqueueNotice(t, "approval", "这项操作需要授权，请打开工作台中此来源的会话，查看并处理授权请求。")
					}
				}
			})
			// Gateway shutdown detaches from the durable runtime; it must not cancel or replay the model run.
			if s.ctx.Err() != nil {
				return
			}
			if ctx.Err() != nil {
				_ = s.runner.Cancel(t.RunID)
			}
			if e := s.finish(t, result, err); e != nil {
				slog.Error("Connect result persistence failed", "turn_id", t.ID, "error", e)
				s.mu.Lock()
				s.db.Model(&models.ConnectTurn{}).Where("id = ? AND status = ?", t.ID, "running").Update("status", "queued")
				s.mu.Unlock()
			}
		}(t)
	}
}
func (s *Service) enqueueNotice(t models.ConnectTurn, suffix, text string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.ctx.Err() != nil {
		return
	}
	var c models.ConnectConnection
	if s.db.First(&c, "id = ?", t.ConnectionID).Error != nil || c.Generation != t.Generation || c.DesiredState != "enabled" {
		return
	}
	var current models.ConnectTurn
	if s.db.First(&current, "id = ?", t.ID).Error != nil || current.Status != "running" {
		return
	}
	d := models.ConnectDelivery{ID: t.ID + ":" + suffix, TurnID: t.ID, ConnectionID: t.ConnectionID, SourceID: t.SourceID, Generation: t.Generation, Part: -1, Text: text, Status: "pending"}
	s.db.Where("id = ?", d.ID).FirstOrCreate(&d)
}
func (s *Service) finish(t models.ConnectTurn, response *bridge.ChatResponse, runErr error) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.db.Transaction(func(tx *gorm.DB) error {
		var current models.ConnectTurn
		if e := tx.First(&current, "id = ?", t.ID).Error; e != nil {
			return e
		}
		if current.Status != "running" {
			return nil
		}
		text := "任务中断，请在工作台查看结果后重试。"
		status := "failed"
		serialized := ""
		if runErr == nil && response != nil {
			text = RenderText(response)
			status = "completed"
			b, e := json.Marshal(response)
			if e != nil {
				return e
			}
			serialized = string(b)
		}
		current.Status = status
		current.Result = serialized
		if runErr != nil {
			current.Error = "任务未完成，请在工作台查看详情"
		}
		if e := tx.Save(&current).Error; e != nil {
			return e
		}
		if err := tx.Model(&models.ConnectDelivery{}).Where("turn_id = ? AND part < 0 AND status IN ?", t.ID, []string{"pending", "retry_wait"}).Update("status", "revoked").Error; err != nil {
			return err
		}
		if response == nil || runErr != nil {
			response = &bridge.ChatResponse{RunID: t.RunID, Response: text, ErrorType: "connect_interrupted", Runtime: "self"}
		}
		if response != nil {
			if recorder, ok := s.runner.(interface {
				SaveResult(*gorm.DB, models.ConnectTurn, *bridge.ChatResponse) error
			}); ok {
				if e := recorder.SaveResult(tx, t, response); e != nil {
					return e
				}
			} else {
				msg := models.Message{ConversationID: t.ConversationID, UserID: t.UserID, Role: "assistant", Content: response.Response, Reasoning: response.Reasoning, SkillsUsed: jsonString(response.SkillsUsed), Citations: jsonString(response.Citations), Artifacts: jsonString(response.Artifacts), ModelUsed: response.ModelUsed, Runtime: response.Runtime, RunID: t.RunID, TraceEvents: jsonString(response.Events), ErrorType: response.ErrorType}
				if e := tx.Create(&msg).Error; e != nil {
					return e
				}
			}
		}
		if e := tx.Model(&models.Conversation{}).Where("id = ? AND user_id = ?", t.ConversationID, t.UserID).Update("updated_at", time.Now()).Error; e != nil {
			return e
		}
		parts := SplitText(text, 3000)
		for i, part := range parts {
			d := models.ConnectDelivery{ID: fmt.Sprintf("%s:%d", t.ID, i), TurnID: t.ID, ConnectionID: t.ConnectionID, SourceID: t.SourceID, Generation: t.Generation, Part: i, Text: part, Status: "pending"}
			if e := tx.Create(&d).Error; e != nil {
				return e
			}
		}
		return nil
	})
}
func jsonString(v any) string { b, _ := json.Marshal(v); return string(b) }
func (s *Service) deliver() {
	// Delivery is serialized; slow platform I/O never holds the state mutex.
	var list []models.ConnectDelivery
	if s.db.Where("status IN ? AND retry_at <= ?", []string{"pending", "retry_wait"}, time.Now()).Order("created_at ASC, part ASC").Limit(10).Find(&list).Error != nil {
		return
	}
	for _, d := range list {
		s.mu.Lock()
		var c models.ConnectConnection
		var source models.ConnectSource
		if s.db.First(&c, "id = ?", d.ConnectionID).Error != nil || c.Generation != d.Generation || c.DesiredState != "enabled" {
			s.db.Model(&d).Update("status", "revoked")
			s.mu.Unlock()
			continue
		}
		var earlier int64
		s.db.Model(&models.ConnectDelivery{}).Where("turn_id = ? AND part >= 0 AND part < ? AND status <> ?", d.TurnID, d.Part, "sent").Count(&earlier)
		if earlier > 0 {
			s.mu.Unlock()
			continue
		}
		if s.db.First(&source, "id = ?", d.SourceID).Error != nil {
			s.mu.Unlock()
			continue
		}
		cfg, e := s.open(c.ID, c.Secret)
		if e != nil {
			s.mu.Unlock()
			continue
		}
		q := s.db.Model(&d).Where("status IN ?", []string{"pending", "retry_wait"}).Updates(map[string]any{"status": "sending", "attempts": d.Attempts + 1})
		s.mu.Unlock()
		if q.Error != nil || q.RowsAffected != 1 {
			continue
		}
		token := ""
		if source.ContextSecret != "" {
			data, e := s.open(source.ID, source.ContextSecret)
			if e == nil {
				token = data["context_token"]
			}
		}
		ctx, cancel := context.WithTimeout(s.ctx, 20*time.Second)
		remote, err := s.adapters[c.Kind].Send(ctx, cfg, Outgoing{DeliveryID: d.ID, Peer: source.Peer, Text: d.Text, ContextToken: token})
		cancel()
		values := map[string]any{"status": "sent", "remote_id": remote, "last_error": ""}
		if err != nil {
			values["status"] = "failed"
			values["last_error"] = publicError(err)
			var send *SendError
			if errors.As(err, &send) {
				if send.Unknown {
					values["status"] = "unknown"
				} else if send.Retryable && d.Attempts < 4 {
					values["status"] = "retry_wait"
					values["retry_at"] = time.Now().Add(time.Duration(max(send.RetryAfterSeconds, 1<<uint(d.Attempts+1))) * time.Second)
				}
			} else {
				values["status"] = "unknown"
			}
		}
		s.mu.Lock()
		s.db.Model(&d).Where("status = ?", "sending").Updates(values)
		if err == nil {
			s.db.Model(&c).Where("generation = ?", d.Generation).Update("last_outbound_at", time.Now())
		}
		s.mu.Unlock()
	}
}
func (s *Service) RetryDelivery(user, connectionID, deliveryID string) (models.ConnectDelivery, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	c, e := s.Get(user, connectionID)
	if e != nil {
		return models.ConnectDelivery{}, e
	}
	if c.DesiredState != "enabled" {
		return models.ConnectDelivery{}, ErrDisconnected
	}
	var d models.ConnectDelivery
	if e = s.db.First(&d, "id = ? AND connection_id = ?", deliveryID, connectionID).Error; e != nil {
		return d, ErrNotFound
	}
	if d.Status != "failed" && d.Status != "unknown" {
		return d, ErrConflict
	}
	d.Generation = c.Generation
	d.Status = "pending"
	d.Attempts = 0
	d.RetryAt = time.Now()
	d.LastError = ""
	e = s.db.Save(&d).Error
	return d, e
}

// Redact unsupported empty messages instead of presenting an invented model answer.
func nonempty(text string) string {
	if strings.TrimSpace(text) == "" {
		return "本次未生成可显示的文字结果，请在工作台查看产物。"
	}
	return text
}
