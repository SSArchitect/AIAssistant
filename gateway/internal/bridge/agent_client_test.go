package bridge

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestAgentClientChatSendsAgentIDAndDecodesTrace(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/agent/chat" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}

		var req ChatRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			t.Fatalf("decode request: %v", err)
		}
		if req.ConversationID != "conv-1" {
			t.Fatalf("unexpected conversation_id: %s", req.ConversationID)
		}
		if req.Message != "ping" {
			t.Fatalf("unexpected message: %s", req.Message)
		}
		if req.AgentID != "general_assistant" {
			t.Fatalf("unexpected agent_id: %s", req.AgentID)
		}
		if req.RoleID != "default" {
			t.Fatalf("unexpected role_id: %s", req.RoleID)
		}
		if len(req.Attachments) != 1 || req.Attachments[0].Kind != "image" || req.Attachments[0].DataURL == "" {
			t.Fatalf("unexpected attachments: %#v", req.Attachments)
		}

		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"conversation_id": "conv-1",
			"response": "pong",
			"skills_used": [],
			"citations": [
				{
					"index": 1,
					"title": "SpaceX files S-1",
					"url": "https://example.com/spacex-s1",
					"snippet": "Example filing details",
					"source": "test-search",
					"metadata": {"rank": 1}
				}
			],
			"model_used": "test-model",
			"tokens_used": {"input": 1, "output": 2},
			"agent_id": "general_assistant",
			"role_id": "default",
			"runtime": "self",
			"run_id": "run_123",
			"memory_updates": [
				{
					"id": "mem_1",
					"role_id": "default",
					"kind": "long_term",
					"content": "User likes concise replies",
					"source": "hook",
					"agent_id": null,
					"confidence": 0.9,
					"tags": ["explicit"],
					"created_at": "2026-06-18T00:00:00Z",
					"updated_at": "2026-06-18T00:00:00Z",
					"metadata": {"reason": "explicit_remember_request"}
				}
			],
			"events": [
				{
					"id": "evt_1",
					"run_id": "run_123",
					"type": "run.started",
					"status": "running",
					"title": "Run started",
					"payload": {"runtime": "self"},
					"created_at": "2026-06-18T00:00:00Z"
				}
			]
		}`))
	}))
	defer server.Close()

	client := NewAgentClient(server.URL, time.Second)
	resp, err := client.Chat(ChatRequest{
		ConversationID: "conv-1",
		Message:        "ping",
		AgentID:        "general_assistant",
		RoleID:         "default",
		Attachments: []ChatAttachment{
			{
				Name:    "reference.png",
				Type:    "image/png",
				Size:    12,
				Kind:    "image",
				DataURL: "data:image/png;base64,ZmFrZQ==",
			},
		},
	})
	if err != nil {
		t.Fatalf("Chat returned error: %v", err)
	}

	if resp.Response != "pong" {
		t.Fatalf("unexpected response: %s", resp.Response)
	}
	if resp.RunID != "run_123" {
		t.Fatalf("unexpected run_id: %s", resp.RunID)
	}
	if resp.Runtime != "self" {
		t.Fatalf("unexpected runtime: %s", resp.Runtime)
	}
	if resp.RoleID != "default" {
		t.Fatalf("unexpected role_id: %s", resp.RoleID)
	}
	if len(resp.MemoryUpdates) != 1 || resp.MemoryUpdates[0].ID != "mem_1" {
		t.Fatalf("unexpected memory updates: %#v", resp.MemoryUpdates)
	}
	if len(resp.Events) != 1 || resp.Events[0].Type != "run.started" {
		t.Fatalf("unexpected events: %#v", resp.Events)
	}
	if len(resp.Citations) != 1 || resp.Citations[0].URL != "https://example.com/spacex-s1" {
		t.Fatalf("unexpected citations: %#v", resp.Citations)
	}
	rank, ok := resp.Citations[0].Metadata["rank"].(float64)
	if !ok || rank != 1 {
		t.Fatalf("unexpected citation metadata: %#v", resp.Citations[0].Metadata)
	}
	if resp.TokensUsed["output"] != 2 {
		t.Fatalf("unexpected token usage: %#v", resp.TokensUsed)
	}
}

func TestAgentClientChatStreamDoesNotUseRequestTimeoutForBody(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/agent/chat/stream" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		flusher, ok := w.(http.Flusher)
		if !ok {
			t.Fatal("expected flusher")
		}
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = w.Write([]byte("event: meta\ndata: {\"run_id\":\"run_slow\"}\n\n"))
		flusher.Flush()
		time.Sleep(80 * time.Millisecond)
		_, _ = w.Write([]byte("event: response\ndata: {\"response\":\"slow final\",\"run_id\":\"run_slow\"}\n\n"))
	}))
	defer server.Close()

	client := NewAgentClient(server.URL, 20*time.Millisecond)
	resp, err := client.ChatStream(ChatRequest{
		ConversationID: "conv-slow",
		Message:        "slow stream",
		Stream:         true,
	})
	if err != nil {
		t.Fatalf("ChatStream returned error: %v", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("read stream body: %v", err)
	}
	if !strings.Contains(string(body), "slow final") {
		t.Fatalf("expected final response in stream body, got %s", string(body))
	}
}

func TestAgentClientSearch(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/agent/search" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}

		var req SearchRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			t.Fatalf("decode request: %v", err)
		}
		if req.Query != "AI Agent latest" {
			t.Fatalf("unexpected query: %s", req.Query)
		}
		if req.Limit != 3 {
			t.Fatalf("unexpected limit: %d", req.Limit)
		}

		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"query": "AI Agent latest",
			"sources": ["web"],
			"provider_errors": [],
			"results": [
				{
					"title": "Agent frameworks ship new release",
					"snippet": "Latest agent framework update.",
					"url": "https://example.com/agent-release",
					"source": "web",
					"metadata": {"rank": 1}
				}
			]
		}`))
	}))
	defer server.Close()

	client := NewAgentClient(server.URL, time.Second)
	resp, err := client.Search(SearchRequest{Query: "AI Agent latest", Limit: 3})
	if err != nil {
		t.Fatalf("Search returned error: %v", err)
	}
	if resp.Query != "AI Agent latest" || len(resp.Sources) != 1 || resp.Sources[0] != "web" {
		t.Fatalf("unexpected search response metadata: %#v", resp)
	}
	if len(resp.Results) != 1 || resp.Results[0].URL != "https://example.com/agent-release" {
		t.Fatalf("unexpected search results: %#v", resp.Results)
	}
	rank, ok := resp.Results[0].Metadata["rank"].(float64)
	if !ok || rank != 1 {
		t.Fatalf("unexpected metadata: %#v", resp.Results[0].Metadata)
	}
}

