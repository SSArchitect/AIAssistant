package handlers

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
)

func TestCreationConfigSyncRespectsStopDuringAgentOutage(t *testing.T) {
	setupDriveTest(t)
	entered := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/agent/config" {
			t.Error("model operation ran after stop")
			return
		}
		io.Copy(io.Discard, r.Body)
		close(entered)
		<-r.Context().Done()
	}))
	defer server.Close()
	h := NewCreationHandler(bridge.NewAgentClient(server.URL, time.Second))
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() {
		_, err := h.generator.(creationReviewer).ReviewCreation(ctx, bridge.CreationReviewRequest{})
		done <- err
	}()
	<-entered
	cancel()
	select {
	case err := <-done:
		if err == nil {
			t.Fatal("stopped request succeeded")
		}
	case <-time.After(time.Second):
		t.Fatal("configuration sync ignored cancellation")
	}
}

func TestCreationRestoresPersistedConfigBeforeEveryAgentOperation(t *testing.T) {
	for _, failSync := range []bool{false, true} {
		t.Run(map[bool]string{false: "agent restart", true: "sync unavailable"}[failSync], func(t *testing.T) {
			setupDriveTest(t)
			if err := database.DB.Save(&models.Setting{Key: "llm.doubao.api_key", Value: "test-persisted-key"}).Error; err != nil {
				t.Fatal(err)
			}
			configured, syncs, operations := false, 0, 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path == "/agent/config" {
					syncs++
					if failSync {
						w.WriteHeader(503)
						w.Write([]byte("SECRET-UPSTREAM"))
						return
					}
					var body struct {
						Settings map[string]string `json:"settings"`
					}
					if json.NewDecoder(r.Body).Decode(&body) != nil || body.Settings["llm.doubao.api_key"] != "test-persisted-key" {
						t.Error("persisted settings missing")
					}
					configured = true
					w.Write([]byte(`{"status":"ok"}`))
					return
				}
				operations++
				if !configured {
					t.Error("creation called an unconfigured/restarted Agent")
				}
				configured = false // simulate an independent Agent restart between steps
				switch r.URL.Path {
				case "/agent/creation/plan/stream":
					w.Write([]byte(`{"type":"result","result":{"reply":"ready"}}` + "\n"))
				default:
					w.Write([]byte(`{}`))
				}
			}))
			defer server.Close()
			h := NewCreationHandler(bridge.NewAgentClient(server.URL, time.Second))
			ctx := context.Background()
			calls := []func() error{
				func() error {
					_, err := h.generator.(creationPlanner).PlanCreation(ctx, bridge.CreationPlanningRequest{})
					return err
				},
				func() error {
					_, err := h.generator.(creationProgressPlanner).PlanCreationWithProgress(ctx, bridge.CreationPlanningRequest{}, nil)
					return err
				},
				func() error {
					_, err := h.generator.(creationReviewer).ReviewCreation(ctx, bridge.CreationReviewRequest{})
					return err
				},
				func() error { _, err := h.generator.CreateMedia(ctx, bridge.CreationNodeRequest{}); return err },
			}
			for _, call := range calls {
				err := call()
				if failSync {
					if err == nil || !strings.Contains(err.Error(), "配置同步") || strings.Contains(err.Error(), "SECRET") {
						t.Fatal("unsafe/unhelpful sync error", err)
					}
				} else if err != nil {
					t.Fatal(err)
				}
			}
			if syncs != 4 || operations != map[bool]int{false: 4, true: 0}[failSync] {
				t.Fatalf("syncs=%d operations=%d", syncs, operations)
			}
		})
	}
}
