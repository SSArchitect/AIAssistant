package handlers

import (
	"net/http"
	"strings"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
)

type ConversationHandler struct{}

func NewConversationHandler() *ConversationHandler {
	return &ConversationHandler{}
}

type conversationCreateRequest struct {
	UserID  string `json:"user_id,omitempty"`
	AgentID string `json:"agent_id,omitempty"`
}

type conversationMessageResponse struct {
	ID             uint      `json:"id"`
	ConversationID string    `json:"conversation_id"`
	UserID         string    `json:"user_id"`
	Role           string    `json:"role"`
	Content        string    `json:"content"`
	SkillsUsed     string    `json:"skills_used,omitempty"`
	Citations      string    `json:"citations,omitempty"`
	ModelUsed      string    `json:"model_used,omitempty"`
	Runtime        string    `json:"runtime,omitempty"`
	RunID          string    `json:"run_id,omitempty"`
	TraceEvents    string    `json:"trace_events,omitempty"`
	ErrorType      string    `json:"error_type,omitempty"`
	CreatedAt      time.Time `json:"created_at"`
}

func (h *ConversationHandler) List(c *gin.Context) {
	userID := requestUserID(c)
	var conversations []models.Conversation
	database.DB.Where("user_id = ?", userID).Order("updated_at desc").Find(&conversations)
	c.JSON(http.StatusOK, gin.H{"conversations": conversations})
}

func (h *ConversationHandler) Create(c *gin.Context) {
	var req conversationCreateRequest
	_ = c.ShouldBindJSON(&req)
	userID := requestUserIDWithBody(c, req.UserID)
	agentID := strings.TrimSpace(req.AgentID)
	if agentID == "" {
		agentID = "super_chat"
	}

	conv := models.Conversation{
		ID:        uuid.New().String(),
		UserID:    userID,
		AgentID:   agentID,
		Title:     "New Conversation",
		CreatedAt: time.Now(),
		UpdatedAt: time.Now(),
	}

	if err := database.DB.Create(&conv).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to create conversation"})
		return
	}

	c.JSON(http.StatusCreated, conv)
}

func (h *ConversationHandler) Get(c *gin.Context) {
	id := c.Param("id")
	userID := requestUserID(c)

	var conv models.Conversation
	if err := database.DB.First(&conv, "id = ? AND user_id = ?", id, userID).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "conversation not found"})
		return
	}

	var messages []models.Message
	database.DB.Where("conversation_id = ? AND user_id = ?", id, userID).Order(messageChronologicalOrder).Find(&messages)
	messageResponses := make([]conversationMessageResponse, 0, len(messages))
	includeTrace := shouldIncludeConversationTrace(c)
	for _, message := range messages {
		messageResponses = append(messageResponses, conversationMessageFromModel(message, includeTrace))
	}

	c.JSON(http.StatusOK, gin.H{
		"conversation": conv,
		"messages":     messageResponses,
	})
}

func shouldIncludeConversationTrace(c *gin.Context) bool {
	value := strings.ToLower(strings.TrimSpace(c.Query("include_trace")))
	return value == "1" || value == "true" || value == "yes"
}

func conversationMessageFromModel(message models.Message, includeTrace bool) conversationMessageResponse {
	response := conversationMessageResponse{
		ID:             message.ID,
		ConversationID: message.ConversationID,
		UserID:         message.UserID,
		Role:           message.Role,
		Content:        message.Content,
		SkillsUsed:     message.SkillsUsed,
		Citations:      message.Citations,
		ModelUsed:      message.ModelUsed,
		Runtime:        message.Runtime,
		RunID:          message.RunID,
		ErrorType:      message.ErrorType,
		CreatedAt:      message.CreatedAt,
	}
	if includeTrace {
		response.TraceEvents = message.TraceEvents
	}
	return response
}

func (h *ConversationHandler) Delete(c *gin.Context) {
	id := c.Param("id")
	userID := requestUserID(c)

	database.DB.Where("conversation_id = ? AND user_id = ?", id, userID).Delete(&models.Message{})
	database.DB.Delete(&models.Conversation{}, "id = ? AND user_id = ?", id, userID)

	c.JSON(http.StatusOK, gin.H{"status": "deleted"})
}
