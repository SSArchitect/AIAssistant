package handlers

import (
	"bufio"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
)

type ChatHandler struct {
	agent  *bridge.AgentClient
	syncer *ConfigSyncer
}

func NewChatHandler(agent *bridge.AgentClient, syncers ...*ConfigSyncer) *ChatHandler {
	var syncer *ConfigSyncer
	if len(syncers) > 0 {
		syncer = syncers[0]
	}
	return &ChatHandler{agent: agent, syncer: syncer}
}

type ChatRequestBody struct {
	ConversationID  string                  `json:"conversation_id" binding:"required"`
	UserID          string                  `json:"user_id,omitempty"`
	Query           string                  `json:"query" binding:"required"`
	Stream          bool                    `json:"stream"`
	ModelPreference *string                 `json:"model_preference,omitempty"`
	AgentID         string                  `json:"agent_id,omitempty"`
	RoleID          string                  `json:"role_id,omitempty"`
	ModeIDs         []string                `json:"mode_ids,omitempty"`
	ModePrompts     []string                `json:"mode_prompts,omitempty"`
	ContextBlocks   []string                `json:"context_blocks,omitempty"`
	Attachments     []bridge.ChatAttachment `json:"attachments,omitempty"`
	AgentInput      map[string]interface{}  `json:"agent_input,omitempty"`
	Handoff         map[string]interface{}  `json:"handoff,omitempty"`
	Regenerate      bool                    `json:"regenerate,omitempty"`
}

type streamErrorPayload struct {
	RunID     string `json:"run_id"`
	Error     string `json:"error"`
	ErrorType string `json:"error_type"`
}

type streamRunPayload struct {
	RunID string `json:"run_id"`
}

const (
	conversationContextMessageLimit    = 30
	conversationContextMaxMessageRunes = 1800
	conversationContextMaxBlockBytes   = 24000
)

func (h *ChatHandler) Chat(c *gin.Context) {
	var req ChatRequestBody
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}
	req.UserID = requestUserIDWithBody(c, req.UserID)

	// Ensure conversation exists
	var conv models.Conversation
	if err := database.DB.First(&conv, "id = ? AND user_id = ?", req.ConversationID, req.UserID).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "conversation not found"})
		return
	}

	contextBlocks := h.persistedConversationContext(req.ConversationID, req.UserID)
	if req.Regenerate {
		contextBlocks = append(contextBlocks, "Regeneration request: the user clicked the refresh button for the previous assistant answer. Answer the current query again from scratch and provide a fresh response.")
	}
	contextBlocks = append(contextBlocks, req.ContextBlocks...)

	if !req.Regenerate {
		// Save user message
		userMsg := models.Message{
			ConversationID: req.ConversationID,
			UserID:         req.UserID,
			Role:           "user",
			Content:        req.Query,
			CreatedAt:      time.Now(),
		}
		if err := database.DB.Create(&userMsg).Error; err != nil {
			slog.Error("Failed to save user message", "error", err)
		}
	}

	agentReq := bridge.ChatRequest{
		ConversationID:  req.ConversationID,
		UserID:          req.UserID,
		Message:         req.Query,
		Stream:          req.Stream,
		ModelPreference: req.ModelPreference,
		AgentID:         req.AgentID,
		RoleID:          req.RoleID,
		ModeIDs:         req.ModeIDs,
		ModePrompts:     req.ModePrompts,
		ContextBlocks:   contextBlocks,
		Attachments:     req.Attachments,
		AgentInput:      req.AgentInput,
		Handoff:         req.Handoff,
	}

	if !h.syncConfigToAgent(c) {
		return
	}

	if req.Stream {
		h.streamChat(c, conv, req, agentReq)
		return
	}

	// Call agent
	agentResp, err := h.agent.Chat(agentReq)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "agent error: " + err.Error()})
		return
	}

	h.saveAssistantMessage(req.ConversationID, req.UserID, agentResp)
	h.updateConversationTitle(conv, req.Query)

	c.JSON(http.StatusOK, agentResp)
}

