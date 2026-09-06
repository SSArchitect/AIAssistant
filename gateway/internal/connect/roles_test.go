package connect

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/models"
)

type roleRunner struct {
	lookup func(context.Context, string) ([]Role, error)
}

func (r *roleRunner) ListRoles(ctx context.Context, user string) ([]Role, error) {
	return r.lookup(ctx, user)
}
func (*roleRunner) Run(context.Context, models.ConnectTurn, func(bridge.RunEvent)) (*bridge.ChatResponse, error) {
	panic("not started")
}
func (*roleRunner) Cancel(string) error { return nil }

func TestConnectionRoleSnapshotNewConversationAndReplay(t *testing.T) {
	s := testService(t, &fakeAdapter{kind: "weixin"})
	s.runner = &roleRunner{lookup: func(ctx context.Context, user string) ([]Role, error) {
		if user != "alice" {
			t.Fatalf("wrong owner: %s", user)
		}
		if _, ok := ctx.Deadline(); !ok {
			t.Fatal("role lookup is unbounded")
		}
		return []Role{{ID: "default"}, {ID: "mentor"}}, nil
	}}
	req := CreateRequest{Kind: "weixin", Name: "personal", RequestID: "create", RoleID: "mentor", Credentials: Config{"app_id": "bot", "sender": "sender"}}
	c, err := s.Create(context.Background(), "alice", req)
	if err != nil || c.RoleID != "mentor" {
		t.Fatal(c, err)
	}
	in := Inbound{MessageID: "one", Sender: "sender", Peer: "dm", Text: "hello"}
	one, err := s.Accept(c.ID, c.Generation, in)
	if err != nil || one.RoleID != "mentor" {
		t.Fatal(one, err)
	}
	changed, err := s.SetRole(context.Background(), "alice", c.ID, "default")
	if err != nil || changed.RoleID != "default" || changed.Generation != c.Generation {
		t.Fatal(changed, err)
	}
	replay, err := s.Accept(c.ID, c.Generation, in)
	if err != nil || replay.ID != one.ID || replay.RoleID != "mentor" {
		t.Fatal(replay, err)
	}
	in.MessageID = "two"
	two, err := s.Accept(c.ID, c.Generation, in)
	if err != nil || two.RoleID != "default" || two.ConversationID != one.ConversationID {
		t.Fatal(two, err)
	}
	if _, err := s.Accept(c.ID, c.Generation, Inbound{MessageID: "new", Sender: "sender", Peer: "dm", Text: "/new"}); err != nil {
		t.Fatal(err)
	}
	in.MessageID = "three"
	three, err := s.Accept(c.ID, c.Generation, in)
	if err != nil || three.RoleID != "default" || three.ConversationID == one.ConversationID {
		t.Fatal(three, err)
	}
	// A creation retry neither restores the old role nor needs the role service to be online.
	s.runner = &roleRunner{lookup: func(context.Context, string) ([]Role, error) { return nil, errors.New("offline") }}
	repeated, err := s.Create(context.Background(), "alice", req)
	if err != nil || repeated.ID != c.ID || repeated.RoleID != "default" {
		t.Fatal(repeated, err)
	}
	req.RoleID = "default"
	if _, err := s.Create(context.Background(), "alice", req); err != ErrConflict {
		t.Fatal(err)
	}
}

func TestRoleValidationAndConcurrentDisconnect(t *testing.T) {
	s := testService(t, &fakeAdapter{kind: "feishu"})
	c := createConnected(t, s, "feishu", "work")
	for _, id := range []string{"", "other-user-role", "disabled-role"} {
		if _, err := s.SetRole(context.Background(), "alice", c.ID, id); !errors.Is(err, ErrInvalid) {
			t.Fatal(id, err)
		}
	}
	if _, err := s.Create(context.Background(), "alice", CreateRequest{Kind: "feishu", Name: "invalid", RequestID: "invalid", RoleID: "other-user-role"}); !errors.Is(err, ErrInvalid) {
		t.Fatal(err)
	}
	s.runner = &roleRunner{lookup: func(context.Context, string) ([]Role, error) {
		if _, err := s.Disconnect("alice", c.ID); err != nil {
			t.Fatal(err)
		}
		return []Role{{ID: "mentor"}}, nil
	}}
	if _, err := s.SetRole(context.Background(), "bob", c.ID, "mentor"); err != ErrNotFound {
		t.Fatal(err)
	}
	before, _ := s.Get("alice", c.ID)
	if before.DesiredState != "enabled" {
		t.Fatal("foreign owner triggered role lookup")
	}
	after, err := s.SetRole(context.Background(), "alice", c.ID, "mentor")
	if err != nil || after.RoleID != "mentor" || after.DesiredState != "disconnected" || after.Generation <= c.Generation {
		t.Fatal(after, err)
	}
	stored, err := s.Get("alice", c.ID)
	if err != nil || stored.RoleID != "mentor" {
		t.Fatal(stored, err)
	}
}

func TestHelpAndNewAreIdempotentControlMessages(t *testing.T) {
	s := testService(t, &fakeAdapter{kind: "weixin"})
	c := createConnected(t, s, "weixin", "personal")
	for _, command := range []string{"/help", "/new"} {
		in := Inbound{MessageID: command, Sender: "sender", Peer: "dm", Text: "  " + command + "\n"}
		turn, err := s.Accept(c.ID, c.Generation, in)
		if err != nil || turn.Status != "completed" || turn.ConversationID != "" {
			t.Fatal(turn, err)
		}
		again, err := s.Accept(c.ID, c.Generation, in)
		if err != nil || again.ID != turn.ID {
			t.Fatal(again, err)
		}
		var deliveries []models.ConnectDelivery
		s.db.Where("turn_id = ?", turn.ID).Find(&deliveries)
		if len(deliveries) != 1 || !strings.Contains(deliveries[0].Text, "长期记忆") {
			t.Fatal(deliveries)
		}
	}
	var count int64
	s.db.Model(&models.Conversation{}).Count(&count)
	if count != 0 {
		t.Fatal("control message created a conversation")
	}
	s.db.Model(&models.Message{}).Count(&count)
	if count != 0 {
		t.Fatal("control message leaked into model history")
	}
}
