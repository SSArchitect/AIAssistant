package handlers

import (
	"encoding/json"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
)

type ConversationHandler struct {
	agent *bridge.AgentClient
}

func NewConversationHandler(agent ...*bridge.AgentClient) *ConversationHandler {
	var agentClient *bridge.AgentClient
	if len(agent) > 0 {
		agentClient = agent[0]
	}
	return &ConversationHandler{agent: agentClient}
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
	Artifacts      string    `json:"artifacts,omitempty"`
	ModelUsed      string    `json:"model_used,omitempty"`
	Runtime        string    `json:"runtime,omitempty"`
	RunID          string    `json:"run_id,omitempty"`
	TraceEvents    string    `json:"trace_events,omitempty"`
	TraceSummary   string    `json:"trace_summary,omitempty"`
	FollowUps      string    `json:"follow_ups,omitempty"`
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
	includeTrace := shouldIncludeConversationTrace(c)
	query := database.DB.Where("conversation_id = ? AND user_id = ?", id, userID).Order(messageChronologicalOrder)
	if !includeTrace {
		query = query.Omit("trace_events")
	}
	query.Find(&messages)
	messageResponses := make([]conversationMessageResponse, 0, len(messages))
	for _, message := range messages {
		messageResponses = append(messageResponses, conversationMessageFromModel(message, includeTrace))
	}
	h.ensureLatestFollowUpsAsync(conv, messages, userID)

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
		Artifacts:      message.Artifacts,
		ModelUsed:      message.ModelUsed,
		Runtime:        message.Runtime,
		RunID:          message.RunID,
		TraceSummary:   message.TraceSummary,
		FollowUps:      message.FollowUps,
		ErrorType:      message.ErrorType,
		CreatedAt:      message.CreatedAt,
	}
	if includeTrace {
		response.TraceEvents = message.TraceEvents
	}
	return response
}

func (h *ConversationHandler) ensureLatestFollowUpsAsync(conv models.Conversation, messages []models.Message, userID string) {
	if h.agent == nil || conv.AgentID != superChatAgentID || len(messages) == 0 {
		return
	}

	latestIndex := len(messages) - 1
	latest := messages[latestIndex]
	if latest.Role != "assistant" ||
		strings.TrimSpace(latest.ErrorType) != "" ||
		strings.TrimSpace(latest.Content) == "" ||
		strings.TrimSpace(latest.FollowUps) != "" {
		return
	}

	userQuestion := ""
	for i := latestIndex - 1; i >= 0; i-- {
		if messages[i].Role == "user" {
			userQuestion = strings.TrimSpace(messages[i].Content)
			break
		}
	}
	if userQuestion == "" {
		return
	}

	messageID := latest.ID
	assistantAnswer := strings.TrimSpace(latest.Content)
	language := followUpLanguage(userQuestion + "\n" + assistantAnswer)

	go func() {
		var stored models.Message
		if err := database.DB.First(&stored, "id = ? AND user_id = ?", messageID, userID).Error; err != nil {
			slog.Warn("Follow-up backfill skipped; assistant message not found", "message_id", messageID, "error", err)
			return
		}
		if strings.TrimSpace(stored.FollowUps) != "" {
			return
		}

		resp, err := h.agent.GenerateFollowUps(bridge.FollowUpRequest{
			UserQuestion:    userQuestion,
			AssistantAnswer: assistantAnswer,
			Language:        language,
		})
		if err != nil {
			slog.Warn("Follow-up backfill failed", "message_id", messageID, "error", err)
			return
		}
		questions := normalizeFollowUpQuestions(resp.Questions)
		if len(questions) == 0 {
			return
		}
		payload, err := json.Marshal(questions)
		if err != nil {
			slog.Warn("Failed to marshal backfilled follow-ups", "message_id", messageID, "error", err)
			return
		}
		if err := database.DB.Model(&models.Message{}).
			Where("id = ? AND user_id = ? AND (follow_ups = '' OR follow_ups IS NULL)", messageID, userID).
			Update("follow_ups", string(payload)).Error; err != nil {
			slog.Warn("Failed to persist backfilled follow-ups", "message_id", messageID, "error", err)
		}
	}()
}

func (h *ConversationHandler) Delete(c *gin.Context) {
	id := c.Param("id")
	userID := requestUserID(c)

	database.DB.Where("conversation_id = ? AND user_id = ?", id, userID).Delete(&models.Message{})
	database.DB.Delete(&models.Conversation{}, "id = ? AND user_id = ?", id, userID)

	c.JSON(http.StatusOK, gin.H{"status": "deleted"})
}
