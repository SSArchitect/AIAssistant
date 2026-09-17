package bridge

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestCreationBridgeContract(t *testing.T) {
	var got CreationNodeRequest
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/agent/creation/node" || r.Method != "POST" {
			t.Errorf("wrong request: %s %s", r.Method, r.URL)
		}
		if err := json.NewDecoder(r.Body).Decode(&got); err != nil {
			t.Error(err)
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"content":"aW1hZ2U=","mime_type":"image/png","provider_task_id":"job"}`))
	}))
	defer server.Close()
	client := NewAgentClient(server.URL, time.Second)
	result, err := client.CreateMedia(context.Background(), CreationNodeRequest{Kind: "video", Prompt: "test", InputImages: []string{"data:image/png;base64,YQ=="}, IdempotencyKey: "run-node"})
	if err != nil || result.ProviderTaskID != "job" || got.IdempotencyKey != "run-node" || len(got.InputImages) != 1 {
		t.Fatalf("bad boundary: %+v %+v %v", got, result, err)
	}
}
func TestCreationBridgeFailureAndCancellation(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(502); w.Write([]byte("secret")) }))
	defer server.Close()
	client := NewAgentClient(server.URL, time.Second)
	if _, err := client.CreateMedia(context.Background(), CreationNodeRequest{}); err == nil || err.Error() == "secret" {
		t.Fatal("expected sanitized failure")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := client.CreateMedia(ctx, CreationNodeRequest{}); err == nil {
		t.Fatal("expected cancellation")
	}
}

func TestCreationPlanningBridgePassesOwnerContextAndUsesBoundedResponse(t *testing.T) {
	var got CreationPlanningRequest
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/agent/creation/plan" || r.Method != "POST" {
			t.Error("wrong planning route")
		}
		if err := json.NewDecoder(r.Body).Decode(&got); err != nil {
			t.Error(err)
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"reply":"请审阅","plan":{"title":"创作","summary":"方案","nodes":[],"questions":[]},"model_used":"model","tokens_used":{"input_tokens":2}}`))
	}))
	defer server.Close()
	client := NewAgentClient(server.URL, time.Second)
	result, err := client.PlanCreation(context.Background(), CreationPlanningRequest{ProjectID: "project", UserID: "alice", Messages: []CreativeMessage{{Role: "user", Content: "短片"}}, NodeContext: map[string]map[string]interface{}{"visual": {"selected_asset_id": "chosen"}}})
	if err != nil || result.Reply != "请审阅" || result.TokensUsed["input_tokens"] != 2 || got.UserID != "alice" || got.NodeContext["visual"]["selected_asset_id"] != "chosen" {
		t.Fatalf("bad bridge: %+v %+v %v", result, got, err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := client.PlanCreation(ctx, CreationPlanningRequest{}); err == nil {
		t.Fatal("cancelled planner continued")
	}
}

func TestCreationPlanningStreamDeliversProgressBeforeResult(t *testing.T) {
	progressSeen := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/agent/creation/plan/stream" {
			t.Error("wrong stream route")
		}
		w.Header().Set("Content-Type", "application/x-ndjson")
		w.Write([]byte(`{"type":"progress","stage":"thinking","message":"正在分析"}` + "\n"))
		w.(http.Flusher).Flush()
		select {
		case <-progressSeen:
		case <-r.Context().Done():
			return
		}
		w.Write([]byte(`{"type":"result","result":{"reply":"审阅","plan":{"title":"方案"}}}` + "\n"))
	}))
	defer server.Close()
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	result, err := NewAgentClient(server.URL, time.Second).PlanCreationWithProgress(ctx, CreationPlanningRequest{}, func(p CreationPlanningProgress) {
		if p.Stage != "thinking" {
			t.Error(p)
		}
		close(progressSeen)
	})
	if err != nil || result.Reply != "审阅" {
		t.Fatalf("%+v %v", result, err)
	}
}

func TestCreationPlanningStreamRejectsTruncationAndSanitizesErrors(t *testing.T) {
	for _, body := range []string{`{"type":"progress","stage":"model"}`, `{"type":"error","message":"SECRET"}`, `{"type":"result"}`} {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.Write([]byte(body)) }))
		result, err := NewAgentClient(server.URL, time.Second).PlanCreationWithProgress(context.Background(), CreationPlanningRequest{}, nil)
		server.Close()
		if result != nil || err == nil || strings.Contains(err.Error(), "SECRET") {
			t.Fatalf("unsafe result %+v %v", result, err)
		}
	}
}

func TestCreationPlanningStreamKeepsActionableSafeErrorCode(t *testing.T) {
	for code, expected := range map[string]string{"model_image_unsupported": "不支持图片", "provider_auth_failed": "鉴权", "provider_rate_limited": "额度", "provider_unavailable": "连接", "invalid_plan": "格式校验", "planning_output_truncated": "未完整返回", "unknown": "暂时无法"} {
		t.Run(code, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				json.NewEncoder(w).Encode(map[string]string{"type": "error", "code": code, "message": "SECRET-KEY"})
			}))
			defer server.Close()
			_, err := NewAgentClient(server.URL, time.Second).PlanCreationWithProgress(context.Background(), CreationPlanningRequest{}, nil)
			if err == nil || !strings.Contains(err.Error(), expected) || strings.Contains(err.Error(), "SECRET") {
				t.Fatalf("unsafe or unhelpful error: %v", err)
			}
		})
	}
}
