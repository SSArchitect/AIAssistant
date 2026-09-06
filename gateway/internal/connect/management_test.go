package connect

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"gorm.io/gorm"
)

func TestConnectionNoteCreateEditClearAndOwnership(t *testing.T) {
	s := testService(t, &fakeAdapter{kind: "feishu"})
	req := CreateRequest{Kind: "feishu", Name: "work", RequestID: "create", Note: "  工作账号\n项目通知  ", Credentials: Config{"app_id": "work", "sender": "sender"}}
	c, err := s.Create(context.Background(), "alice", req)
	if err != nil || c.Note != "工作账号\n项目通知" {
		t.Fatal(c, err)
	}
	if _, err = s.SetNote("bob", c.ID, "changed"); !errors.Is(err, ErrNotFound) {
		t.Fatal(err)
	}
	for _, note := range []string{strings.Repeat("备", 500), ""} {
		got, err := s.SetNote("alice", c.ID, note)
		if err != nil || got.Note != note || got.Secret != c.Secret || got.Generation != c.Generation || got.RoleID != c.RoleID || got.Status != c.Status {
			t.Fatal(got, err)
		}
		stored, err := s.Get("alice", c.ID)
		if err != nil || stored.Note != note {
			t.Fatal(stored, err)
		}
	}
	if _, err = s.SetNote("alice", c.ID, strings.Repeat("备", 501)); !errors.Is(err, ErrInvalid) {
		t.Fatal(err)
	}
	replay, err := s.Create(context.Background(), "alice", req)
	if err != nil || replay.ID != c.ID || replay.Note != "" {
		t.Fatal("creation retry must keep the edited note", replay, err)
	}
	req.RequestID, req.Note = "too-long", strings.Repeat("备", 501)
	if _, err = s.Create(context.Background(), "alice", req); !errors.Is(err, ErrInvalid) {
		t.Fatal(err)
	}
	if _, err = s.Disconnect("alice", c.ID); err != nil {
		t.Fatal(err)
	}
	got, err := s.SetNote("alice", c.ID, " 离线备用 ")
	if err != nil || got.Note != "离线备用" || got.DesiredState != "disconnected" {
		t.Fatal(got, err)
	}
}

