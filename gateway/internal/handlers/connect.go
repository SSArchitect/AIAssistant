package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/connect"
	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

// ConnectRunner shares the Gateway's context and tool-policy preparation with Web chat.
// It does not invoke a Gin handler or expose the Python service to external connectors.
type ConnectRunner struct{ chat *ChatHandler }

func NewConnectRunner(chat *ChatHandler) *ConnectRunner { return &ConnectRunner{chat: chat} }
func (r *ConnectRunner) Cancel(runID string) error      { return r.chat.agent.CancelRun(runID) }
func (r *ConnectRunner) ListRoles(ctx context.Context, user string) ([]connect.Role, error) {
	response, err := r.chat.agent.ListRolesContext(ctx, user)
	if err != nil {
		return nil, err
	}
	roles := []connect.Role{}
	for _, role := range response.Roles {
		if role.Enabled {
			roles = append(roles, connect.Role{ID: role.ID, Name: role.Name})
		}
	}
	return roles, nil
}
func (r *ConnectRunner) SaveResult(tx *gorm.DB, t models.ConnectTurn, response *bridge.ChatResponse) error {
	response.RunID = t.RunID
	msg := buildAssistantMessage(t.ConversationID, t.UserID, response)
	if e := tx.Create(msg).Error; e != nil {
		return e
	}
	return persistTokenUsageRecordDB(tx, t.ConversationID, t.UserID, msg.ID, "super_chat", msg.CreatedAt, response)
}
func (r *ConnectRunner) Run(ctx context.Context, t models.ConnectTurn, emit func(bridge.RunEvent)) (*bridge.ChatResponse, error) {
	var req bridge.ChatRequest
	if t.Request != "" {
		if e := json.Unmarshal([]byte(t.Request), &req); e != nil {
			return nil, e
		}
	} else {
		var conv models.Conversation
		if e := database.DB.First(&conv, "id = ? AND user_id = ? AND source_id = ?", t.ConversationID, t.UserID, t.SourceID).Error; e != nil {
			return nil, e
		}
		disabled, policies, e := toolRuntimeSettingsForConversation(t.UserID, t.ConversationID)
		if e != nil {
			return nil, e
		}
		req = bridge.ChatRequest{ConversationID: t.ConversationID, UserID: t.UserID, RoleID: connect.EffectiveRole(t.RoleID), Message: t.Text, AgentID: "super_chat", RunID: t.RunID, Stream: true, DisabledTools: disabled, ToolPolicies: policies, ContextBlocks: r.chat.persistedConversationContextBefore(t.ConversationID, t.UserID, t.UserMessageID)}
		b, e := json.Marshal(req)
		if e != nil {
			return nil, e
		}
		if e = database.DB.Model(&models.ConnectTurn{}).Where("id = ?", t.ID).Update("request", string(b)).Error; e != nil {
			return nil, e
		}
	}
	if r.chat.syncer != nil {
		if e := r.chat.syncer.SyncToAgent(); e != nil {
			return nil, e
		}
	}
	state, e := r.chat.agent.ConnectRun(ctx, &req, t.RunID, t.UserID)
	// A timed-out admission is safe to repeat using the SAME immutable request and run ID.
	if e != nil && ctx.Err() == nil {
		state, e = r.chat.agent.ConnectRun(ctx, &req, t.RunID, t.UserID)
	}
	if e != nil {
		return nil, e
	}
	seen := map[string]bool{}
	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()
	for {
		if state.Status == "completed" && state.Response != nil {
			return state.Response, nil
		}
		if state.Status != "running" {
			return nil, fmt.Errorf("run %s", state.Status)
		}
		if trace, e := r.chat.agent.GetRunContext(ctx, t.RunID); e == nil && trace.UserID == t.UserID {
			for _, event := range trace.Events {
				if !seen[event.ID] {
					seen[event.ID] = true
					emit(event)
				}
			}
		}
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-ticker.C:
		}
		next, e := r.chat.agent.ConnectRun(ctx, nil, t.RunID, t.UserID)
		if e != nil {
			continue
		}
		state = next
	}
}

type ConnectHandler struct{ service *connect.Service }

