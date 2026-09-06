package connect

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/skip2/go-qrcode"
)

type Weixin struct {
	client *http.Client
	base   string
}

func NewWeixin() *Weixin {
	return &Weixin{client: platformClient(), base: "https://ilinkai.weixin.qq.com"}
}
func (a *Weixin) Descriptor() Descriptor {
	return Descriptor{ID: "weixin", Name: "微信", Auth: "qr", Fields: []Field{}, Input: []string{"text"}, Output: []string{"text"}}
}
func (a *Weixin) api(ctx context.Context, c Config, method, path string, body map[string]any, out any) error {
	base := a.base
	if c["base_url"] != "" {
		base = c["base_url"]
	}
	random := make([]byte, 4)
	_, _ = rand.Read(random)
	uin := base64.StdEncoding.EncodeToString([]byte(strconv.FormatUint(uint64(binary.BigEndian.Uint32(random)), 10)))
	// Wire profile pinned to Tencent/openclaw-weixin 2f4dcbf57bedf0e17e266fdedcf0cd2dd141b7d3 (2.4.8).
	headers := map[string]string{"AuthorizationType": "ilink_bot_token", "X-WECHAT-UIN": uin, "iLink-App-Id": "bot", "iLink-App-ClientVersion": "132104", "User-Agent": "AgentAssistant/1.0"}
	if c["bot_token"] != "" {
		headers["Authorization"] = "Bearer " + c["bot_token"]
	}
	if body != nil {
		body["base_info"] = map[string]string{"channel_version": "2.4.8", "bot_agent": "AgentAssistant/1.0"}
	}
	return requestJSON(ctx, a.client, method, base+path, headers, body, out)
}
func validWeixinBase(raw string) bool {
	u, e := url.Parse(raw)
	return e == nil && u.Scheme == "https" && u.User == nil && u.Port() == "" && (u.Hostname() == "ilinkai.weixin.qq.com" || strings.HasSuffix(u.Hostname(), ".weixin.qq.com")) && (u.Path == "" || u.Path == "/") && u.RawQuery == "" && u.Fragment == ""
}
func (a *Weixin) Authenticate(ctx context.Context, c Config) (AuthResult, error) {
	if c["bot_token"] != "" {
		return AuthResult{Config: c, RemoteID: c["bot_id"], Sender: c["user_id"], Ready: true}, nil
	}
	if c["qrcode"] == "" {
		var r struct {
			QRCode  string `json:"qrcode"`
			Content string `json:"qrcode_img_content"`
		}
		e := a.api(ctx, c, "POST", "/ilink/bot/get_bot_qrcode?bot_type=3", map[string]any{"local_token_list": []string{}}, &r)
		if e != nil {
			return AuthResult{}, e
		}
		if r.QRCode == "" || r.Content == "" {
			return AuthResult{}, &SendError{Message: "微信未返回有效二维码"}
		}
		c["qrcode"] = r.QRCode
		c["qr_expires"] = time.Now().Add(5 * time.Minute).Format(time.RFC3339)
		png, e := qrcode.Encode(r.Content, qrcode.Medium, 256)
		if e != nil {
			return AuthResult{}, e
		}
		c["qr_image"] = "data:image/png;base64," + base64.StdEncoding.EncodeToString(png)
		return AuthResult{Config: c, NextAction: actionJSON("qr", c["qr_image"], "用微信扫描并确认连接")}, nil
	}
	expires, _ := time.Parse(time.RFC3339, c["qr_expires"])
	if time.Now().After(expires) {
		return AuthResult{}, &SendError{Message: "二维码已过期，请重新连接"}
	}
	var r struct {
		Status   string `json:"status"`
		Token    string `json:"bot_token"`
		BotID    string `json:"ilink_bot_id"`
		UserID   string `json:"ilink_user_id"`
		BaseURL  string `json:"baseurl"`
		Redirect string `json:"redirect_host"`
	}
	e := a.api(ctx, c, "GET", "/ilink/bot/get_qrcode_status?qrcode="+url.QueryEscape(c["qrcode"]), nil, &r)
	if e != nil {
		var send *SendError
		if ctx.Err() == nil && errors.As(e, &send) && send.Timeout {
			return AuthResult{Config: c, NextAction: actionJSON("qr", c["qr_image"], "等待微信确认")}, nil
		}
		return AuthResult{}, e
	}
	if r.Status == "confirmed" {
		if r.Token == "" || r.BotID == "" || r.UserID == "" {
			return AuthResult{}, &SendError{Message: "微信授权未返回完整身份"}
		}
		if r.BaseURL != "" {
			if !validWeixinBase(r.BaseURL) {
				return AuthResult{}, ErrInvalid
			}
			c["base_url"] = strings.TrimRight(r.BaseURL, "/")
		}
		c["bot_token"] = r.Token
		c["bot_id"] = r.BotID
		c["user_id"] = r.UserID
		delete(c, "qr_image")
		delete(c, "qrcode")
		return AuthResult{Config: c, RemoteID: r.BotID, Sender: r.UserID, Ready: true}, nil
	}
	if r.Status == "scaned_but_redirect" {
		base := "https://" + r.Redirect
		if !validWeixinBase(base) {
			return AuthResult{}, ErrInvalid
		}
		c["base_url"] = strings.TrimRight(base, "/")
	}
	if r.Status != "wait" && r.Status != "scaned" && r.Status != "scaned_but_redirect" {
		return AuthResult{}, &SendError{Message: "微信授权尚未完成或需要额外验证，请重新连接并在微信确认"}
	}
	return AuthResult{Config: c, NextAction: actionJSON("qr", c["qr_image"], "等待微信确认")}, nil
}
func (a *Weixin) Check(ctx context.Context, c Config) ([]Diagnostic, error) {
	if c["bot_token"] == "" {
		return []Diagnostic{{Name: "credentials", Status: "unknown", Detail: "尚未完成扫码授权"}}, nil
	}
	var r struct {
		Ret  int `json:"ret"`
		Code int `json:"errcode"`
	}
	e := a.api(ctx, c, "POST", "/ilink/bot/getconfig", map[string]any{"ilink_user_id": c["user_id"]}, &r)
	if e != nil {
		return nil, e
	}
	if r.Ret != 0 || r.Code != 0 {
		return nil, &SendError{Message: "微信登录已失效或接口不可用，请重新连接"}
	}
	return []Diagnostic{{Name: "credentials", Status: "passed"}}, nil
}

