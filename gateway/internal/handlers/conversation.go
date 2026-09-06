package handlers

import (
	"encoding/base64"
	"encoding/json"
	"log/slog"
	"net/http"
	"strconv"
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
	UserID    string `json:"user_id,omitempty"`
	AgentID   string `json:"agent_id,omitempty"`
	RequestID string `json:"request_id,omitempty"`
}

type conversationMessageResponse struct {
	ID             uint      `json:"id"`
	ConversationID string    `json:"conversation_id"`
	UserID         string    `json:"user_id"`
	Role           string    `json:"role"`
	Content        string    `json:"content"`
	Reasoning      string    `json:"reasoning,omitempty"`
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

type conversationCursor struct {
	UpdatedAt time.Time `json:"updated_at"`
	ID        string    `json:"id"`
}

func (h *ConversationHandler) List(c *gin.Context) {
	userID := requestUserID(c)
	query := database.DB.Where("user_id = ?", userID)
	var conversations = make([]models.Conversation, 0)
	// Keep the original contract for API clients that do not request pagination.
	if c.Query("limit") == "" {
		if err := query.Order("updated_at desc, id desc").Find(&conversations).Error; err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to list conversations"})
			return
		}
		c.JSON(http.StatusOK, gin.H{"conversations": conversations})
		return
	}
	limit, err := strconv.Atoi(c.Query("limit"))
	if err != nil || limit < 1 || limit > 100 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "limit must be between 1 and 100"})
		return
	}
	if search := strings.TrimSpace(c.Query("q")); search != "" {
		escaped := strings.NewReplacer("\\", "\\\\", "%", "\\%", "_", "\\_").Replace(search)
		query = query.Where("title LIKE ? ESCAPE '\\'", "%"+escaped+"%")
	}
	var total int64
	if err := query.Model(&models.Conversation{}).Count(&total).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to count conversations"})
		return
	}
	if encoded := c.Query("cursor"); encoded != "" {
		var cursor conversationCursor
		raw, err := base64.RawURLEncoding.DecodeString(encoded)
		if err != nil || json.Unmarshal(raw, &cursor) != nil || cursor.ID == "" || cursor.UpdatedAt.IsZero() {
			c.JSON(http.StatusBadRequest, gin.H{"error": "invalid conversation cursor"})
			return
		}
		query = query.Where("updated_at < ? OR (updated_at = ? AND id < ?)", cursor.UpdatedAt, cursor.UpdatedAt, cursor.ID)
	}
	if err := query.Order("updated_at desc, id desc").Limit(limit + 1).Find(&conversations).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to list conversations"})
		return
	}
	more := len(conversations) > limit
	next := ""
	if more {
		conversations = conversations[:limit]
		last := conversations[len(conversations)-1]
		raw, _ := json.Marshal(conversationCursor{UpdatedAt: last.UpdatedAt, ID: last.ID})
		next = base64.RawURLEncoding.EncodeToString(raw)
	}
	c.JSON(http.StatusOK, gin.H{"conversations": conversations, "has_more": more, "next_cursor": next, "total": total})
}

func (h *ConversationHandler) Create(c *gin.Context) {
	var req conversationCreateRequest
	_ = c.ShouldBindJSON(&req)
	userID := requestUserIDWithBody(c, req.UserID)
	agentID := strings.TrimSpace(req.AgentID)
	if agentID == "" {
		agentID = "super_chat"
	}
	requestID := strings.TrimSpace(req.RequestID)
	if len(requestID) > 160 {
		requestID = requestID[:160]
	}
	if requestID != "" {
		var existing models.Conversation
		if err := database.DB.First(
			&existing,
			"user_id = ? AND client_request_id = ?",
			userID,
			requestID,
		).Error; err == nil {
			c.JSON(http.StatusOK, existing)
			return
		}
	}

	conv := models.Conversation{
		ID:              uuid.New().String(),
		UserID:          userID,
		AgentID:         agentID,
		ClientRequestID: optionalConversationRequestID(requestID),
		Title:           "New Conversation",
		CreatedAt:       time.Now(),
		UpdatedAt:       time.Now(),
	}

	if err := database.DB.Create(&conv).Error; err != nil {
		// A retried or concurrent mobile request can win the unique constraint
		// between the lookup and insert. Return that conversation instead of
		// creating another session or surfacing a false failure.
		if requestID != "" {
			var existing models.Conversation
			if lookupErr := database.DB.First(
				&existing,
				"user_id = ? AND client_request_id = ?",
				userID,
				requestID,
			).Error; lookupErr == nil {
				c.JSON(http.StatusOK, existing)
				return
			}
		}
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to create conversation"})
		return
	}

	c.JSON(http.StatusCreated, conv)
}

func optionalConversationRequestID(value string) *string {
	if value == "" {
		return nil
	}
	return &value
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
		Reasoning:      message.Reasoning,
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

	result := database.DB.Delete(&models.Conversation{}, "id = ? AND user_id = ?", id, userID)
	if result.Error != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to delete conversation"})
		return
	}
	if result.RowsAffected == 0 {
		c.JSON(http.StatusNotFound, gin.H{"error": "conversation not found"})
		return
	}
	if err := database.DB.Where("conversation_id = ? AND user_id = ?", id, userID).Delete(&models.Message{}).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "conversation deleted, but messages cleanup failed"})
		return
	}
	if err := database.DB.Where("conversation_id = ? AND user_id = ?", id, userID).Delete(&models.ConversationToolPolicy{}).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "conversation deleted, but tool policy cleanup failed"})
		return
	}

	c.JSON(http.StatusOK, gin.H{"status": "deleted"})
}