func TestAgentClientListAgents(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/agent/agents" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"agents": [
				{
					"id": "general_assistant",
					"name": "General Assistant",
					"description": "Default assistant",
					"runtime": "self",
					"framework": "native",
					"enabled": true,
					"experimental": false,
					"capabilities": ["chat", "tracing"],
					"metadata": {"available": true}
				}
			]
		}`))
	}))
	defer server.Close()

	client := NewAgentClient(server.URL, time.Second)
	resp, err := client.ListAgents()
	if err != nil {
		t.Fatalf("ListAgents returned error: %v", err)
	}

	if len(resp.Agents) != 1 {
		t.Fatalf("unexpected agents length: %d", len(resp.Agents))
	}
	agent := resp.Agents[0]
	if agent.ID != "general_assistant" || agent.Runtime != "self" || !agent.Enabled {
		t.Fatalf("unexpected agent: %#v", agent)
	}
	if len(agent.Capabilities) != 2 || agent.Capabilities[1] != "tracing" {
		t.Fatalf("unexpected capabilities: %#v", agent.Capabilities)
	}
}

func TestAgentClientGenerateImage(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/agent/aigc/image" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}

		var req AIGCImageRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			t.Fatalf("decode request: %v", err)
		}
		if req.Prompt != "a clean product shot" {
			t.Fatalf("unexpected prompt: %s", req.Prompt)
		}
		if req.AspectRatio != "16:9" {
			t.Fatalf("unexpected aspect ratio: %s", req.AspectRatio)
		}
		if req.PromptOptimizer == nil || !*req.PromptOptimizer {
			t.Fatalf("expected prompt optimizer true: %#v", req.PromptOptimizer)
		}

		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"id": "img_123",
			"provider": "minimax",
			"model": "image-01",
			"prompt": "a clean product shot",
			"aspect_ratio": "16:9",
			"response_format": "url",
			"images": [
				{
					"index": 0,
					"url": "https://example.com/generated.png",
					"mime_type": "image/png"
				}
			],
			"metadata": {"request_id": "abc"}
		}`))
	}))
	defer server.Close()

	promptOptimizer := true
	client := NewAgentClient(server.URL, time.Second)
	resp, err := client.GenerateImage(AIGCImageRequest{
		Prompt:          "a clean product shot",
		AspectRatio:     "16:9",
		N:               1,
		PromptOptimizer: &promptOptimizer,
	})
	if err != nil {
		t.Fatalf("GenerateImage returned error: %v", err)
	}
	if resp.Provider != "minimax" || resp.Model != "image-01" {
		t.Fatalf("unexpected response metadata: %#v", resp)
	}
	if len(resp.Images) != 1 || resp.Images[0].URL != "https://example.com/generated.png" {
		t.Fatalf("unexpected images: %#v", resp.Images)
	}
}

