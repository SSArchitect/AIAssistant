package handlers

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/gin-gonic/gin"
)

func TestRunPagesDefaultToTenAndForwardCursorAndOwner(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("limit") != "10" || r.URL.Query().Get("user_id") != "alice" || r.URL.Query().Get("cursor") != "next" {
			t.Errorf("unexpected query: %s", r.URL.RawQuery)
		}
		json.NewEncoder(w).Encode(bridge.RunListResponse{Runs: []bridge.RunRecord{{RunID: "older"}}, HasMore: true, NextCursor: "another"})
	}))
	defer upstream.Close()
	router := gin.New()
	router.GET("/api/runs", NewChatHandler(bridge.NewAgentClient(upstream.URL, time.Second)).ListRuns)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, httptest.NewRequest("GET", "/api/runs?user_id=alice&cursor=next", nil))
	var page bridge.RunListResponse
	if err := json.Unmarshal(response.Body.Bytes(), &page); err != nil {
		t.Fatal(err)
	}
	if response.Code != 200 || !page.HasMore || page.NextCursor != "another" || len(page.Runs) != 1 {
		t.Fatalf("unexpected page: %d %+v", response.Code, page)
	}
}

func TestRunPagesRejectInvalidLimitAndCursor(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusBadRequest) }))
	defer upstream.Close()
	router := gin.New()
	router.GET("/api/runs", NewChatHandler(bridge.NewAgentClient(upstream.URL, time.Second)).ListRuns)
	for _, query := range []string{"limit=bad", "cursor=bad"} {
		response := httptest.NewRecorder()
		router.ServeHTTP(response, httptest.NewRequest("GET", "/api/runs?"+query, nil))
		if response.Code != 400 {
			t.Fatalf("%s: status %d", query, response.Code)
		}
	}
}