func TestDeleteConnectionRemovesBindingsAndWorkButKeepsHistory(t *testing.T) {
	s := testService(t, &fakeAdapter{kind: "feishu"})
	c := createConnected(t, s, "feishu", "work")
	other := createConnected(t, s, "feishu", "other")
	turn := accepted(t, s, c, "1")
	for _, row := range []any{
		&models.Message{ConversationID: turn.ConversationID, UserID: "alice", Role: "user", Content: "history"},
		&models.ConnectCheck{ID: "check", ConnectionID: c.ID},
		&models.ConnectDelivery{ID: "delivery", ConnectionID: c.ID, TurnID: turn.ID, Status: "pending"},
	} {
		if err := s.db.Create(row).Error; err != nil {
			t.Fatal(err)
		}
	}
	if err := s.Delete("bob", c.ID); !errors.Is(err, ErrNotFound) {
		t.Fatal(err)
	}
	for i := 0; i < 2; i++ {
		if err := s.Delete("alice", c.ID); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := s.Get("alice", c.ID); !errors.Is(err, ErrNotFound) {
		t.Fatal(err)
	}
	if _, err := s.SetNote("alice", c.ID, "revive"); !errors.Is(err, ErrNotFound) {
		t.Fatal(err)
	}
	if _, err := s.Reconnect(context.Background(), "alice", c.ID, nil); !errors.Is(err, ErrNotFound) {
		t.Fatal(err)
	}
	items, err := s.List("alice")
	if err != nil || len(items) != 1 || items[0].ID != other.ID {
		t.Fatal(items, err)
	}
	for _, row := range []any{&models.ConnectSource{}, &models.ConnectTurn{}, &models.ConnectDelivery{}, &models.ConnectCheck{}} {
		var count int64
		if err := s.db.Model(row).Where("connection_id = ?", c.ID).Count(&count).Error; err != nil || count != 0 {
			t.Fatalf("retained %T: %d %v", row, count, err)
		}
	}
	var tombstone models.ConnectConnection
	if err := s.db.Unscoped().First(&tombstone, "id = ?", c.ID).Error; err != nil || !tombstone.DeletedAt.Valid || tombstone.Secret != "" || tombstone.RemoteKey != nil || tombstone.Note != "" || tombstone.Sender != "" {
		t.Fatal(tombstone, err)
	}
	var count int64
	s.db.Model(&models.Conversation{}).Where("id = ?", turn.ConversationID).Count(&count)
	if count != 1 {
		t.Fatal("conversation removed")
	}
	s.db.Model(&models.Message{}).Where("conversation_id = ?", turn.ConversationID).Count(&count)
	if count != 1 {
		t.Fatal("history removed")
	}
	req := CreateRequest{Kind: "feishu", Name: "work", RequestID: "work", Credentials: Config{"app_id": "work", "sender": "sender"}}
	if _, err := s.Create(context.Background(), "alice", req); !errors.Is(err, ErrConflict) {
		t.Fatal("stale creation revived deletion", err)
	}
	if _, err := s.Accept(c.ID, c.Generation, Inbound{MessageID: "late", Sender: "sender", Peer: "dm", Text: "late"}); !errors.Is(err, ErrNotFound) {
		t.Fatal(err)
	}
	if err := s.finish(turn, &bridge.ChatResponse{Response: "late"}, nil); !errors.Is(err, gorm.ErrRecordNotFound) {
		t.Fatal(err)
	}
	req.RequestID = "new-creation"
	fresh, err := s.Create(context.Background(), "alice", req)
	if err != nil || fresh.ID == c.ID || fresh.Status != "connected" {
		t.Fatal("remote binding not released", fresh, err)
	}
	if next := accepted(t, s, fresh, "1"); next.ConversationID == turn.ConversationID {
		t.Fatal("deleted source reused")
	}
}

func TestDeleteConnectionCancelsListenerAndActiveRun(t *testing.T) {
	listening, stopped := make(chan struct{}), make(chan struct{})
	a := &restartAdapter{fakeAdapter: &fakeAdapter{kind: "feishu"}, listen: func(ctx context.Context, _ Config, _ func(Inbound) error, healthy func()) error {
		healthy()
		close(listening)
		<-ctx.Done()
		close(stopped)
		return ctx.Err()
	}}
	s := testService(t, a)
	c := createConnected(t, s, "feishu", "work")
	r := &controlledRunner{started: make(chan models.ConnectTurn, 1), release: make(chan struct{})}
	s.runner = r
	accepted(t, s, c, "run")
	s.supervise()
	s.dispatch()
	select {
	case <-listening:
	case <-time.After(3 * time.Second):
		t.Fatal("listener never started")
	}
	select {
	case <-r.started:
	case <-time.After(3 * time.Second):
		t.Fatal("run never started")
	}
	if err := s.Delete("alice", c.ID); err != nil {
		t.Fatal(err)
	}
	select {
	case <-stopped:
	case <-time.After(3 * time.Second):
		t.Fatal("listener not stopped")
	}
	waitFor(t, func() bool { s.mu.Lock(); defer s.mu.Unlock(); return len(s.running) == 0 && len(s.workers) == 0 })
	var count int64
	s.db.Model(&models.ConnectDelivery{}).Count(&count)
	if count != 0 {
		t.Fatal("late run created a delivery")
	}
}

func TestDeleteConnectionRejectsLateCheckAndAuthorization(t *testing.T) {
	for _, operation := range []string{"check", "authorize"} {
		t.Run(operation, func(t *testing.T) {
			started, release, done := make(chan struct{}), make(chan struct{}), make(chan error, 1)
			a := &restartAdapter{fakeAdapter: &fakeAdapter{kind: "feishu"}}
			s := testService(t, a)
			c := createConnected(t, s, "feishu", "work")
			if operation == "check" {
				a.check = func(context.Context, Config) ([]Diagnostic, error) { close(started); <-release; return nil, nil }
				go func() { _, err := s.Check(context.Background(), "alice", c.ID); done <- err }()
			} else {
				a.authenticate = func(ctx context.Context, cfg Config) (AuthResult, error) {
					close(started)
					<-release
					return a.fakeAdapter.Authenticate(ctx, cfg)
				}
				go func() { _, err := s.Reconnect(context.Background(), "alice", c.ID, nil); done <- err }()
			}
			<-started
			err := s.Delete("alice", c.ID)
			close(release)
			if err != nil {
				t.Fatal(err)
			}
			if err := <-done; err == nil {
				t.Fatal("late operation succeeded after deletion")
			}
			var count int64
			s.db.Model(&models.ConnectConnection{}).Count(&count)
			if count != 0 {
				t.Fatal("connection revived")
			}
			s.db.Model(&models.ConnectCheck{}).Count(&count)
			if count != 0 {
				t.Fatal("orphaned check")
			}
		})
	}
}
