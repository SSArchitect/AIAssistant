package connect

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	larkim "github.com/larksuite/oapi-sdk-go/v3/service/im/v1"
)

func TestFeishuNormalizationRejectsGroupsAndBots(t *testing.T) {
	var event larkim.P2MessageReceiveV1
	err := json.Unmarshal([]byte(`{"event":{"sender":{"sender_id":{"open_id":"ou_1"},"sender_type":"user"},"message":{"message_id":"om_1","chat_id":"oc_1","thread_id":"thread","chat_type":"p2p","message_type":"text","content":"{\"text\":\"hello\"}"}}}`), &event)
	if err != nil {
		t.Fatal(err)
	}
	got, ok := feishuInbound(&event)
	if !ok || got.MessageID != "om_1" || got.Text != "hello" || got.Sender != "ou_1" || got.Thread != "thread" {
		t.Fatal(got, ok)
	}
	*event.Event.Message.ChatType = "group"
	if _, ok = feishuInbound(&event); ok {
		t.Fatal("group accepted")
	}
	*event.Event.Message.ChatType = "p2p"
	*event.Event.Sender.SenderType = "app"
	if _, ok = feishuInbound(&event); ok {
		t.Fatal("bot loop accepted")
	}
	*event.Event.Sender.SenderType = "user"
	*event.Event.Message.MessageType = "image"
	if got, ok = feishuInbound(&event); !ok || !got.Unsupported {
		t.Fatal("media wasn't routed to control reply")
	}
}
func TestFeishuSendContractAndReadOnlyCheck(t *testing.T) {
	var sent []map[string]string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if strings.Contains(r.URL.Path, "tenant_access_token") {
			w.Write([]byte(`{"code":0,"tenant_access_token":"token"}`))
			return
		}
		if r.URL.Path != "/open-apis/im/v1/messages" || r.URL.Query().Get("receive_id_type") != "chat_id" || r.Header.Get("Authorization") != "Bearer token" {
			t.Error("unexpected send", r.URL)
		}
		var body map[string]string
		json.NewDecoder(r.Body).Decode(&body)
		sent = append(sent, body)
		w.Write([]byte(`{"code":0,"data":{"message_id":"remote"}}`))
	}))
	defer server.Close()
	a := &Feishu{base: server.URL, client: server.Client()}
	cfg := Config{"app_id": "app", "app_secret": "secret"}
	if _, e := a.Check(context.Background(), cfg); e != nil {
		t.Fatal(e)
	}
	if len(sent) != 0 {
		t.Fatal("check sent a message")
	}
	for i := 0; i < 2; i++ {
		if id, e := a.Send(context.Background(), cfg, Outgoing{DeliveryID: "turn:0", Peer: "chat", Text: "最终答案"}); e != nil || id != "remote" {
			t.Fatal(id, e)
		}
	}
	if len(sent) != 2 || sent[0]["uuid"] != sent[1]["uuid"] || sent[0]["receive_id"] != "chat" || sent[0]["msg_type"] != "text" {
		t.Fatal(sent)
	}
}
func TestWeixinQRIdentityAndRedirectValidation(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/ilink/bot/get_bot_qrcode":
			if r.Method != "POST" || r.URL.Query().Get("bot_type") != "3" {
				t.Error("QR contract", r.Method, r.URL)
			}
			w.Write([]byte(`{"qrcode":"opaque","qrcode_img_content":"https://example.com/scan"}`))
		case "/ilink/bot/get_qrcode_status":
			w.Write([]byte(`{"status":"confirmed","bot_token":"private-token","ilink_bot_id":"bot","ilink_user_id":"user"}`))
		default:
			t.Error(r.URL)
		}
	}))
	defer server.Close()
	a := &Weixin{base: server.URL, client: server.Client()}
	first, e := a.Authenticate(context.Background(), Config{})
	if e != nil || first.Ready || !strings.Contains(first.NextAction, "data:image/png;base64,") {
		t.Fatal(first.Ready, e)
	}
	next, e := a.Authenticate(context.Background(), first.Config)
	if e != nil || !next.Ready || next.Sender != "user" || next.RemoteID != "bot" {
		t.Fatal(next, e)
	}
	for _, url := range []string{"http://ilinkai.weixin.qq.com", "https://weixin.qq.com.attacker.test", "https://user@ilinkai.weixin.qq.com", "https://127.0.0.1", "https://ilinkai.weixin.qq.com:443", "https://ilinkai.weixin.qq.com/path"} {
		if validWeixinBase(url) {
			t.Fatal("unsafe redirect", url)
		}
	}
	if !validWeixinBase("https://ilinkai.weixin.qq.com") {
		t.Fatal("legitimate base rejected")
	}
}
func TestWeixinPersistsMessagesBeforeCursorAndPreservesLargeIDs(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"ret":0,"get_updates_buf":"next","msgs":[{"message_id":9007199254740993,"from_user_id":"user","message_type":1,"context_token":"ctx","item_list":[{"type":1,"text_item":{"text":"hello"}}]},{"message_id":2,"from_user_id":"bot","message_type":2}]}`))
	}))
	defer server.Close()
	a := &Weixin{base: server.URL, client: server.Client()}
	var inputs []Inbound
	done := errors.New("done")
	e := a.Listen(context.Background(), Config{}, func(in Inbound) error {
		inputs = append(inputs, in)
		if in.Cursor != "" {
			return done
		}
		return nil
	}, func() {})
	if e != done || len(inputs) != 2 || inputs[0].MessageID != "9007199254740993" || inputs[0].ContextToken != "ctx" || inputs[1].Cursor != "next" {
		t.Fatal(inputs, e)
	}
	inputs = nil
	a.Listen(context.Background(), Config{}, func(in Inbound) error { inputs = append(inputs, in); return done }, func() {})
	if len(inputs) != 1 || inputs[0].Cursor != "" {
		t.Fatal("cursor advanced before persistence")
	}
}
func TestWeixinSendRequiresContextAndHTTPAmbiguity(t *testing.T) {
	calls := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		var body struct {
			Msg map[string]any `json:"msg"`
		}
		json.NewDecoder(r.Body).Decode(&body)
		if body.Msg["context_token"] != "ctx" || body.Msg["client_id"] != "turn:0" || body.Msg["message_state"] != float64(2) {
			t.Error(body)
		}
		w.WriteHeader(503)
	}))
	defer server.Close()
	a := &Weixin{base: server.URL, client: server.Client()}
	if _, e := a.Send(context.Background(), Config{}, Outgoing{Text: "answer"}); e == nil || calls != 0 {
		t.Fatal("missing context attempted send")
	}
	_, e := a.Send(context.Background(), Config{}, Outgoing{DeliveryID: "turn:0", Peer: "user", Text: "answer", ContextToken: "ctx"})
	var send *SendError
	if !errors.As(e, &send) || !send.Unknown || send.Retryable {
		t.Fatal("ambiguous response auto-retried", e)
	}
}