func TestAgentClientRolesCRUD(t *testing.T) {
	var created bool
	var updated bool
	var deleted bool
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch {
		case r.Method == http.MethodGet && r.URL.Path == "/agent/roles":
			if got := r.URL.Query().Get("user_id"); got != "user-1" {
				t.Fatalf("unexpected list roles user_id: %s", got)
			}
			_, _ = w.Write([]byte(`{
				"roles": [
					{
						"id": "default",
						"name": "Default Assistant",
						"description": "Default",
						"base_persona": "Helpful",
						"instructions": ["Be concise"],
						"enabled": true,
						"memory_enabled": true,
						"metadata": {"built_in": true}
					}
				]
			}`))
		case r.Method == http.MethodPost && r.URL.Path == "/agent/roles":
			created = true
			var req RoleWriteRequest
			if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
				t.Fatalf("decode create role: %v", err)
			}
			if req.UserID != "user-1" || req.ID != "custom_role" || req.Name != "Custom Role" {
				t.Fatalf("unexpected create role request: %#v", req)
			}
			_, _ = w.Write([]byte(`{
				"id": "custom_role",
				"name": "Custom Role",
				"description": "",
				"base_persona": "Persona",
				"instructions": [],
				"enabled": true,
				"memory_enabled": true,
				"metadata": {"built_in": false}
			}`))
		case r.Method == http.MethodPut && r.URL.Path == "/agent/roles/custom_role":
			updated = true
			var req RoleWriteRequest
			if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
				t.Fatalf("decode update role: %v", err)
			}
			if req.UserID != "user-1" {
				t.Fatalf("unexpected update role user_id: %#v", req)
			}
			_, _ = w.Write([]byte(`{
				"id": "custom_role",
				"name": "Updated Role",
				"description": "",
				"base_persona": "Persona",
				"instructions": ["One"],
				"enabled": true,
				"memory_enabled": true,
				"metadata": {"built_in": false}
			}`))
		case r.Method == http.MethodDelete && r.URL.Path == "/agent/roles/custom_role":
			if got := r.URL.Query().Get("user_id"); got != "user-1" {
				t.Fatalf("unexpected delete role user_id: %s", got)
			}
			deleted = true
			_, _ = w.Write([]byte(`{"status":"ok"}`))
		default:
			t.Fatalf("unexpected %s %s", r.Method, r.URL.Path)
		}
	}))
	defer server.Close()

	client := NewAgentClient(server.URL, time.Second)
	roles, err := client.ListRoles("user-1")
	if err != nil {
		t.Fatalf("ListRoles returned error: %v", err)
	}
	if len(roles.Roles) != 1 || roles.Roles[0].ID != "default" {
		t.Fatalf("unexpected roles: %#v", roles)
	}

	role, err := client.CreateRole(RoleWriteRequest{
		UserID:      "user-1",
		ID:          "custom_role",
		Name:        "Custom Role",
		BasePersona: "Persona",
	})
	if err != nil {
		t.Fatalf("CreateRole returned error: %v", err)
	}
	if role.ID != "custom_role" || !created {
		t.Fatalf("unexpected created role: %#v", role)
	}

	enabled := true
	role, err = client.UpdateRole("custom_role", RoleWriteRequest{
		UserID:  "user-1",
		Name:    "Updated Role",
		Enabled: &enabled,
	})
	if err != nil {
		t.Fatalf("UpdateRole returned error: %v", err)
	}
	if role.Name != "Updated Role" || !updated {
		t.Fatalf("unexpected updated role: %#v", role)
	}

	if err := client.DeleteRole("custom_role", "user-1"); err != nil {
		t.Fatalf("DeleteRole returned error: %v", err)
	}
	if !deleted {
		t.Fatal("expected delete request")
	}
}

