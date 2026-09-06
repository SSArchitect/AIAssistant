package connect

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/models"
)

type controlledRunner struct {
	started chan models.ConnectTurn
	release chan struct{}
}

func (r *controlledRunner) Run(ctx context.Context, t models.ConnectTurn, emit func(bridge.RunEvent)) (*bridge.ChatResponse, error) {
	r.started <- t
	for i := 0; i < 200; i++ {
		emit(bridge.RunEvent{Type: "model.delta", Payload: map[string]any{"delta": "partial"}})
	}
	select {
	case <-ctx.Done():
		return nil, ctx.Err()
	case <-r.release:
		return &bridge.ChatResponse{Response: "完整答案", RunID: t.RunID}, nil
	}
}
func (*controlledRunner) Cancel(string) error { return nil }
func waitFor(t *testing.T, condition func() bool) {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for !condition() {
		if time.Now().After(deadline) {
			t.Fatal("condition timed out")
		}
		time.Sleep(time.Millisecond * 5)
	}
}
func accepted(t *testing.T, s *Service, c models.ConnectConnection, id string) models.ConnectTurn {
	t.Helper()
	turn, err := s.Accept(c.ID, c.Generation, Inbound{MessageID: id, Sender: "sender", Peer: "dm", Text: "request " + id, ContextToken: "private-context"})
	if err != nil {
		t.Fatal(err)
	}
	return turn
}
func TestWorkerSerializesSourceAndOnlyDeliversFinal(t *testing.T) {
	a := &fakeAdapter{kind: "feishu"}
	s := testService(t, a)
	c := createConnected(t, s, "feishu", "work")
	r := &controlledRunner{started: make(chan models.ConnectTurn, 4), release: make(chan struct{})}
	s.runner = r
	first, second := accepted(t, s, c, "1"), accepted(t, s, c, "2")
	s.dispatch()
	running := <-r.started
	if running.ID != first.ID || running.UserMessageID == 0 {
		t.Fatal(running)
	}
	s.dispatch()
	select {
	case <-r.started:
		t.Fatal("same source executed concurrently")
	default:
	}
	var count int64
	s.db.Model(&models.ConnectDelivery{}).Count(&count)
	if count != 0 {
		t.Fatal("stream deltas generated external messages")
	}
	s.db.Model(&models.Message{}).Count(&count)
	if count != 1 {
		t.Fatal("future queued messages leaked into history")
	}
	close(r.release)
	waitFor(t, func() bool {
		var got models.ConnectTurn
		s.db.First(&got, "id = ?", first.ID)
		return got.Status == "completed"
	})
	waitFor(t, func() bool { s.mu.Lock(); defer s.mu.Unlock(); return len(s.running) == 0 })
	s.dispatch()
	running = <-r.started
	if running.ID != second.ID || running.UserMessageID <= 2 {
		t.Fatal("second input not sequenced after first answer", running)
	}
	waitFor(t, func() bool {
		var got models.ConnectTurn
		s.db.First(&got, "id = ?", second.ID)
		return got.Status == "completed"
	})
	var deliveries []models.ConnectDelivery
	s.db.Find(&deliveries)
	if len(deliveries) != 2 || deliveries[0].Text != "完整答案" {
		t.Fatal(deliveries)
	}
}

func TestUnknownDeliveryNeedsExplicitRetryWithoutRerunningAgent(t *testing.T) {
	sends := 0
	a := &fakeAdapter{kind: "feishu", send: func(_ context.Context, _ Config, out Outgoing) (string, error) {
		sends++
		if out.ContextToken != "private-context" {
			t.Fatal("wrong context token")
		}
		if sends == 1 {
			return "", &SendError{Message: "timeout", Unknown: true}
		}
		return "receipt", nil
	}}
	s := testService(t, a)
	c := createConnected(t, s, "feishu", "work")
	turn := accepted(t, s, c, "1")
	s.db.Model(&turn).Update("status", "running")
	if e := s.finish(turn, &bridge.ChatResponse{Response: "answer"}, nil); e != nil {
		t.Fatal(e)
	}
	s.deliver()
	s.deliver()
	var d models.ConnectDelivery
	s.db.First(&d, "turn_id = ?", turn.ID)
	if sends != 1 || d.Status != "unknown" {
		t.Fatal(sends, d)
	}
	if _, e := s.RetryDelivery("bob", c.ID, d.ID); e != ErrNotFound {
		t.Fatal(e)
	}
	if _, e := s.RetryDelivery("alice", c.ID, d.ID); e != nil {
		t.Fatal(e)
	}
	s.deliver()
	s.db.First(&d, "id = ?", d.ID)
	if sends != 2 || d.Status != "sent" {
		t.Fatal(sends, d)
	}
	var count int64
	s.db.Model(&models.ConnectTurn{}).Count(&count)
	if count != 1 {
		t.Fatal("delivery retry executed another turn")
	}
}

