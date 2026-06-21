package handlers

import (
	"net/http"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/gin-gonic/gin"
)

type HealthHandler struct {
	agent *bridge.AgentClient
}

func NewHealthHandler(agent *bridge.AgentClient) *HealthHandler {
	return &HealthHandler{agent: agent}
}

func (h *HealthHandler) Health(c *gin.Context) {
	agentStatus := "ok"
	if err := h.agent.Health(); err != nil {
		agentStatus = "unavailable"
	}

	c.JSON(http.StatusOK, gin.H{
		"status": "ok",
		"agent":  agentStatus,
	})
}