func (h *ChatHandler) streamChat(
	c *gin.Context,
	conv models.Conversation,
	req ChatRequestBody,
	agentReq bridge.ChatRequest,
) {
	resp, err := h.agent.ChatStream(agentReq)
	if err != nil {
		h.saveAssistantMessage(req.ConversationID, req.UserID, &bridge.ChatResponse{
			ConversationID: req.ConversationID,
			Response:       err.Error(),
			ErrorType:      "stream_error",
			AgentID:        req.AgentID,
			RoleID:         req.RoleID,
		})
		h.updateConversationTitle(conv, req.Query)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "agent error: " + err.Error()})
		return
	}
	defer resp.Body.Close()

	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	c.Header("X-Accel-Buffering", "no")
	c.Status(http.StatusOK)

	flusher, ok := c.Writer.(http.Flusher)
	if !ok {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "streaming unsupported"})
		return
	}

	var finalResp bridge.ChatResponse
	hasFinalResp := false
	var streamErr streamErrorPayload
	streamEvents := make([]bridge.RunEvent, 0)
	traceErrorType := ""
	traceErrorMessage := ""
	latestRunID := ""
	currentEvent := ""
	clientConnected := true
	reader := bufio.NewReader(resp.Body)

	for {
		line, readErr := reader.ReadString('\n')
		if len(line) > 0 {
			trimmed := strings.TrimSpace(line)
			if strings.HasPrefix(trimmed, "event:") {
				currentEvent = strings.TrimSpace(strings.TrimPrefix(trimmed, "event:"))
			} else if strings.HasPrefix(trimmed, "data:") {
				payload := strings.TrimSpace(strings.TrimPrefix(trimmed, "data:"))
				switch currentEvent {
				case "meta", "done":
					var runPayload streamRunPayload
					if err := json.Unmarshal([]byte(payload), &runPayload); err == nil && runPayload.RunID != "" {
						latestRunID = runPayload.RunID
					}
				case "response":
					if err := json.Unmarshal([]byte(payload), &finalResp); err == nil {
						hasFinalResp = true
						if finalResp.RunID != "" {
							latestRunID = finalResp.RunID
						}
					}
				case "trace":
					var event bridge.RunEvent
					if err := json.Unmarshal([]byte(payload), &event); err == nil {
						streamEvents = append(streamEvents, event)
						if event.RunID != "" {
							latestRunID = event.RunID
						}
						if event.Type == "run.failed" || event.Status == "error" {
							if errorType, ok := event.Payload["error_type"].(string); ok && errorType != "" {
								traceErrorType = errorType
							}
							if errorMessage, ok := event.Payload["error_message"].(string); ok && errorMessage != "" {
								traceErrorMessage = errorMessage
							}
						}
					}
				case "error":
					if err := json.Unmarshal([]byte(payload), &streamErr); err != nil {
						streamErr.Error = payload
					}
					if streamErr.RunID != "" {
						latestRunID = streamErr.RunID
					}
				}
			}

			if clientConnected {
				if _, err := c.Writer.Write([]byte(line)); err != nil {
					clientConnected = false
					slog.Warn("Client stream write failed; continuing agent stream for persistence", "error", err)
				} else {
					flusher.Flush()
				}
			}
		}

		if readErr != nil {
			if readErr != io.EOF {
				slog.Warn("Agent stream read failed", "error", readErr)
			}
			break
		}
	}

	if !hasFinalResp && streamErr.Error == "" && traceErrorMessage == "" {
		if recoveredResp := h.recoverCompletedRunResponse(latestRunID, req); recoveredResp != nil {
			finalResp = *recoveredResp
			hasFinalResp = true
		}
	}

	if hasFinalResp {
		if len(finalResp.Events) == 0 && len(streamEvents) > 0 {
			finalResp.Events = streamEvents
		}
		h.saveAssistantMessage(req.ConversationID, req.UserID, &finalResp)
		h.updateConversationTitle(conv, req.Query)
	} else if streamErr.Error != "" || traceErrorMessage != "" {
		errorMessage := streamErr.Error
		if errorMessage == "" {
			errorMessage = traceErrorMessage
		}
		errorType := streamErr.ErrorType
		if errorType == "" {
			errorType = traceErrorType
		}
		if errorType == "" {
			errorType = "stream_error"
		}
		h.saveAssistantMessage(req.ConversationID, req.UserID, &bridge.ChatResponse{
			ConversationID: req.ConversationID,
			Response:       errorMessage,
			ErrorType:      errorType,
			AgentID:        req.AgentID,
			RoleID:         req.RoleID,
			RunID:          firstNonEmpty(streamErr.RunID, latestRunID),
			Events:         streamEvents,
		})
		h.updateConversationTitle(conv, req.Query)
	}
}

