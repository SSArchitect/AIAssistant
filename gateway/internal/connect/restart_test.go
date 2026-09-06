package connect

import (
	"context"
	"errors"
	"sync/atomic"
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/models"
)

type restartAdapter struct {
	*fakeAdapter
	authenticate func(context.Context, Config) (AuthResult, error)
	listen       func(context.Context, Config, func(Inbound) error, func()) error
}

func (a *restartAdapter) Authenticate(ctx context.Context, cfg Config) (AuthResult, error) {
	if a.authenticate != nil {
		return a.authenticate(ctx, cfg)
	}
	return a.fakeAdapter.Authenticate(ctx, cfg)
}
func (a *restartAdapter) Listen(ctx context.Context, cfg Config, emit func(Inbound) error, healthy func()) error {
	if a.listen != nil {
		return a.listen(ctx, cfg, emit, healthy)
	}
	return a.fakeAdapter.Listen(ctx, cfg, emit, healthy)
}

func TestRestartRestoresEnabledConnectionsAndKeepsManualDisconnect(t *testing.T) {
	for _, kind := range []string{"weixin", "feishu"} {
		for _, status := range []string{"connected", "degraded", "disconnected"} {
			t.Run(kind+"/"+status, func(t *testing.T) {
				listening := make(chan Config, 4)
				var authCalls atomic.Int32
				a := &restartAdapter{fakeAdapter: &fakeAdapter{kind: kind}}
				a.authenticate = func(ctx context.Context, cfg Config) (AuthResult, error) {
					authCalls.Add(1)
					return a.fakeAdapter.Authenticate(ctx, cfg)
				}
				a.listen = func(ctx context.Context, cfg Config, _ func(Inbound) error, healthy func()) error {
					healthy()
					listening <- cfg
					<-ctx.Done()
					return ctx.Err()
				}
				s := testService(t, a)
				c := createConnected(t, s, kind, "work")
				old := accepted(t, s, c, "before-restart")
				cfg, err := s.open(c.ID, c.Secret)
				if err != nil {
					t.Fatal(err)
				}
				cfg["bot_token"], cfg["cursor"] = "saved-authorization", "saved-cursor"
				secret, err := s.seal(c.ID, cfg)
				if err != nil {
					t.Fatal(err)
				}
				if err := s.db.Model(&c).Updates(map[string]any{"secret": secret, "role_id": "mentor"}).Error; err != nil {
					t.Fatal(err)
				}
				s.Start()
				select {
				case <-listening:
				case <-time.After(3 * time.Second):
					t.Fatal("listener not started")
				}
				if status == "disconnected" {
					c, err = s.Disconnect("alice", c.ID)
					if err != nil {
						t.Fatal(err)
					}
				} else if status == "degraded" {
					if err := s.db.Model(&c).Update("status", "degraded").Error; err != nil {
						t.Fatal(err)
					}
				}
				s.Close()
				before, err := s.Get("alice", c.ID)
				if err != nil {
					t.Fatal(err)
				}
				restarted, err := NewService(s.db, make([]byte, 32), nil, a)
				if err != nil {
					t.Fatal(err)
				}
				t.Cleanup(restarted.Close)
				restarted.Start()
				if status == "disconnected" {
					restarted.supervise()
					restarted.mu.Lock()
					count := len(restarted.workers)
					restarted.mu.Unlock()
					if count != 0 {
						t.Fatal("manually disconnected integration resumed")
					}
				} else {
					select {
					case restored := <-listening:
						if restored["bot_token"] != "saved-authorization" || restored["cursor"] != "saved-cursor" {
							t.Fatal("saved authorization or cursor lost")
						}
					case <-time.After(3 * time.Second):
						t.Fatal("restart did not resume listener")
					}
					replay, err := restarted.Accept(c.ID, c.Generation, Inbound{MessageID: "before-restart", Sender: "sender", Peer: "dm", Text: "request before-restart", ContextToken: "private-context"})
					if err != nil || replay.ID != old.ID {
						t.Fatal("replay lost its original turn", err)
					}
					next := accepted(t, restarted, c, "after-restart")
					if next.ConversationID != old.ConversationID || next.RoleID != "mentor" {
						t.Fatal("restart lost conversation or role")
					}
				}
				after, err := restarted.Get("alice", c.ID)
				if err != nil || after.DesiredState != before.DesiredState || after.Generation != before.Generation || after.Secret != before.Secret || after.RoleID != before.RoleID || authCalls.Load() != 1 {
					t.Fatal("restart changed durable connection settings", err)
				}
			})
		}
	}
}

func TestShutdownDuringAuthorizationCanResumeAfterRestart(t *testing.T) {
	authorizing := make(chan struct{})
	var calls atomic.Int32
	a := &restartAdapter{fakeAdapter: &fakeAdapter{kind: "weixin"}}
	a.authenticate = func(ctx context.Context, cfg Config) (AuthResult, error) {
		switch calls.Add(1) {
		case 1:
			return AuthResult{Config: cfg, NextAction: actionJSON("qr", "test-qr", "scan")}, nil
		case 2:
			close(authorizing)
			<-ctx.Done()
			// Platform adapters wrap cancelled HTTP requests, so checking only errors.Is is insufficient.
			return AuthResult{}, &SendError{Message: "平台请求未确认", Unknown: true}
		default:
			return AuthResult{Config: cfg, RemoteID: "bot", Sender: "sender", Ready: true}, nil
		}
	}
	s := testService(t, a)
	c, err := s.Create(context.Background(), "alice", CreateRequest{Kind: "weixin", Name: "work", RequestID: "create"})
	if err != nil {
		t.Fatal(err)
	}
	s.Start()
	select {
	case <-authorizing:
	case <-time.After(3 * time.Second):
		t.Fatal("authorization not started")
	}
	s.Close()
	stored, err := s.Get("alice", c.ID)
	if err != nil || stored.Status != "awaiting_auth" || stored.DesiredState != "enabled" || stored.LastError != "" || stored.Generation != c.Generation || stored.NextAction != c.NextAction {
		t.Fatal("shutdown persisted a terminal authorization failure", stored, err)
	}
	restarted, err := NewService(s.db, make([]byte, 32), nil, a)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(restarted.Close)
	restarted.Start()
	waitFor(t, func() bool { c, e := restarted.Get("alice", c.ID); return e == nil && c.Status == "connected" })
}

func TestCancelledAuthorizationRequestPreservesStateButRealRejectionFails(t *testing.T) {
	for _, cancelled := range []bool{true, false} {
		t.Run(map[bool]string{true: "cancelled", false: "rejected"}[cancelled], func(t *testing.T) {
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			a := &restartAdapter{fakeAdapter: &fakeAdapter{kind: "feishu"}}
			a.authenticate = func(context.Context, Config) (AuthResult, error) {
				if cancelled {
					cancel()
				}
				return AuthResult{}, errors.New("authentication failed")
			}
			s := testService(t, a)
			c, err := s.Create(ctx, "alice", CreateRequest{Kind: "feishu", Name: "work", RequestID: "create"})
			if cancelled {
				if !errors.Is(err, context.Canceled) {
					t.Fatal(err)
				}
				var stored models.ConnectConnection
				if err := s.db.First(&stored, "id = ?", c.ID).Error; err != nil || stored.Status != "connecting" || stored.LastError != "" {
					t.Fatal(stored, err)
				}
			} else if err != nil || c.Status != "error" || c.LastError == "" {
				t.Fatal(c, err)
			}
		})
	}
}
