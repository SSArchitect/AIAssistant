package connect

import (
	"context"
	"encoding/json"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/models"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

type fakeAdapter struct {
	kind  string
	check func(context.Context, Config) ([]Diagnostic, error)
	send  func(context.Context, Config, Outgoing) (string, error)
}

func (a *fakeAdapter) Descriptor() Descriptor {
	return Descriptor{ID: a.kind, Name: a.kind, Auth: "credentials", Fields: []Field{{Key: "app_id"}, {Key: "sender"}}, Input: []string{"text"}, Output: []string{"text"}}
}
func (a *fakeAdapter) Authenticate(_ context.Context, c Config) (AuthResult, error) {
	return AuthResult{Config: c, RemoteID: c["app_id"], Sender: c["sender"], Ready: true}, nil
}
func (a *fakeAdapter) Check(ctx context.Context, c Config) ([]Diagnostic, error) {
	if a.check != nil {
		return a.check(ctx, c)
	}
	return []Diagnostic{{Name: "credentials", Status: "passed"}}, nil
}
func (a *fakeAdapter) Listen(ctx context.Context, c Config, emit func(Inbound) error, healthy func()) error {
	healthy()
	<-ctx.Done()
	return ctx.Err()
}
func (a *fakeAdapter) Send(ctx context.Context, cfg Config, out Outgoing) (string, error) {
	if a.send != nil {
		return a.send(ctx, cfg, out)
	}
	return "remote", nil
}

func testService(t *testing.T, adapters ...Adapter) *Service {
	t.Helper()
	db, err := gorm.Open(sqlite.Open(filepath.Join(t.TempDir(), "connect.db")), &gorm.Config{})
	if err != nil {
		t.Fatal(err)
	}
	if err = db.AutoMigrate(&models.Conversation{}, &models.Message{}); err != nil {
		t.Fatal(err)
	}
	s, err := NewService(db, make([]byte, 32), nil, adapters...)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(s.Close)
	return s
}
func createConnected(t *testing.T, s *Service, kind, name string) models.ConnectConnection {
	t.Helper()
	c, err := s.Create(context.Background(), "alice", CreateRequest{Kind: kind, Name: name, RequestID: name, Credentials: Config{"app_id": name, "sender": "sender"}})
	if err != nil {
		t.Fatal(err)
	}
	return c
}
func TestSourceIsolationAndInboundRetry(t *testing.T) {
	s := testService(t, &fakeAdapter{kind: "feishu"}, &fakeAdapter{kind: "weixin"})
	a := createConnected(t, s, "feishu", "work")
	b := createConnected(t, s, "weixin", "personal")
	input := Inbound{MessageID: "same-id", Sender: "sender", Peer: "dm", Text: "same text"}
	one, err := s.Accept(a.ID, a.Generation, input)
	if err != nil {
		t.Fatal(err)
	}
	replay, err := s.Accept(a.ID, a.Generation, input)
	if err != nil {
		t.Fatal(err)
	}
	if one.ID != replay.ID {
		t.Fatal("retry created another turn")
	}
	two, err := s.Accept(b.ID, b.Generation, input)
	if err != nil {
		t.Fatal(err)
	}
	if one.ID == two.ID || one.ConversationID == two.ConversationID {
		t.Fatal("sources merged")
	}
	input.MessageID = "new-id"
	three, err := s.Accept(a.ID, a.Generation, input)
	if err != nil {
		t.Fatal(err)
	}
	if three.ID == one.ID || three.ConversationID != one.ConversationID {
		t.Fatal("new message must create a new turn in the same source conversation")
	}
	input.MessageID = "new-command"
	input.Text = "/new"
	if _, err = s.Accept(a.ID, a.Generation, input); err != nil {
		t.Fatal(err)
	}
	input.MessageID = "same-id"
	input.Text = "same text"
	old, err := s.Accept(a.ID, a.Generation, input)
	if err != nil || old.ID != one.ID {
		t.Fatal("old retry moved to new conversation", err)
	}
	input.MessageID = "after-new"
	next, err := s.Accept(a.ID, a.Generation, input)
	if err != nil || next.ConversationID == one.ConversationID {
		t.Fatal("/new did not isolate epoch", err)
	}
	input.Text = "changed payload"
	if _, err = s.Accept(a.ID, a.Generation, input); err != ErrConflict {
		t.Fatal("expected idempotency conflict", err)
	}
}
func TestDisconnectFencesWorkAndRetainsHistory(t *testing.T) {
	s := testService(t, &fakeAdapter{kind: "feishu"})
	c := createConnected(t, s, "feishu", "work")
	turn, err := s.Accept(c.ID, c.Generation, Inbound{MessageID: "1", Sender: "sender", Peer: "dm", Text: "hello"})
	if err != nil {
		t.Fatal(err)
	}
	if _, err = s.Disconnect("bob", c.ID); err != ErrNotFound {
		t.Fatal("other account can disconnect", err)
	}
	stopped, err := s.Disconnect("alice", c.ID)
	if err != nil {
		t.Fatal(err)
	}
	again, err := s.Disconnect("alice", c.ID)
	if err != nil || again.Generation != stopped.Generation {
		t.Fatal("disconnect not idempotent", err)
	}
	if _, err = s.Accept(c.ID, c.Generation, Inbound{MessageID: "2", Sender: "sender", Peer: "dm", Text: "hello"}); err != ErrDisconnected {
		t.Fatal(err)
	}
	var stored models.ConnectTurn
	s.db.First(&stored, "id = ?", turn.ID)
	if stored.Status != "cancelled" {
		t.Fatal(stored.Status)
	}
	var count int64
	s.db.Model(&models.Conversation{}).Count(&count)
	if count != 1 {
		t.Fatal("disconnect deleted history")
	}
	if _, err = s.Check(context.Background(), "alice", c.ID); err != nil {
		t.Fatal(err)
	}
	got, _ := s.Get("alice", c.ID)
	if got.DesiredState != "disconnected" {
		t.Fatal("check reconnected disabled integration")
	}
}
func TestLateCheckCannotUndoDisconnect(t *testing.T) {
	a := &fakeAdapter{kind: "feishu"}
	s := testService(t, a)
	c := createConnected(t, s, "feishu", "work")
	a.check = func(context.Context, Config) ([]Diagnostic, error) {
		_, err := s.Disconnect("alice", c.ID)
		return []Diagnostic{{Name: "credentials", Status: "passed"}}, err
	}
	if _, err := s.Check(context.Background(), "alice", c.ID); err != nil {
		t.Fatal(err)
	}
	got, _ := s.Get("alice", c.ID)
	if got.Status != "disconnected" {
		t.Fatal("late check changed disconnected state")
	}
}
func TestConnectionsHideSecretsAndRequireBoundSender(t *testing.T) {
	s := testService(t, &fakeAdapter{kind: "feishu"})
	c := createConnected(t, s, "feishu", "work")
	if strings.Contains(c.Secret, "sender") {
		t.Fatal("plaintext credentials")
	}
	if _, err := s.Accept(c.ID, c.Generation, Inbound{MessageID: "1", Sender: "stranger", Peer: "dm", Text: "hello"}); err != ErrForbidden {
		t.Fatal("unbound sender accepted", err)
	}
	if _, err := s.Create(context.Background(), "alice", CreateRequest{Kind: "slack", RequestID: "unsupported", Name: "Slack"}); err != ErrUnsupported {
		t.Fatal(err)
	}
	if _, err := s.Get("bob", c.ID); err != ErrNotFound {
		t.Fatal(err)
	}
}

func TestCredentialFilteringPairingAndCreateIdempotency(t *testing.T) {
	s := testService(t, &fakeAdapter{kind: "feishu"})
	req := CreateRequest{Kind: "feishu", Name: "work", RequestID: "create", Credentials: Config{"app_id": "app", "base_url": "https://evil.invalid", "bot_token": "forged"}}
	c, err := s.Create(context.Background(), "alice", req)
	if err != nil {
		t.Fatal(err)
	}
	cfg, _ := s.open(c.ID, c.Secret)
	if cfg["base_url"] != "" || cfg["bot_token"] != "" {
		t.Fatal("client supplied transport secrets accepted")
	}
	duplicate, err := s.Create(context.Background(), "alice", req)
	if err != nil || duplicate.ID != c.ID {
		t.Fatal("create not idempotent", err)
	}
	req.Name = "other"
	if _, err := s.Create(context.Background(), "alice", req); err != ErrConflict {
		t.Fatal(err)
	}
	input := Inbound{MessageID: "pair", Sender: "real-user", Peer: "dm", Text: "/connect wrong"}
	if _, err := s.Accept(c.ID, c.Generation, input); err != ErrForbidden {
		t.Fatal("bad pairing accepted", err)
	}
	input.Text = "/connect " + cfg["pairing_code"]
	if turn, err := s.Accept(c.ID, c.Generation, input); err != nil || turn.ID != "" {
		t.Fatal("pairing should not invoke model", err)
	}
	c, _ = s.Get("alice", c.ID)
	if c.Sender != "real-user" || c.Status != "connected" || c.NextAction != "" {
		t.Fatal(c)
	}
	raw, _ := json.Marshal(c)
	if strings.Contains(string(raw), cfg["pairing_code"]) || strings.Contains(string(raw), "forged") {
		t.Fatal("secrets leaked")
	}
}

func TestReconnectFencesOldGenerationAndRetainsIdentity(t *testing.T) {
	s := testService(t, &fakeAdapter{kind: "feishu"})
	c := createConnected(t, s, "feishu", "work")
	turn, _ := s.Accept(c.ID, c.Generation, Inbound{MessageID: "1", Sender: "sender", Peer: "dm", Text: "hello"})
	next, err := s.Reconnect(context.Background(), "alice", c.ID, Config{})
	if err != nil || next.Generation <= c.Generation || next.Status != "connected" {
		t.Fatal(next, err)
	}
	var old models.ConnectTurn
	s.db.First(&old, "id = ?", turn.ID)
	if old.Status != "cancelled" {
		t.Fatal("reconnect left old run active")
	}
	if _, err := s.Accept(c.ID, c.Generation, Inbound{MessageID: "late", Sender: "sender", Peer: "dm", Text: "late"}); err != ErrDisconnected {
		t.Fatal(err)
	}
	bad, err := s.Reconnect(context.Background(), "alice", c.ID, Config{"app_id": "another-app"})
	if err != nil || bad.Status != "error" || bad.RemoteID != "work" {
		t.Fatal("identity change inherited history", bad, err)
	}
}

func TestConcurrentChecksAreCoalesced(t *testing.T) {
	entered, release := make(chan struct{}), make(chan struct{})
	var calls atomic.Int32
	a := &fakeAdapter{kind: "feishu", check: func(context.Context, Config) ([]Diagnostic, error) {
		calls.Add(1)
		close(entered)
		<-release
		return []Diagnostic{{Name: "credentials", Status: "passed"}}, nil
	}}
	s := testService(t, a)
	c := createConnected(t, s, "feishu", "work")
	results := make(chan models.ConnectCheck, 2)
	go func() { r, _ := s.Check(context.Background(), "alice", c.ID); results <- r }()
	<-entered
	go func() { r, _ := s.Check(context.Background(), "alice", c.ID); results <- r }()
	close(release)
	one, two := <-results, <-results
	if one.ID == "" || one.ID != two.ID || calls.Load() != 1 {
		t.Fatal(one, two, calls.Load())
	}
}

func TestExpiredPairingIsRejected(t *testing.T) {
	s := testService(t, &fakeAdapter{kind: "feishu"})
	c, _ := s.Create(context.Background(), "alice", CreateRequest{Kind: "feishu", Name: "work", RequestID: "expired", Credentials: Config{"app_id": "app"}})
	cfg, _ := s.open(c.ID, c.Secret)
	cfg["pairing_expires"] = time.Now().Add(-time.Second).Format(time.RFC3339)
	secret, _ := s.seal(c.ID, cfg)
	s.db.Model(&c).Update("secret", secret)
	if _, e := s.Accept(c.ID, c.Generation, Inbound{MessageID: "pair", Sender: "sender", Peer: "dm", Text: "/connect " + cfg["pairing_code"]}); e != ErrForbidden {
		t.Fatal(e)
	}
}

func TestDeletedHistoryStartsFreshWithoutRebindingOldRetry(t *testing.T) {
	s := testService(t, &fakeAdapter{kind: "feishu"})
	c := createConnected(t, s, "feishu", "work")
	input := Inbound{MessageID: "old", Sender: "sender", Peer: "dm", Text: "hello"}
	old, e := s.Accept(c.ID, c.Generation, input)
	if e != nil {
		t.Fatal(e)
	}
	s.db.Delete(&models.Conversation{}, "id = ?", old.ConversationID)
	input.MessageID = "new"
	next, e := s.Accept(c.ID, c.Generation, input)
	if e != nil || next.ConversationID == old.ConversationID || next.ConversationID == "" {
		t.Fatal(next, e)
	}
	input.MessageID = "old"
	retry, e := s.Accept(c.ID, c.Generation, input)
	if e != nil || retry.ID != old.ID || retry.ConversationID != old.ConversationID {
		t.Fatal("old retry inherited fresh history", retry, e)
	}
}
