package connect

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"time"

	larkcore "github.com/larksuite/oapi-sdk-go/v3/core"
	"github.com/larksuite/oapi-sdk-go/v3/event/dispatcher"
	larkim "github.com/larksuite/oapi-sdk-go/v3/service/im/v1"
	larkws "github.com/larksuite/oapi-sdk-go/v3/ws"
)

type Feishu struct {
	client *http.Client
	base   string
}

func NewFeishu() *Feishu { return &Feishu{client: platformClient(), base: "https://open.feishu.cn"} }
func (a *Feishu) Descriptor() Descriptor {
	return Descriptor{ID: "feishu", Name: "飞书", Auth: "credentials", Fields: []Field{{Key: "app_id", Label: "App ID", Required: true}, {Key: "app_secret", Label: "App Secret", Secret: true, Required: true}}, Input: []string{"text"}, Output: []string{"text"}, HelpURL: "https://open.feishu.cn/document/server-docs/event-subscription-guide/event-subscription-configure-/request-url-configuration-case"}
}
func (a *Feishu) token(ctx context.Context, c Config) (string, error) {
	var r struct {
		Code  int    `json:"code"`
		Token string `json:"tenant_access_token"`
	}
	e := requestJSON(ctx, a.client, "POST", a.base+"/open-apis/auth/v3/tenant_access_token/internal", nil, map[string]string{"app_id": c["app_id"], "app_secret": c["app_secret"]}, &r)
	if e != nil {
		return "", e
	}
	if r.Code != 0 || r.Token == "" {
		return "", &SendError{Message: "飞书凭据无效或应用不可用"}
	}
	return r.Token, nil
}
func (a *Feishu) Authenticate(ctx context.Context, c Config) (AuthResult, error) {
	_, e := a.token(ctx, c)
	return AuthResult{Config: c, RemoteID: c["app_id"], Ready: e == nil}, e
}
func (a *Feishu) Check(ctx context.Context, c Config) ([]Diagnostic, error) {
	_, e := a.token(ctx, c)
	return []Diagnostic{{Name: "credentials", Status: map[bool]string{true: "passed", false: "failed"}[e == nil]}, {Name: "permissions", Status: "unknown", Detail: "需在飞书发布自建应用并订阅私聊消息，开启机器人发消息权限"}}, e
}
func ptr(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}
func feishuInbound(e *larkim.P2MessageReceiveV1) (Inbound, bool) {
	if e == nil || e.Event == nil || e.Event.Message == nil || e.Event.Sender == nil || e.Event.Sender.SenderId == nil {
		return Inbound{}, false
	}
	m := e.Event.Message
	s := e.Event.Sender
	if ptr(m.ChatType) != "p2p" || ptr(s.SenderType) != "user" {
		return Inbound{}, false
	}
	text := ""
	if ptr(m.MessageType) == "text" {
		var content struct {
			Text string `json:"text"`
		}
		if json.Unmarshal([]byte(ptr(m.Content)), &content) != nil {
			return Inbound{}, false
		}
		text = content.Text
	} else {
		text = "[不支持的消息类型]"
	}
	return Inbound{MessageID: ptr(m.MessageId), Peer: ptr(m.ChatId), Sender: ptr(s.SenderId.OpenId), Thread: ptr(m.ThreadId), Text: text, Unsupported: ptr(m.MessageType) != "text"}, true
}

// SDK logging is intentionally suppressed: its upstream errors can include transport credentials.
type quietLogger struct{}

func (quietLogger) Debug(context.Context, ...interface{}) {}
func (quietLogger) Info(context.Context, ...interface{})  {}
func (quietLogger) Warn(context.Context, ...interface{})  {}
func (quietLogger) Error(context.Context, ...interface{}) {}
func (a *Feishu) Listen(ctx context.Context, c Config, emit func(Inbound) error, healthy func()) error {
	handler := dispatcher.NewEventDispatcher("", "").OnP2MessageReceiveV1(func(_ context.Context, e *larkim.P2MessageReceiveV1) error {
		in, ok := feishuInbound(e)
		if !ok {
			return nil
		}
		return emit(in)
	})
	client := larkws.NewClient(c["app_id"], c["app_secret"], larkws.WithEventHandler(handler), larkws.WithLogger(quietLogger{}), larkws.WithLogLevel(larkcore.LogLevelError), larkws.WithAutoReconnect(false), larkws.WithOnReady(healthy), larkws.WithHttpClient(&http.Client{Timeout: 15 * time.Second}))
	defer client.Close()
	return client.Start(ctx)
}
func (a *Feishu) Send(ctx context.Context, c Config, out Outgoing) (string, error) {
	token, e := a.token(ctx, c)
	if e != nil {
		var send *SendError
		if errors.As(e, &send) && send.Unknown {
			return "", &SendError{Message: "飞书令牌暂时不可用，消息尚未发送", Retryable: true}
		}
		return "", e
	}
	content, _ := json.Marshal(map[string]string{"text": out.Text})
	var r struct {
		Code int `json:"code"`
		Data struct {
			MessageID string `json:"message_id"`
		} `json:"data"`
	}
	e = requestJSON(ctx, a.client, "POST", a.base+"/open-apis/im/v1/messages?receive_id_type=chat_id", map[string]string{"Authorization": "Bearer " + token}, map[string]string{"receive_id": out.Peer, "msg_type": "text", "content": string(content), "uuid": hash(out.DeliveryID)[:32]}, &r)
	if e != nil {
		return "", e
	}
	if r.Code != 0 {
		return "", &SendError{Message: fmt.Sprintf("飞书发送被拒绝（%d），请检查权限与接收方", r.Code), Retryable: r.Code == 99991400}
	}
	if r.Data.MessageID == "" {
		return "", &SendError{Message: "飞书未返回消息回执", Unknown: true}
	}
	return r.Data.MessageID, nil
}