type weixinMessage struct {
	ID      json.Number `json:"message_id"`
	From    string      `json:"from_user_id"`
	Type    int         `json:"message_type"`
	Group   string      `json:"group_id"`
	Context string      `json:"context_token"`
	Items   []struct {
		Type int `json:"type"`
		Text struct {
			Text string `json:"text"`
		} `json:"text_item"`
	} `json:"item_list"`
}

func (a *Weixin) Listen(ctx context.Context, c Config, emit func(Inbound) error, healthy func()) error {
	cursor := c["cursor"]
	for ctx.Err() == nil {
		var r struct {
			Ret      int             `json:"ret"`
			Code     int             `json:"errcode"`
			Cursor   string          `json:"get_updates_buf"`
			Messages []weixinMessage `json:"msgs"`
		}
		e := a.api(ctx, c, "POST", "/ilink/bot/getupdates", map[string]any{"get_updates_buf": cursor}, &r)
		if e != nil {
			var send *SendError
			if ctx.Err() == nil && errors.As(e, &send) && send.Timeout {
				continue
			}
			return e
		}
		if r.Ret != 0 || r.Code != 0 {
			return &SendError{Message: "微信接收失败，请检查登录状态"}
		}
		healthy()
		for _, m := range r.Messages {
			if m.Type != 1 || m.Group != "" || m.ID == "" {
				continue
			}
			var texts []string
			for _, item := range m.Items {
				if item.Type == 1 {
					texts = append(texts, item.Text.Text)
				}
			}
			if len(texts) == 0 {
				texts = []string{}
			}
			if e = emit(Inbound{MessageID: m.ID.String(), Sender: m.From, Peer: m.From, Text: strings.Join(texts, "\n"), ContextToken: m.Context, Unsupported: len(texts) == 0}); e != nil {
				return e
			}
		}
		// Advance only after EVERY accepted item is durable. A crash before this repeats, never loses, messages.
		if r.Cursor != "" {
			if e = emit(Inbound{Cursor: r.Cursor}); e != nil {
				return e
			}
			cursor = r.Cursor
		}
		if len(r.Messages) == 0 && !pause(ctx, 300*time.Millisecond) {
			return ctx.Err()
		}
	}
	return ctx.Err()
}
func (a *Weixin) Send(ctx context.Context, c Config, out Outgoing) (string, error) {
	if out.ContextToken == "" {
		return "", &SendError{Message: "微信回复上下文不可用，请先在微信发送新消息"}
	}
	var r struct {
		Ret  int `json:"ret"`
		Code int `json:"errcode"`
	}
	e := a.api(ctx, c, "POST", "/ilink/bot/sendmessage", map[string]any{"msg": map[string]any{"from_user_id": "", "to_user_id": out.Peer, "client_id": out.DeliveryID, "message_type": 2, "message_state": 2, "context_token": out.ContextToken, "item_list": []any{map[string]any{"type": 1, "text_item": map[string]string{"text": out.Text}}}}}, &r)
	if e != nil {
		return "", e
	}
	if r.Ret != 0 || r.Code != 0 {
		return "", &SendError{Message: fmt.Sprintf("微信发送被拒绝（%d/%d）", r.Ret, r.Code)}
	}
	return out.DeliveryID, nil
}
