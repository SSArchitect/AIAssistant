package handlers

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/connect"
	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

func setupConnectHandlerDB(t *testing.T) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	if e := database.Init(filepath.Join(t.TempDir(), "app.db")); e != nil {
		t.Fatal(e)
	}
}
func TestConnectManagementRequiresSessionAndOwner(t *testing.T) {
	setupConnectHandlerDB(t)
	s, e := connect.NewService(database.DB, make([]byte, 32), nil, connect.NewFeishu())
	if e != nil {
		t.Fatal(e)
	}
	defer s.Close()
	router := gin.New()
	NewConnectHandler(s).Register(router.Group("/api"))
	c := models.ConnectConnection{ID: "owned", UserID: "alice", Kind: "feishu", Name: "Work", DesiredState: "disconnected", Status: "disconnected", Secret: "private", RequestID: "request"}
	database.DB.Create(&c)
	alice, _ := createAccountSession("alice")
	bob, _ := createAccountSession("bob")
	for _, tc := range []struct {
		path, token string
		code        int
	}{{"/api/connect/v1/catalog?user_id=alice", "", 401}, {"/api/connect/v1/catalog?account_session=" + alice, "", 401}, {"/api/connect/v1/catalog", alice, 200}, {"/api/connect/v1/connections/owned", bob, 404}, {"/api/connect/v1/connections/owned", alice, 200}} {
		req := httptest.NewRequest("GET", tc.path, nil)
		req.Header.Set("X-Account-Session", tc.token)
		w := httptest.NewRecorder()
		router.ServeHTTP(w, req)
		if w.Code != tc.code {
			t.Fatalf("%s: %d %s", tc.path, w.Code, w.Body.String())
		}
		if strings.Contains(w.Body.String(), "private") {
			t.Fatal("credential disclosed")
		}
	}
}
func TestWebCannotAppendToConnectConversation(t *testing.T) {
	setupConnectHandlerDB(t)
	database.DB.Create(&models.Conversation{ID: "source-conv", UserID: "alice", AgentID: "super_chat", SourceID: "src"})
	router := gin.New()
	router.POST("/api/chat", NewChatHandler(nil).Chat)
	req := httptest.NewRequest("POST", "/api/chat", strings.NewReader(`{"conversation_id":"source-conv","user_id":"alice","query":"web message","agent_id":"super_chat"}`))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)
	if w.Code != 403 {
		t.Fatal(w.Code, w.Body.String())
	}
	var count int64
	database.DB.Model(&models.Message{}).Count(&count)
	if count != 0 {
		t.Fatal("rejected input persisted")
	}
}
func TestConnectRunnerFreezesContextAndSharesResultAccounting(t *testing.T) {
	setupConnectHandlerDB(t)
	if e := database.DB.AutoMigrate(&models.ConnectTurn{}); e != nil {
		t.Fatal(e)
	}
	database.DB.Create(&models.Conversation{ID: "conv", UserID: "alice", SourceID: "src", AgentID: "super_chat"})
	for _, m := range []models.Message{{ID: 1, ConversationID: "conv", UserID: "alice", Role: "assistant", Content: "previous"}, {ID: 2, ConversationID: "conv", UserID: "alice", Role: "user", Content: "current"}, {ID: 3, ConversationID: "conv", UserID: "alice", Role: "user", Content: "future"}} {
		database.DB.Create(&m)
	}
	var requests []bridge.ChatRequest
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req bridge.ChatRequest
		json.NewDecoder(r.Body).Decode(&req)
		requests = append(requests, req)
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"run_id":"run","status":"completed","response":{"response":"answer","tokens_used":{"input":3,"output":2,"total":5},"runtime":"self","model_used":"test"}}`))
	}))
	defer server.Close()
	runner := NewConnectRunner(NewChatHandler(bridge.NewAgentClient(server.URL, time.Second)))
	turn := models.ConnectTurn{ID: "turn", SourceID: "src", ExternalID: "msg", ConversationID: "conv", UserID: "alice", RunID: "run", Text: "current", RoleID: "mentor", UserMessageID: 2}
	database.DB.Create(&turn)
	response, e := runner.Run(context.Background(), turn, func(bridge.RunEvent) {})
	if e != nil {
		t.Fatal(e)
	}
	database.DB.First(&turn, "id = ?", turn.ID)
	database.DB.Model(&models.Message{}).Where("id = 1").Update("content", "changed-history")
	turn.RoleID = "changed-after-admission"
	if _, e = runner.Run(context.Background(), turn, func(bridge.RunEvent) {}); e != nil {
		t.Fatal(e)
	}
	raw, _ := json.Marshal(requests)
	if len(requests) != 2 || requests[0].RoleID != "mentor" || stringMustJSON(requests[0]) != stringMustJSON(requests[1]) || !strings.Contains(string(raw), "previous") || strings.Contains(string(raw), "future") || strings.Contains(string(raw), "changed-history") {
		t.Fatal(string(raw))
	}
	if e := database.DB.Transaction(func(tx *gorm.DB) error { return runner.SaveResult(tx, turn, response) }); e != nil {
		t.Fatal(e)
	}
	var usage models.TokenUsage
	database.DB.First(&usage, "run_id = ?", "run")
	if usage.TotalTokens != 5 || usage.AgentID != "super_chat" || usage.UserID != "alice" {
		t.Fatal(usage)
	}
}
func stringMustJSON(v any) string { b, _ := json.Marshal(v); return string(b) }

func TestConnectRoleManagementUsesSessionOwnerAndEnabledRoles(t *testing.T) {
	setupConnectHandlerDB(t)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/agent/roles" || r.URL.Query().Get("user_id") != "alice" {
			t.Errorf("unexpected role lookup: %s", r.URL)
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"roles":[{"id":"default","name":"Default","enabled":true},{"id":"mentor","name":"Mentor","enabled":true},{"id":"disabled","enabled":false}]}`))
	}))
	defer server.Close()
	s, err := connect.NewService(database.DB, make([]byte, 32), NewConnectRunner(NewChatHandler(bridge.NewAgentClient(server.URL, time.Second))))
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	database.DB.Create(&models.ConnectConnection{ID: "owned", UserID: "alice", RequestID: "create", DesiredState: "disconnected", Status: "disconnected"})
	alice, _ := createAccountSession("alice")
	bob, _ := createAccountSession("bob")
	router := gin.New()
	NewConnectHandler(s).Register(router.Group("/api"))
	for _, tc := range []struct {
		method, path, token, body string
		code                      int
	}{
		{"GET", "/api/connect/v1/roles?user_id=bob", alice, "", 200},
		{"GET", "/api/connect/v1/roles?user_id=alice", "", "", 401},
		{"PUT", "/api/connect/v1/connections/owned/role", bob, `{"role_id":"mentor","user_id":"alice"}`, 404},
		{"PUT", "/api/connect/v1/connections/owned/role", alice, `{"role_id":"disabled"}`, 400},
		{"PUT", "/api/connect/v1/connections/owned/role", alice, `{"role_id":"bob-role"}`, 400},
		{"PUT", "/api/connect/v1/connections/owned/role", alice, `{"role_id":"mentor","user_id":"bob"}`, 200},
	} {
		req := httptest.NewRequest(tc.method, tc.path, strings.NewReader(tc.body))
		req.Header.Set("X-Account-Session", tc.token)
		w := httptest.NewRecorder()
		router.ServeHTTP(w, req)
		if w.Code != tc.code {
			t.Fatal(tc, w.Code, w.Body.String())
		}
		if tc.method == "GET" && w.Code == 200 && (strings.Contains(w.Body.String(), "disabled") || !strings.Contains(w.Body.String(), "mentor")) {
			t.Fatal(w.Body.String())
		}
	}
	c, err := s.Get("alice", "owned")
	if err != nil || c.RoleID != "mentor" || c.DesiredState != "disconnected" {
		t.Fatal(c, err)
	}
}

