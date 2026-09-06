package handlers

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"path/filepath"
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
)

func TestConversationCursorPagination(t *testing.T) {
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "page.db")); err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC().Truncate(time.Second)
	rows := []models.Conversation{
		{ID: "d", UserID: "a", Title: "Latest", UpdatedAt: now},
		{ID: "c", UserID: "a", Title: "Same time", UpdatedAt: now},
		{ID: "b", UserID: "a", Title: "Old 100%_ complete", UpdatedAt: now.Add(-time.Hour)},
		{ID: "a", UserID: "a", Title: "Older", UpdatedAt: now.Add(-2 * time.Hour)},
		{ID: "private", UserID: "b", Title: "Old 100%_ complete", UpdatedAt: now.Add(-time.Hour)},
	}
	if err := database.DB.Create(&rows).Error; err != nil {
		t.Fatal(err)
	}
	router := gin.New()
	router.GET("/api/conversations", NewConversationHandler().List)
	type response struct {
		Conversations []models.Conversation `json:"conversations"`
		HasMore       bool                  `json:"has_more"`
		Next          string                `json:"next_cursor"`
		Total         int                   `json:"total"`
	}
	fetch := func(query string) response {
		t.Helper()
		req := httptest.NewRequest(http.MethodGet, "/api/conversations?"+query, nil)
		req.Header.Set("X-User-ID", "a")
		recorder := httptest.NewRecorder()
		router.ServeHTTP(recorder, req)
		if recorder.Code != 200 {
			t.Fatalf("%d %s", recorder.Code, recorder.Body.String())
		}
		var value response
		if err := json.Unmarshal(recorder.Body.Bytes(), &value); err != nil {
			t.Fatal(err)
		}
		return value
	}
	first := fetch("limit=1")
	if len(first.Conversations) != 1 || first.Conversations[0].ID != "d" || !first.HasMore || first.Total != 4 {
		t.Fatalf("first: %+v", first)
	}
	// Insert/delete ahead of the cursor: the next page must still contain c.
	database.DB.Create(&models.Conversation{ID: "new", UserID: "a", Title: "New", UpdatedAt: now.Add(time.Hour)})
	database.DB.Delete(&models.Conversation{}, "id = ?", "d")
	second := fetch("limit=1&cursor=" + url.QueryEscape(first.Next))
	if len(second.Conversations) != 1 || second.Conversations[0].ID != "c" {
		t.Fatalf("second: %+v", second)
	}
	last := fetch("limit=20&cursor=" + url.QueryEscape(second.Next))
	if len(last.Conversations) != 2 || last.Conversations[0].ID != "b" || last.Conversations[1].ID != "a" || last.HasMore || last.Next != "" {
		t.Fatalf("last: %+v", last)
	}
	search := fetch("limit=20&q=" + url.QueryEscape("100%_"))
	if len(search.Conversations) != 1 || search.Conversations[0].ID != "b" || search.Total != 1 {
		t.Fatalf("search: %+v", search)
	}
	empty := fetch("limit=20&q=doesnotexist")
	if empty.Conversations == nil || len(empty.Conversations) != 0 || empty.Total != 0 || empty.HasMore {
		t.Fatalf("empty: %+v", empty)
	}
	for _, query := range []string{"limit=0", "limit=101", "limit=abc", "limit=-1", "limit=1&cursor=bad", "limit=1&cursor=e30"} {
		req := httptest.NewRequest(http.MethodGet, "/api/conversations?"+query, nil)
		req.Header.Set("X-User-ID", "a")
		result := httptest.NewRecorder()
		router.ServeHTTP(result, req)
		if result.Code != http.StatusBadRequest {
			t.Errorf("%s: want 400, got %d", query, result.Code)
		}
	}
}