func NewConnectHandler(s *connect.Service) *ConnectHandler { return &ConnectHandler{service: s} }
func (h *ConnectHandler) Register(api *gin.RouterGroup) {
	g := api.Group("/connect/v1")
	g.Use(func(c *gin.Context) {
		// Header authentication avoids both anonymous user-id fallback and URL token logging.
		user, ok := accountSessionUserID(c.GetHeader("X-Account-Session"))
		if !ok {
			c.AbortWithStatusJSON(401, gin.H{"error": "valid account session required"})
			return
		}
		c.Set("connect_user", user)
		c.Header("Cache-Control", "no-store")
		c.Next()
	})
	g.GET("/catalog", func(c *gin.Context) {
		c.JSON(200, gin.H{"protocol_version": connect.ProtocolVersion, "connectors": h.service.Catalog()})
	})
	g.GET("/connections", func(c *gin.Context) {
		items, e := h.service.List(c.GetString("connect_user"))
		h.respond(c, gin.H{"connections": items}, e)
	})
	g.GET("/roles", func(c *gin.Context) {
		roles, err := h.service.ListRoles(c.Request.Context(), c.GetString("connect_user"))
		h.respond(c, gin.H{"roles": roles}, err)
	})
	g.PUT("/connections/:id/role", func(c *gin.Context) {
		var req struct {
			RoleID string `json:"role_id"`
		}
		if !h.decode(c, &req) {
			return
		}
		item, err := h.service.SetRole(c.Request.Context(), c.GetString("connect_user"), c.Param("id"), req.RoleID)
		h.respond(c, item, err)
	})
	g.POST("/connections", func(c *gin.Context) {
		var req connect.CreateRequest
		if !h.decode(c, &req) {
			return
		}
		ctx, cancel := context.WithTimeout(c.Request.Context(), 20*time.Second)
		defer cancel()
		item, e := h.service.Create(ctx, c.GetString("connect_user"), req)
		h.respond(c, item, e)
	})
	g.PUT("/connections/:id/note", func(c *gin.Context) {
		var req struct {
			Note *string `json:"note"`
		}
		if !h.decode(c, &req) {
			return
		}
		if req.Note == nil {
			h.respond(c, nil, connect.ErrInvalid)
			return
		}
		item, err := h.service.SetNote(c.GetString("connect_user"), c.Param("id"), *req.Note)
		h.respond(c, item, err)
	})
	g.DELETE("/connections/:id", func(c *gin.Context) {
		err := h.service.Delete(c.GetString("connect_user"), c.Param("id"))
		h.respond(c, gin.H{"deleted": true}, err)
	})
	g.GET("/connections/:id", func(c *gin.Context) {
		item, e := h.service.Detail(c.GetString("connect_user"), c.Param("id"))
		h.respond(c, item, e)
	})
	g.POST("/connections/:id/disconnect", func(c *gin.Context) {
		item, e := h.service.Disconnect(c.GetString("connect_user"), c.Param("id"))
		h.respond(c, item, e)
	})
	g.POST("/connections/:id/reconnect", func(c *gin.Context) {
		var req struct {
			Credentials connect.Config `json:"credentials"`
		}
		if !h.decode(c, &req) {
			return
		}
		ctx, cancel := context.WithTimeout(c.Request.Context(), 20*time.Second)
		defer cancel()
		item, e := h.service.Reconnect(ctx, c.GetString("connect_user"), c.Param("id"), req.Credentials)
		h.respond(c, item, e)
	})
	g.POST("/connections/:id/check", func(c *gin.Context) {
		item, e := h.service.Check(c.Request.Context(), c.GetString("connect_user"), c.Param("id"))
		h.respond(c, item, e)
	})
	g.GET("/connections/:id/checks/:check_id", func(c *gin.Context) {
		item, e := h.service.GetCheck(c.GetString("connect_user"), c.Param("id"), c.Param("check_id"))
		h.respond(c, item, e)
	})
	g.POST("/connections/:id/deliveries/:delivery_id/retry", func(c *gin.Context) {
		item, e := h.service.RetryDelivery(c.GetString("connect_user"), c.Param("id"), c.Param("delivery_id"))
		h.respond(c, item, e)
	})
}
func (h *ConnectHandler) decode(c *gin.Context, v any) bool {
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 16*1024)
	if e := json.NewDecoder(c.Request.Body).Decode(v); e != nil {
		c.JSON(400, gin.H{"error": "invalid request"})
		return false
	}
	return true
}
func (h *ConnectHandler) respond(c *gin.Context, v any, e error) {
	if e == nil {
		c.JSON(200, v)
		return
	}
	status := 500
	message := "Connect 操作失败，请稍后重试"
	switch {
	case errors.Is(e, connect.ErrNotFound):
		status = 404
		message = e.Error()
	case errors.Is(e, connect.ErrConflict):
		status = 409
		message = "请求重复或平台账号不匹配"
	case errors.Is(e, connect.ErrInvalid), errors.Is(e, connect.ErrUnsupported):
		status = 400
		message = e.Error()
	case errors.Is(e, connect.ErrDisconnected):
		status = 409
		message = "连接已断开"
	case errors.Is(e, connect.ErrForbidden):
		status = 403
		message = "当前来源未授权"
	}
	c.JSON(status, gin.H{"error": message})
}
