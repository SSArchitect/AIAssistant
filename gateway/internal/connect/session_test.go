package connect

import (
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/models"
)

func TestConversationIdleRotation(t *testing.T) {
	for _, tc := range []struct {
		name   string
		gap    time.Duration
		status string
		rotate bool
	}{
		{"recent", 29 * time.Minute, "completed", false},
		{"threshold", 30 * time.Minute, "completed", true},
		{"long_gap", 24 * time.Hour, "completed", true},
		{"failed", time.Hour, "failed", true},
		{"cancelled", time.Hour, "cancelled", true},
		{"queued", time.Hour, "queued", false},
		{"running", time.Hour, "running", false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			s := testService(t, &fakeAdapter{kind: "feishu"})
			now := time.Date(2026, 9, 7, 0, 0, 0, 0, time.UTC)
			s.db.Config.NowFunc = func() time.Time { return now }
			c := createConnected(t, s, "feishu", "work")
			if err := s.db.Model(&c).Update("role_id", "mentor").Error; err != nil {
				t.Fatal(err)
			}
			old := accepted(t, s, c, "first")
			if err := s.db.Model(&old).Update("status", tc.status).Error; err != nil {
				t.Fatal(err)
			}
			now = now.Add(tc.gap)
			next := accepted(t, s, c, "next")
			if rotated := next.ConversationID != old.ConversationID; rotated != tc.rotate {
				t.Fatalf("rotated = %v, want %v", rotated, tc.rotate)
			}
			var source models.ConnectSource
			if err := s.db.First(&source, "id = ?", old.SourceID).Error; err != nil {
				t.Fatal(err)
			}
			wantEpoch := uint64(1)
			if tc.rotate {
				wantEpoch++
			}
			if source.Epoch != wantEpoch || source.ConversationID != next.ConversationID || next.RoleID != "mentor" {
				t.Fatalf("routing or role changed unexpectedly: %+v / %+v", source, next)
			}
			var count int64
			if err := s.db.Model(&models.Conversation{}).Count(&count).Error; err != nil || count != int64(wantEpoch) {
				t.Fatalf("history not retained: count %d, error %v", count, err)
			}
			if replay := accepted(t, s, c, "first"); replay.ID != old.ID || replay.ConversationID != old.ConversationID {
				t.Fatal("late replay moved to a new conversation")
			}
		})
	}
}

func TestConversationIdleIgnoresControlsAndRetries(t *testing.T) {
	for _, text := range []string{"/status", "/help", "/stop", "unsupported", "retry"} {
		t.Run(text, func(t *testing.T) {
			s := testService(t, &fakeAdapter{kind: "weixin"})
			now := time.Date(2026, 9, 7, 0, 0, 0, 0, time.UTC)
			s.db.Config.NowFunc = func() time.Time { return now }
			c := createConnected(t, s, "weixin", "personal")
			old := accepted(t, s, c, "first")
			if err := s.db.Model(&old).Update("status", "completed").Error; err != nil {
				t.Fatal(err)
			}
			now = now.Add(29 * time.Minute)
			if text == "retry" {
				accepted(t, s, c, "first")
			} else if _, err := s.Accept(c.ID, c.Generation, Inbound{MessageID: "control", Sender: "sender", Peer: "dm", Text: text, Unsupported: text == "unsupported"}); err != nil {
				t.Fatal(err)
			}
			var count int64
			if err := s.db.Model(&models.Conversation{}).Count(&count).Error; err != nil || count != 1 {
				t.Fatalf("control or retry created a conversation: %d / %v", count, err)
			}
			now = now.Add(time.Minute)
			if next := accepted(t, s, c, "next"); next.ConversationID == old.ConversationID {
				t.Fatal("control or retry extended the idle deadline")
			}
		})
	}
}

func TestConversationIdleRestoresTimestampAfterRestart(t *testing.T) {
	for _, legacy := range []bool{false, true} {
		t.Run(map[bool]string{false: "persisted", true: "legacy"}[legacy], func(t *testing.T) {
			s := testService(t, &fakeAdapter{kind: "feishu"})
			now := time.Date(2026, 9, 7, 0, 0, 0, 0, time.UTC)
			s.db.Config.NowFunc = func() time.Time { return now }
			c := createConnected(t, s, "feishu", "work")
			old := accepted(t, s, c, "first")
			if err := s.db.Model(&old).Update("status", "completed").Error; err != nil {
				t.Fatal(err)
			}
			if legacy {
				if err := s.db.Model(&models.ConnectSource{}).Where("id = ?", old.SourceID).UpdateColumn("last_message_at", nil).Error; err != nil {
					t.Fatal(err)
				}
			}
			s.Close()
			restarted, err := NewService(s.db, make([]byte, 32), nil, &fakeAdapter{kind: "feishu"})
			if err != nil {
				t.Fatal(err)
			}
			t.Cleanup(restarted.Close)
			now = now.Add(29 * time.Minute)
			if _, err := restarted.Accept(c.ID, c.Generation, Inbound{MessageID: "status", Sender: "sender", Peer: "dm", Text: "/status"}); err != nil {
				t.Fatal(err)
			}
			now = now.Add(time.Minute)
			if next := accepted(t, restarted, c, "next"); next.ConversationID == old.ConversationID {
				t.Fatal("restart or legacy control reset the idle deadline")
			}
		})
	}
}

func TestConversationIdleUsesLatestMessagePerSource(t *testing.T) {
	s := testService(t, &fakeAdapter{kind: "feishu"})
	now := time.Date(2026, 9, 7, 0, 0, 0, 0, time.UTC)
	s.db.Config.NowFunc = func() time.Time { return now }
	c := createConnected(t, s, "feishu", "work")
	accept := func(id, peer string) models.ConnectTurn {
		t.Helper()
		turn, err := s.Accept(c.ID, c.Generation, Inbound{MessageID: id, Sender: "sender", Peer: peer, Text: id})
		if err != nil {
			t.Fatal(err)
		}
		if err := s.db.Model(&turn).Update("status", "completed").Error; err != nil {
			t.Fatal(err)
		}
		return turn
	}
	one := accept("one", "dm")
	other := accept("other", "other-dm")
	now = now.Add(20 * time.Minute)
	if next := accept("two", "dm"); next.ConversationID != one.ConversationID {
		t.Fatal("recent follow-up did not reuse the conversation")
	}
	now = now.Add(20 * time.Minute)
	if next := accept("three", "dm"); next.ConversationID != one.ConversationID {
		t.Fatal("ordinary message did not refresh the deadline")
	}
	if next := accept("other-next", "other-dm"); next.ConversationID == other.ConversationID {
		t.Fatal("activity in another source extended the deadline")
	}
}