func (h *ChatHandler) recoverCompletedRunResponse(runID string, req ChatRequestBody) *bridge.ChatResponse {
	if runID == "" {
		return nil
	}

	run, err := h.agent.GetRun(runID)
	if err != nil {
		slog.Warn("Failed to recover completed stream run", "run_id", runID, "error", err)
		return nil
	}
	if run.Status != "completed" || strings.TrimSpace(run.Output) == "" {
		return nil
	}

	conversationID := run.ConversationID
	if conversationID == "" {
		conversationID = req.ConversationID
	}
	return &bridge.ChatResponse{
		ConversationID: conversationID,
		Response:       run.Output,
		SkillsUsed:     run.SkillsUsed,
		Citations:      nil,
		ModelUsed:      run.ModelUsed,
		TokensUsed:     run.TokensUsed,
		AgentID:        run.AgentID,
		Runtime:        run.Runtime,
		RunID:          run.RunID,
		Events:         run.Events,
	}
}

func (h *ChatHandler) persistedConversationContext(conversationID string, userID string) []string {
	var messages []models.Message
	err := database.DB.
		Where("conversation_id = ? AND user_id = ?", conversationID, normalizedUserID(userID)).
		Order(messageReverseChronologicalOrder).
		Limit(conversationContextMessageLimit).
		Find(&messages).Error
	if err != nil {
		slog.Warn("Failed to load persisted conversation context", "conversation_id", conversationID, "error", err)
		return nil
	}
	if len(messages) == 0 {
		return nil
	}

	for i, j := 0, len(messages)-1; i < j; i, j = i+1, j-1 {
		messages[i], messages[j] = messages[j], messages[i]
	}

	var builder strings.Builder
	builder.WriteString("Persisted conversation history (recent messages from this conversation, oldest to newest):")
	for _, message := range messages {
		role := strings.TrimSpace(message.Role)
		if role != "user" && role != "assistant" {
			continue
		}
		content := strings.TrimSpace(message.Content)
		if content == "" {
			continue
		}
		content = truncateRunes(content, conversationContextMaxMessageRunes)
		line := "\n" + role + ": " + content
		if builder.Len()+len(line) > conversationContextMaxBlockBytes {
			break
		}
		builder.WriteString(line)
	}

	block := builder.String()
	if !strings.Contains(block, "\n") {
		return nil
	}
	return []string{block}
}

func truncateRunes(value string, maxRunes int) string {
	runes := []rune(value)
	if len(runes) <= maxRunes {
		return value
	}
	return string(runes[:maxRunes]) + "..."
}

func (h *ChatHandler) syncConfigToAgent(c *gin.Context) bool {
	if h.syncer == nil {
		return true
	}
	if err := h.syncer.SyncToAgent(); err != nil {
		slog.Warn("Failed to sync config to agent", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to sync config: " + err.Error()})
		return false
	}
	return true
}

func (h *ChatHandler) saveAssistantMessage(conversationID string, userID string, agentResp *bridge.ChatResponse) {
	skillsJSON, _ := json.Marshal(agentResp.SkillsUsed)
	citationsJSON, _ := json.Marshal(agentResp.Citations)
	traceEventsJSON, _ := json.Marshal(agentResp.Events)
	assistantMsg := models.Message{
		ConversationID: conversationID,
		UserID:         normalizedUserID(userID),
		Role:           "assistant",
		Content:        agentResp.Response,
		SkillsUsed:     string(skillsJSON),
		Citations:      string(citationsJSON),
		ModelUsed:      agentResp.ModelUsed,
		Runtime:        agentResp.Runtime,
		RunID:          agentResp.RunID,
		TraceEvents:    string(traceEventsJSON),
		ErrorType:      agentResp.ErrorType,
		CreatedAt:      time.Now(),
	}
	if err := database.DB.Create(&assistantMsg).Error; err != nil {
		slog.Error("Failed to save assistant message", "error", err)
	}
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return value
		}
	}
	return ""
}

func (h *ChatHandler) updateConversationTitle(conv models.Conversation, query string) {
	if conv.Title != "New Conversation" && conv.Title != "" {
		return
	}
	title := query
	if len(title) > 50 {
		title = title[:50] + "..."
	}
	if err := database.DB.Model(&conv).Update("title", title).Error; err != nil {
		slog.Error("Failed to update conversation title", "error", err)
	}
}