func TestNewTopicAcknowledgementDeliveredOnce(t *testing.T) {
	for _, kind := range []string{"weixin", "feishu"} {
		t.Run(kind, func(t *testing.T) {
			var sent []Outgoing
			a := &fakeAdapter{kind: kind, send: func(_ context.Context, _ Config, out Outgoing) (string, error) {
				sent = append(sent, out)
				return "receipt", nil
			}}
			s := testService(t, a)
			c := createConnected(t, s, kind, "personal")
			old := accepted(t, s, c, "old-topic")
			in := Inbound{MessageID: "new-command", Sender: "sender", Peer: "dm", Text: "/new", ContextToken: "new-context"}
			command, err := s.Accept(c.ID, c.Generation, in)
			if err != nil || command.Status != "completed" {
				t.Fatal(command, err)
			}
			// The acknowledgement is deliverable before another ordinary message or model run.
			s.deliver()
			if len(sent) != 1 || !strings.HasPrefix(sent[0].Text, "已为你开启新话题。") || !strings.Contains(sent[0].Text, "人设和长期记忆已保留") || sent[0].Peer != "dm" || sent[0].ContextToken != "new-context" {
				t.Fatal(sent)
			}
			replay, err := s.Accept(c.ID, c.Generation, in)
			if err != nil || replay.ID != command.ID {
				t.Fatal(replay, err)
			}
			s.deliver()
			if len(sent) != 1 {
				t.Fatal("platform retry duplicated the acknowledgement", sent)
			}
			next := accepted(t, s, c, "new-topic")
			if next.ConversationID == old.ConversationID {
				t.Fatal("acknowledgement did not correspond to a new topic")
			}
		})
	}
}

func TestFailedNoticeDoesNotBlockFinalAndFinishIsIdempotent(t *testing.T) {
	s := testService(t, &fakeAdapter{kind: "feishu"})
	c := createConnected(t, s, "feishu", "work")
	turn := accepted(t, s, c, "1")
	s.db.Model(&turn).Update("status", "running")
	s.enqueueNotice(turn, "approval", "needs approval")
	s.db.Model(&models.ConnectDelivery{}).Where("part = -1").Update("status", "failed")
	for i := 0; i < 2; i++ {
		if e := s.finish(turn, &bridge.ChatResponse{Response: "answer"}, nil); e != nil {
			t.Fatal(e)
		}
	}
	s.deliver()
	var d models.ConnectDelivery
	s.db.First(&d, "part = 0")
	if d.Status != "sent" {
		t.Fatal("notice blocked final", d)
	}
	var count int64
	s.db.Model(&models.Message{}).Count(&count)
	if count != 1 {
		t.Fatal("duplicate assistant history")
	}
}

func TestDisconnectFencesLateResultAndPendingDelivery(t *testing.T) {
	sends := 0
	a := &fakeAdapter{kind: "feishu", send: func(context.Context, Config, Outgoing) (string, error) { sends++; return "", nil }}
	s := testService(t, a)
	c := createConnected(t, s, "feishu", "work")
	turn := accepted(t, s, c, "1")
	s.db.Model(&turn).Update("status", "running")
	s.enqueueNotice(turn, "approval", "notice")
	s.Disconnect("alice", c.ID)
	if e := s.finish(turn, &bridge.ChatResponse{Response: "late"}, nil); e != nil {
		t.Fatal(e)
	}
	s.deliver()
	if sends != 0 {
		t.Fatal("disconnected integration sent a message")
	}
	var count int64
	s.db.Model(&models.Message{}).Count(&count)
	if count != 0 {
		t.Fatal("late result changed history")
	}
}

func TestUnsupportedInputAndFailuresProduceUsefulControlReplies(t *testing.T) {
	s := testService(t, &fakeAdapter{kind: "feishu"})
	c := createConnected(t, s, "feishu", "work")
	turn, e := s.Accept(c.ID, c.Generation, Inbound{MessageID: "image", Sender: "sender", Peer: "dm", Unsupported: true})
	if e != nil || turn.Status != "completed" || turn.ConversationID != "" {
		t.Fatal(turn, e)
	}
	turn = accepted(t, s, c, "text")
	s.db.Model(&turn).Update("status", "running")
	if e := s.finish(turn, nil, errors.New("internal credentials must not appear")); e != nil {
		t.Fatal(e)
	}
	var msg models.Message
	s.db.First(&msg, "run_id = ?", turn.RunID)
	if msg.ErrorType != "connect_interrupted" || msg.Content == "" {
		t.Fatal("failed run left history spinning", msg)
	}
}
