package bridge

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestConnectRunAdmissionLookupAndCancellation(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "POST" {
			var req ChatRequest
			json.NewDecoder(r.Body).Decode(&req)
			if req.RunID != "run" || req.UserID != "alice" || req.AgentID != "super_chat" {
				t.Error(req)
			}
		} else if r.URL.Query().Get("user_id") != "alice" || r.URL.Path != "/agent/connect/runs/run" {
			t.Error(r.URL)
		}
		w.Write([]byte(`{"run_id":"run","status":"completed","response":{"response":"完整答案","citations":[{"title":"source","url":"https://example.com"}]}}`))
	}))
	defer server.Close()
	client := NewAgentClient(server.URL, time.Second)
	for _, req := range []*ChatRequest{{RunID: "run", UserID: "alice", AgentID: "super_chat"}, nil} {
		result, e := client.ConnectRun(context.Background(), req, "run", "alice")
		if e != nil || result.Status != "completed" || len(result.Response.Citations) != 1 {
			t.Fatal(result, e)
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, e := client.ConnectRun(ctx, nil, "run", "alice"); e == nil {
		t.Fatal("cancelled request succeeded")
	}
}
func TestConnectRunDoesNotLeakAgentErrorBody(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(409); w.Write([]byte("secret-token")) }))
	defer server.Close()
	_, e := NewAgentClient(server.URL, time.Second).ConnectRun(context.Background(), nil, "run", "alice")
	if e == nil || e.Error() != "Connect runtime status 409" {
		t.Fatal(e)
	}
}
