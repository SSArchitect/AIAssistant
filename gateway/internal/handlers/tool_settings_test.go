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

func TestResolveToolApprovalPersistsTraceAndConversationPolicy(t *testing.T) {
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
			"decision":"allow_conversation",
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
				"payload":{"approval_id":"approval_test","tool_name":"upsert_pulse_topic","decision":"allow_conversation","request_count":1,"succeeded_count":1,"failed_count":0},
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
	body := bytes.NewBufferString(`{"user_id":"alice","decision":"allow_conversation"}`)
	req := httptest.NewRequest(http.MethodPost, "/api/tool-approvals/approval_test", body)
	req.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	var policy models.ConversationToolPolicy
	if err := database.DB.First(
		&policy,
		"user_id = ? AND conversation_id = ? AND tool_name = ?",
		"alice",
		"conv-approval",
		"upsert_pulse_topic",
	).Error; err != nil {
		t.Fatalf("load conversation policy: %v", err)
	}
	if policy.Policy != "auto" {
		t.Fatalf("expected conversation auto policy, got %#v", policy)
	}
	settings, err := loadUserSettings("alice")
	if err != nil {
		t.Fatalf("load user settings: %v", err)
	}
	if _, exists := settings["tool.upsert_pulse_topic.policy"]; exists {
		t.Fatalf("conversation approval must not create an account-wide policy: %#v", settings)
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

func TestConversationToolPolicyOnlyAppliesToMatchingConversation(t *testing.T) {
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}
	if err := saveConversationToolPolicy(
		"alice",
		"conv-a",
		"upsert_pulse_topic",
		"auto",
	); err != nil {
		t.Fatalf("save conversation policy: %v", err)
	}

	_, policiesA, err := toolRuntimeSettingsForConversation("alice", "conv-a")
	if err != nil {
		t.Fatalf("load conv-a policies: %v", err)
	}
	if policiesA["upsert_pulse_topic"] != "auto" {
		t.Fatalf("expected conv-a policy, got %#v", policiesA)
	}
	_, policiesB, err := toolRuntimeSettingsForConversation("alice", "conv-b")
	if err != nil {
		t.Fatalf("load conv-b policies: %v", err)
	}
	if _, exists := policiesB["upsert_pulse_topic"]; exists {
		t.Fatalf("conversation policy leaked into conv-b: %#v", policiesB)
	}
}
