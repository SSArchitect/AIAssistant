package handlers

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/aan/agent-assistant-gateway/internal/connect"
	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/middleware"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
)

func TestConnectMobileCORSAndSessionAuthentication(t *testing.T) {
	setupConnectHandlerDB(t)
	service, err := connect.NewService(database.DB, make([]byte, 32), nil)
	if err != nil {
		t.Fatal(err)
	}
	defer service.Close()
	router := gin.New()
	router.Use(middleware.CORS())
	NewConnectHandler(service).Register(router.Group("/api"))
	for _, owner := range []string{"alice", "bob"} {
		if err := database.DB.Create(&models.ConnectConnection{ID: owner + "-connection", UserID: owner, RequestID: owner, DesiredState: "disconnected", Status: "disconnected"}).Error; err != nil {
			t.Fatal(err)
		}
	}
	token, err := createAccountSession("alice")
	if err != nil {
		t.Fatal(err)
	}
	preflight := httptest.NewRequest(http.MethodOptions, "/api/connect/v1/connections", nil)
	preflight.Header.Set("Origin", "https://localhost")
	preflight.Header.Set("Access-Control-Request-Method", "GET")
	preflight.Header.Set("Access-Control-Request-Headers", "x-account-session,x-user-id")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, preflight)
	if w.Code != http.StatusNoContent || w.Header().Get("Access-Control-Allow-Origin") != "*" {
		t.Fatalf("mobile preflight rejected: %d %v", w.Code, w.Header())
	}
	for _, header := range []string{"x-account-session", "x-user-id"} {
		if !strings.Contains(strings.ToLower(w.Header().Get("Access-Control-Allow-Headers")), header) {
			t.Fatalf("preflight does not allow %s", header)
		}
	}
	for _, tc := range []struct {
		name, query, header string
		status              int
	}{
		{"mobile header", "?user_id=bob", token, http.StatusOK},
		{"query token rejected", "?account_session=" + token, "", http.StatusUnauthorized},
		{"invalid header rejected", "", "invalid-session", http.StatusUnauthorized},
		{"missing session rejected", "", "", http.StatusUnauthorized},
	} {
		t.Run(tc.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, "/api/connect/v1/connections"+tc.query, nil)
			req.Header.Set("Origin", "https://localhost")
			req.Header.Set("X-Account-Session", tc.header)
			req.Header.Set("X-User-ID", "bob")
			w := httptest.NewRecorder()
			router.ServeHTTP(w, req)
			if w.Code != tc.status || w.Header().Get("Access-Control-Allow-Origin") != "*" {
				t.Fatalf("status = %d, want %d", w.Code, tc.status)
			}
			if tc.status == http.StatusOK && (!strings.Contains(w.Body.String(), "alice-connection") || strings.Contains(w.Body.String(), "bob-connection")) {
				t.Fatalf("mobile response did not use the authenticated owner: %s", w.Body.String())
			}
		})
	}
}
