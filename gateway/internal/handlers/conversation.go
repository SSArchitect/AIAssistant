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

func (h *ConversationHandler) List(c *gin.Context) {
	var conversations []models.Conversation
	database.DB.Order("updated_at desc").Find(&conversations)
	c.JSON(http.StatusOK, gin.H{"conversations": conversations})
}

func (h *ConversationHandler) Create(c *gin.Context) {
	conv := models.Conversation{
		ID:        uuid.New().String(),
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

	var conv models.Conversation
	if err := database.DB.First(&conv, "id = ?", id).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "conversation not found"})
		return
	}

	var messages []models.Message
	database.DB.Where("conversation_id = ?", id).Order(messageChronologicalOrder).Find(&messages)

	c.JSON(http.StatusOK, gin.H{
		"conversation": conv,
		"messages":     messages,
	})
}

func (h *ConversationHandler) Delete(c *gin.Context) {
	id := c.Param("id")

	database.DB.Where("conversation_id = ?", id).Delete(&models.Message{})
	database.DB.Delete(&models.Conversation{}, "id = ?", id)

	c.JSON(http.StatusOK, gin.H{"status": "deleted"})
}