func TestAccountDeletionRevokesAndRemovesOnlyOwnedConnections(t *testing.T) {
	setupConnectHandlerDB(t)
	s, e := connect.NewService(database.DB, make([]byte, 32), nil)
	if e != nil {
		t.Fatal(e)
	}
	defer s.Close()
	database.DB.Create(&models.Account{ID: "alice", Name: "Alice", NameKey: "alice"})
	for _, c := range []models.ConnectConnection{{ID: "alice-c", UserID: "alice", RequestID: "a", DesiredState: "enabled", Status: "connected"}, {ID: "bob-c", UserID: "bob", RequestID: "b", DesiredState: "enabled", Status: "connected"}} {
		database.DB.Create(&c)
	}
	database.DB.Create(&models.ConnectConnection{ID: "deleted-c", UserID: "alice", RequestID: "deleted"})
	if err := s.Delete("alice", "deleted-c"); err != nil {
		t.Fatal(err)
	}
	database.DB.Create(&models.ConnectSource{ID: "source", ConnectionID: "alice-c", UserID: "alice"})
	database.DB.Create(&models.ConnectTurn{ID: "turn", SourceID: "source", ExternalID: "m", ConnectionID: "alice-c", UserID: "alice", Status: "queued"})
	database.DB.Create(&models.ConnectDelivery{ID: "delivery", ConnectionID: "alice-c", TurnID: "turn", Status: "pending"})
	database.DB.Create(&models.ConnectCheck{ID: "check", ConnectionID: "alice-c"})
	handler := NewAdminHandler(nil)
	handler.SetConnectService(s)
	router := gin.New()
	router.DELETE("/accounts/:id", handler.DeleteAccount)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, httptest.NewRequest("DELETE", "/accounts/alice", nil))
	if w.Code != 200 {
		t.Fatal(w.Code, w.Body.String())
	}
	for _, m := range []any{&models.ConnectSource{}, &models.ConnectTurn{}, &models.ConnectDelivery{}, &models.ConnectCheck{}} {
		var count int64
		database.DB.Model(m).Count(&count)
		if count != 0 {
			t.Fatalf("owned rows retained: %T", m)
		}
	}
	remaining, e := s.Get("bob", "bob-c")
	if e != nil || remaining.DesiredState != "enabled" {
		t.Fatal(remaining, e)
	}
	var retained int64
	database.DB.Unscoped().Model(&models.ConnectConnection{}).Where("user_id = ?", "alice").Count(&retained)
	if retained != 0 {
		t.Fatal("account deletion retained connection tombstones")
	}
}