func TestAgentClientRoleMemoriesCRUD(t *testing.T) {
	var created bool
	var deleted bool
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch {
		case r.Method == http.MethodGet && r.URL.Path == "/agent/roles/default/memories":
			if got := r.URL.Query().Get("user_id"); got != "user-1" {
				t.Fatalf("unexpected user_id query: %s", got)
			}
			if got := r.URL.Query().Get("kind"); got != "role" {
				t.Fatalf("unexpected kind query: %s", got)
			}
			_, _ = w.Write([]byte(`{
				"memories": [
					{
						"id": "mem_1",
						"role_id": "default",
						"user_id": "user-1",
						"kind": "role",
						"content": "Keep answers concise",
						"source": "manual",
						"confidence": 1,
						"tags": ["role_config"],
						"created_at": "2026-06-21T00:00:00Z",
						"updated_at": "2026-06-21T00:00:00Z",
						"metadata": {}
					}
				]
			}`))
		case r.Method == http.MethodPost && r.URL.Path == "/agent/roles/default/memories":
			created = true
			var req MemoryWriteRequest
			if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
				t.Fatalf("decode create memory: %v", err)
			}
			if req.UserID != "user-1" || req.Kind != "role" || req.Content != "Keep answers concise" {
				t.Fatalf("unexpected create memory request: %#v", req)
			}
			_, _ = w.Write([]byte(`{
				"id": "mem_1",
				"role_id": "default",
				"user_id": "user-1",
				"kind": "role",
				"content": "Keep answers concise",
				"source": "manual",
				"confidence": 1,
				"tags": ["role_config"],
				"created_at": "2026-06-21T00:00:00Z",
				"updated_at": "2026-06-21T00:00:00Z",
				"metadata": {}
			}`))
		case r.Method == http.MethodDelete && r.URL.Path == "/agent/roles/default/memories/mem_1":
			deleted = true
			if got := r.URL.Query().Get("user_id"); got != "user-1" {
				t.Fatalf("unexpected delete user_id query: %s", got)
			}
			_, _ = w.Write([]byte(`{"status":"ok"}`))
		default:
			t.Fatalf("unexpected %s %s", r.Method, r.URL.String())
		}
	}))
	defer server.Close()

	client := NewAgentClient(server.URL, time.Second)
	memories, err := client.ListRoleMemories("default", "user-1", "role", "")
	if err != nil {
		t.Fatalf("ListRoleMemories returned error: %v", err)
	}
	if len(memories.Memories) != 1 || memories.Memories[0].ID != "mem_1" {
		t.Fatalf("unexpected memories: %#v", memories)
	}

	memory, err := client.CreateRoleMemory("default", MemoryWriteRequest{
		UserID:  "user-1",
		Kind:    "role",
		Content: "Keep answers concise",
		Source:  "manual",
		Tags:    []string{"role_config"},
	})
	if err != nil {
		t.Fatalf("CreateRoleMemory returned error: %v", err)
	}
	if memory.ID != "mem_1" || !created {
		t.Fatalf("unexpected created memory: %#v", memory)
	}

	if err := client.DeleteRoleMemory("default", "mem_1", "user-1"); err != nil {
		t.Fatalf("DeleteRoleMemory returned error: %v", err)
	}
	if !deleted {
		t.Fatal("expected delete request")
	}
}