func (h *ChatHandler) ListAgents(c *gin.Context) {
	agents, err := h.agent.ListAgents()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "agent error: " + err.Error()})
		return
	}
	c.JSON(http.StatusOK, agents)
}

func (h *ChatHandler) ListRoles(c *gin.Context) {
	roles, err := h.agent.ListRoles(requestUserID(c))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "agent error: " + err.Error()})
		return
	}
	c.JSON(http.StatusOK, roles)
}

func (h *ChatHandler) CreateRole(c *gin.Context) {
	var req bridge.RoleWriteRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}
	req.UserID = requestUserIDWithBody(c, req.UserID)
	role, err := h.agent.CreateRole(req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "agent error: " + err.Error()})
		return
	}
	c.JSON(http.StatusOK, role)
}

func (h *ChatHandler) UpdateRole(c *gin.Context) {
	var req bridge.RoleWriteRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}
	req.UserID = requestUserIDWithBody(c, req.UserID)
	role, err := h.agent.UpdateRole(c.Param("id"), req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "agent error: " + err.Error()})
		return
	}
	c.JSON(http.StatusOK, role)
}

func (h *ChatHandler) DeleteRole(c *gin.Context) {
	if err := h.agent.DeleteRole(c.Param("id"), requestUserID(c)); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "agent error: " + err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"status": "ok"})
}

func (h *ChatHandler) ListRoleMemories(c *gin.Context) {
	memories, err := h.agent.ListRoleMemories(c.Param("id"), requestUserID(c), c.Query("kind"), c.Query("agent_id"))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "agent error: " + err.Error()})
		return
	}
	c.JSON(http.StatusOK, memories)
}

func (h *ChatHandler) CreateRoleMemory(c *gin.Context) {
	var req bridge.MemoryWriteRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}
	req.Content = strings.TrimSpace(req.Content)
	if req.Content == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "memory content is required"})
		return
	}
	req.UserID = requestUserIDWithBody(c, req.UserID)
	req.Kind = strings.TrimSpace(req.Kind)
	if req.Kind == "" {
		req.Kind = "role"
	}
	req.Source = strings.TrimSpace(req.Source)
	if req.Source == "" {
		req.Source = "manual"
	}
	if req.Metadata == nil {
		req.Metadata = map[string]interface{}{}
	}
	req.Metadata["entrypoint"] = "super_chat_role_memory"

	memory, err := h.agent.CreateRoleMemory(c.Param("id"), req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "agent error: " + err.Error()})
		return
	}
	c.JSON(http.StatusOK, memory)
}

func (h *ChatHandler) DeleteRoleMemory(c *gin.Context) {
	if err := h.agent.DeleteRoleMemory(c.Param("id"), c.Param("memory_id"), requestUserID(c)); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "agent error: " + err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"status": "ok"})
}

func (h *ChatHandler) ListTools(c *gin.Context) {
	tools, err := h.agent.ListSkills()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "agent error: " + err.Error()})
		return
	}
	c.JSON(http.StatusOK, tools)
}

func (h *ChatHandler) ListRuns(c *gin.Context) {
	limit := 50
	if rawLimit := c.Query("limit"); rawLimit != "" {
		parsed, err := strconv.Atoi(rawLimit)
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "invalid limit"})
			return
		}
		limit = parsed
	}

	userID := requestUserID(c)
	runs, err := h.agent.ListRuns(c.Query("conversation_id"), userID, limit)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "agent error: " + err.Error()})
		return
	}
	c.JSON(http.StatusOK, runs)
}

func (h *ChatHandler) GetRun(c *gin.Context) {
	userID := requestUserID(c)
	run, err := h.agent.GetRun(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "agent error: " + err.Error()})
		return
	}
	if normalizedUserID(run.UserID) != userID {
		c.JSON(http.StatusNotFound, gin.H{"error": "run not found"})
		return
	}
	c.JSON(http.StatusOK, run)
}

func (h *ChatHandler) GenerateImage(c *gin.Context) {
	var req bridge.AIGCImageRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}

	if !h.syncConfigToAgent(c) {
		return
	}

	resp, err := h.agent.GenerateImage(req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "agent error: " + err.Error()})
		return
	}

	c.JSON(http.StatusOK, resp)
}