func TestConnectNoteAndDeleteEndpointsRequireOwner(t *testing.T) {
	setupConnectHandlerDB(t)
	s, err := connect.NewService(database.DB, make([]byte, 32), nil)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	if err := database.DB.Create(&models.ConnectConnection{ID: "owned", UserID: "alice", RequestID: "a", Name: "Work", Secret: "private", Note: "before", Status: "connected", DesiredState: "enabled", Generation: 3}).Error; err != nil {
		t.Fatal(err)
	}
	alice, _ := createAccountSession("alice")
	bob, _ := createAccountSession("bob")
	router := gin.New()
	NewConnectHandler(s).Register(router.Group("/api"))
	for _, tc := range []struct {
		method, path, token, body string
		code                      int
	}{
		{"PUT", "/owned/note", "", `{"note":"x"}`, 401},
		{"PUT", "/owned/note", bob, `{"note":"x","user_id":"alice"}`, 404},
		{"PUT", "/owned/note", alice, `{}`, 400},
		{"PUT", "/owned/note", alice, `{"note":null}`, 400},
		{"PUT", "/owned/note", alice, `{"note":"` + strings.Repeat("备", 501) + `"}`, 400},
		{"PUT", "/owned/note", alice, `{"note":" 工作账号 "}`, 200},
		{"PUT", "/owned/note", alice, `{"note":""}`, 200},
		{"DELETE", "/owned", "", "", 401},
		{"DELETE", "/owned?user_id=alice", bob, "", 404},
		{"DELETE", "/owned", alice, "", 200},
		{"DELETE", "/owned", alice, "", 200},
		{"GET", "/owned", alice, "", 404},
		{"PUT", "/owned/note", alice, `{"note":"revive"}`, 404},
	} {
		req := httptest.NewRequest(tc.method, "/api/connect/v1/connections"+tc.path, strings.NewReader(tc.body))
		req.Header.Set("X-Account-Session", tc.token)
		w := httptest.NewRecorder()
		router.ServeHTTP(w, req)
		if w.Code != tc.code {
			t.Fatalf("%s %s: got %d %s", tc.method, tc.path, w.Code, w.Body.String())
		}
		if strings.Contains(w.Body.String(), "private") {
			t.Fatal("secret disclosed")
		}
		if tc.method == "PUT" && tc.code == 200 {
			var result models.ConnectConnection
			if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
				t.Fatal(err)
			}
			var input struct {
				Note string `json:"note"`
			}
			json.Unmarshal([]byte(tc.body), &input)
			if result.Note != strings.TrimSpace(input.Note) || result.Generation != 3 || result.Status != "connected" {
				t.Fatal(result)
			}
		}
	}
}
