package handlers

import (
	"net/http"
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
	UserID string `json:"user_id,omitempty"`
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
	userID := requestUserID(c)
	if req.UserID != "" {
		userID = normalizedUserID(req.UserID)
	}

	conv := models.Conversation{
		ID:        uuid.New().String(),
		UserID:    userID,
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

	c.JSON(http.StatusOK, gin.H{
		"conversation": conv,
		"messages":     messages,
	})
}

func (h *ConversationHandler) Delete(c *gin.Context) {
	id := c.Param("id")
	userID := requestUserID(c)

	database.DB.Where("conversation_id = ? AND user_id = ?", id, userID).Delete(&models.Message{})
	database.DB.Delete(&models.Conversation{}, "id = ? AND user_id = ?", id, userID)

	c.JSON(http.StatusOK, gin.H{"status": "deleted"})
}
