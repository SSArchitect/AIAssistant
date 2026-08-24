package handlers

import (
	"bytes"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
)

func TestValidateUserToolPolicySetting(t *testing.T) {
	for _, policy := range []string{"auto", "confirm", "deny", " CONFIRM "} {
		if err := validateUserToolSetting("tool.delete_drive.policy", policy); err != nil {
			t.Fatalf("expected policy %q to be valid: %v", policy, err)
		}
	}
	if err := validateUserToolSetting("tool.delete_drive.policy", "sometimes"); err == nil {
		t.Fatal("expected unsupported policy to be rejected")
	}
}

func TestToolPoliciesFromSettings(t *testing.T) {
	policies := toolPoliciesFromSettings(map[string]string{
		"tool.delete_drive.policy": "confirm",
		"tool.search.policy":       "deny",
		"tool.search.enabled":      "false",
	})
	if policies["delete_drive"] != "confirm" || policies["search"] != "deny" {
		t.Fatalf("unexpected policies: %#v", policies)
	}
	if len(policies) != 2 {
		t.Fatalf("expected only policy settings, got %#v", policies)
	}
}

func TestResolveToolApprovalPersistsTraceAndAlwaysAllowPolicy(t *testing.T) {
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/agent/tool-approvals/approval_test" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"approval_id":"approval_test",
			"run_id":"run_approval",
			"conversation_id":"conv-approval",
			"tool_name":"upsert_pulse_topic",
			"decision":"allow_always",
			"status":"approved",
			"request_count":1,
			"succeeded_count":1,
			"failed_count":0,
			"results":[],
			"events":[{
				"id":"evt_resolved",
				"run_id":"run_approval",
				"type":"approval.resolved",
				"status":"completed",
				"title":"Approval resolved",
				"payload":{"approval_id":"approval_test","tool_name":"upsert_pulse_topic","decision":"allow_always","request_count":1,"succeeded_count":1,"failed_count":0},
				"created_at":"2026-08-24T00:00:00Z"
			}],
			"skills_used":["upsert_pulse_topic"]
		}`))
	}))
	defer agentServer.Close()

	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}
	message := models.Message{
		ConversationID: "conv-approval",
		UserID:         "alice",
		Role:           "assistant",
		Content:        "waiting",
		RunID:          "run_approval",
		CreatedAt:      time.Now(),
	}
	if err := database.DB.Create(&message).Error; err != nil {
		t.Fatalf("create message: %v", err)
	}

	router := gin.New()
	handler := NewChatHandler(bridge.NewAgentClient(agentServer.URL, time.Second))
	router.POST("/api/tool-approvals/:id", handler.ResolveToolApproval)
	body := bytes.NewBufferString(`{"user_id":"alice","decision":"allow_always"}`)
	req := httptest.NewRequest(http.MethodPost, "/api/tool-approvals/approval_test", body)
	req.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	settings, err := loadUserSettings("alice")
	if err != nil {
		t.Fatalf("load settings: %v", err)
	}
	if settings["tool.upsert_pulse_topic.policy"] != "auto" {
		t.Fatalf("expected always-allow policy, got %#v", settings)
	}
	var stored models.Message
	if err := database.DB.First(&stored, message.ID).Error; err != nil {
		t.Fatalf("load message: %v", err)
	}
	for _, fragment := range []string{"approval.resolved", "approval_test", "upsert_pulse_topic"} {
		if !strings.Contains(stored.TraceSummary, fragment) {
			t.Fatalf("expected trace summary to contain %q, got %s", fragment, stored.TraceSummary)
		}
	}
}