func TestAgentClientListRunsUsesFiltersAndDecodesEvents(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/agent/runs" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		if got := r.URL.Query().Get("conversation_id"); got != "conv-1" {
			t.Fatalf("unexpected conversation_id query: %s", got)
		}
		if got := r.URL.Query().Get("user_id"); got != "0" {
			t.Fatalf("unexpected user_id query: %s", got)
		}
		if got := r.URL.Query().Get("limit"); got != "10" {
			t.Fatalf("unexpected limit query: %s", got)
		}

		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"runs": [
				{
					"run_id": "run_123",
					"conversation_id": "conv-1",
					"agent_id": "general_assistant",
					"runtime": "self",
					"status": "completed",
					"input": "ping",
					"output": "pong",
					"model_used": "test-model",
					"tokens_used": {"input": 1},
					"skills_used": [],
					"duration_ms": 12,
					"started_at": "2026-06-18T00:00:00Z",
					"completed_at": "2026-06-18T00:00:01Z",
					"events": [
						{
							"id": "evt_1",
							"run_id": "run_123",
							"type": "run.completed",
							"status": "completed",
							"title": "Run completed",
							"payload": {},
							"duration_ms": 12,
							"created_at": "2026-06-18T00:00:01Z"
						}
					]
				}
			]
		}`))
	}))
	defer server.Close()

	client := NewAgentClient(server.URL, time.Second)
	resp, err := client.ListRuns("conv-1", "0", 10)
	if err != nil {
		t.Fatalf("ListRuns returned error: %v", err)
	}

	if len(resp.Runs) != 1 {
		t.Fatalf("unexpected runs length: %d", len(resp.Runs))
	}
	run := resp.Runs[0]
	if run.RunID != "run_123" || run.Status != "completed" {
		t.Fatalf("unexpected run: %#v", run)
	}
	if run.DurationMS == nil || *run.DurationMS != 12 {
		t.Fatalf("unexpected duration: %#v", run.DurationMS)
	}
	if run.CompletedAt == nil || *run.CompletedAt != "2026-06-18T00:00:01Z" {
		t.Fatalf("unexpected completed_at: %#v", run.CompletedAt)
	}
	if len(run.Events) != 1 || run.Events[0].Type != "run.completed" {
		t.Fatalf("unexpected events: %#v", run.Events)
	}
}

func TestAgentClientReturnsStatusBodyOnError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "agent unavailable", http.StatusServiceUnavailable)
	}))
	defer server.Close()

	client := NewAgentClient(server.URL, time.Second)
	_, err := client.ListAgents()
	if err == nil {
		t.Fatal("expected error")
	}
	if got := err.Error(); got != "agent returned status 503: agent unavailable\n" {
		t.Fatalf("unexpected error: %s", got)
	}
}
