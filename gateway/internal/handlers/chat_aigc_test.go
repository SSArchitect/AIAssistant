package handlers

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/gin-gonic/gin"
)

func TestGenerateImagePreservesAgentErrorStatus(t *testing.T) {
	gin.SetMode(gin.TestMode)
	for _, status := range []int{http.StatusBadRequest, http.StatusUnprocessableEntity, http.StatusBadGateway} {
		t.Run(http.StatusText(status), func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("Content-Type", "application/json")
				w.WriteHeader(status)
				_, _ = w.Write([]byte(`{"detail":"invalid image input"}`))
			}))
			defer server.Close()
			router := gin.New()
			handler := NewChatHandler(bridge.NewAgentClient(server.URL, time.Second))
			router.POST("/api/aigc/image", handler.GenerateImage)
			request := httptest.NewRequest(http.MethodPost, "/api/aigc/image", strings.NewReader(`{"prompt":"redraw","provider":"spark","image_data_url":"data:image/png;base64,???"}`))
			request.Header.Set("Content-Type", "application/json")
			response := httptest.NewRecorder()
			router.ServeHTTP(response, request)
			if response.Code != status || !strings.Contains(response.Body.String(), "invalid image input") {
				t.Fatalf("expected status %d and agent error, got %d: %s", status, response.Code, response.Body.String())
			}
		})
	}
}

func TestGenerateImageUnavailableAgentReturnsBadGateway(t *testing.T) {
	gin.SetMode(gin.TestMode)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	server.Close()
	router := gin.New()
	handler := NewChatHandler(bridge.NewAgentClient(server.URL, time.Second))
	router.POST("/api/aigc/image", handler.GenerateImage)
	request := httptest.NewRequest(http.MethodPost, "/api/aigc/image", strings.NewReader(`{"prompt":"redraw"}`))
	request.Header.Set("Content-Type", "application/json")
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	if response.Code != http.StatusBadGateway {
		t.Fatalf("expected 502 for unavailable agent, got %d", response.Code)
	}
}
