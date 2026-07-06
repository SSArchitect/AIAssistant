package handlers

import (
	"bufio"
	"encoding/json"
	"errors"
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
	"gorm.io/gorm"
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
	ConversationID    string                  `json:"conversation_id" binding:"required"`
	UserID            string                  `json:"user_id,omitempty"`
	Query             string                  `json:"query" binding:"required"`
	Stream            bool                    `json:"stream"`
	ModelPreference   *string                 `json:"model_preference,omitempty"`
	AgentID           string                  `json:"agent_id,omitempty"`
	RoleID            string                  `json:"role_id,omitempty"`
	ModeIDs           []string                `json:"mode_ids,omitempty"`
	ModePrompts       []string                `json:"mode_prompts,omitempty"`
	ContextBlocks     []string                `json:"context_blocks,omitempty"`
	DriveContext      *bridge.DriveContext    `json:"drive_context,omitempty"`
	Attachments       []bridge.ChatAttachment `json:"attachments,omitempty"`
	AgentInput        map[string]interface{}  `json:"agent_input,omitempty"`
	Handoff           map[string]interface{}  `json:"handoff,omitempty"`
	Regenerate        bool                    `json:"regenerate,omitempty"`
	RunID             string                  `json:"run_id,omitempty"`
	SuppressUserMsg   bool                    `json:"suppress_user_message,omitempty"`
	SuppressFollowUps bool                    `json:"suppress_follow_ups,omitempty"`
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
	superChatAgentID       = "super_chat"
	pulseBackgroundAgentID = "pulse_background"
)

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
	disabledTools, err := disabledToolsForUser(req.UserID)
	if err != nil {
		slog.Warn("Failed to load user tool settings", "user_id", req.UserID, "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load tool settings"})
		return
	}

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

	if !req.Regenerate && !req.SuppressUserMsg {
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
		DriveContext:    req.DriveContext,
		Attachments:     req.Attachments,
		AgentInput:      req.AgentInput,
		Handoff:         req.Handoff,
		RunID:           req.RunID,
		DisabledTools:   disabledTools,
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

	assistantMsg := h.saveAssistantMessage(req.ConversationID, req.UserID, agentResp)
	if !req.SuppressFollowUps {
		h.generateFollowUpsAsync(req, assistantMsg, agentResp)
	}
	if !req.SuppressUserMsg {
		h.updateConversationTitle(conv, req.Query)
	}

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
		if !req.SuppressUserMsg {
			h.updateConversationTitle(conv, req.Query)
		}
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
		assistantMsg := h.saveAssistantMessage(req.ConversationID, req.UserID, &finalResp)
		if !req.SuppressFollowUps {
			h.generateFollowUpsAsync(req, assistantMsg, &finalResp)
		}
		if !req.SuppressUserMsg {
			h.updateConversationTitle(conv, req.Query)
		}
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
		if errorType == "cancelled" {
			return
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
		if !req.SuppressUserMsg {
			h.updateConversationTitle(conv, req.Query)
		}
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
		Artifacts:      run.Artifacts,
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

func compactTraceEvents(events []bridge.RunEvent) []bridge.RunEvent {
	if len(events) == 0 {
		return []bridge.RunEvent{}
	}
	compact := make([]bridge.RunEvent, 0, len(events))
	for _, event := range events {
		compact = append(compact, bridge.RunEvent{
			ID:         event.ID,
			RunID:      event.RunID,
			Type:       event.Type,
			Status:     event.Status,
			Title:      event.Title,
			StepID:     event.StepID,
			Payload:    compactTracePayload(event.Payload),
			DurationMS: event.DurationMS,
			CreatedAt:  event.CreatedAt,
		})
	}
	return compact
}

func compactTracePayload(payload map[string]interface{}) map[string]interface{} {
	if len(payload) == 0 {
		return map[string]interface{}{}
	}
	allowed := map[string]bool{
		"agent_id": true, "arguments": true, "aspect_ratio": true, "brief_preview": true,
		"budget_error_type": true, "budget_reason": true, "citation_count": true,
		"command_text": true, "count": true, "error_message": true,
		"error_type": true, "failed_tool_call_count": true, "final_prompt_char_count": true,
		"finalization_status": true, "image_count": true,
		"information_strategy": true, "max_failed_tool_calls": true, "max_model_rounds": true,
		"max_tool_calls": true, "message_count": true, "model": true, "node": true,
		"provider": true, "reason": true, "response_status": true, "result": true,
		"result_preview": true, "round": true, "skills_used": true, "source_agent_id": true,
		"status": true, "step": true, "steps": true, "streaming": true, "summary": true,
		"target_agent_id": true, "tool_calls": true, "tools_count": true, "total": true,
		"tool_call_count": true, "usage": true, "urls": true, "workflow_node": true,
	}
	compact := make(map[string]interface{})
	for key, value := range payload {
		if !allowed[key] {
			continue
		}
		compact[key] = compactTraceValue(key, value)
	}
	return compact
}

func compactTraceValue(key string, value interface{}) interface{} {
	switch key {
	case "arguments":
		return compactTraceObject(value, map[string]int{
			"query": 240, "task": 240, "url": 500, "sources": 120,
		})
	case "step":
		return compactTraceObject(value, map[string]int{
			"id": 80, "type": 80, "title": 160, "description": 260, "query": 240, "task": 240,
		})
	case "steps":
		return compactTraceObjects(value, 12, map[string]int{
			"id": 80, "type": 80, "title": 160, "description": 180, "query": 180, "task": 180,
		})
	case "tool_calls":
		return compactTraceObjects(value, 8, map[string]int{"id": 120, "name": 120})
	case "usage":
		return compactTraceObject(value, map[string]int{
			"input": 40, "output": 40, "total": 40, "input_tokens": 40, "output_tokens": 40, "total_tokens": 40,
		})
	case "urls":
		return compactTraceStringSlice(value, 4, 500)
	case "skills_used":
		return compactTraceStringSlice(value, 12, 80)
	case "result_preview":
		return compactToolResultPreview(value)
	case "brief_preview", "result", "summary", "error_message", "reason", "command_text":
		return truncateRunes(interfaceToString(value), 500)
	default:
		switch typed := value.(type) {
		case string:
			return truncateRunes(typed, 500)
		default:
			return typed
		}
	}
}

func compactTraceObject(value interface{}, allowed map[string]int) map[string]interface{} {
	source, ok := value.(map[string]interface{})
	if !ok {
		return map[string]interface{}{}
	}
	compact := make(map[string]interface{})
	for key, maxRunes := range allowed {
		raw, ok := source[key]
		if !ok {
			continue
		}
		if text, ok := raw.(string); ok {
			compact[key] = truncateRunes(text, maxRunes)
		} else {
			compact[key] = raw
		}
	}
	return compact
}

func compactTraceObjects(value interface{}, limit int, allowed map[string]int) []map[string]interface{} {
	items, ok := value.([]interface{})
	if !ok {
		return []map[string]interface{}{}
	}
	compact := make([]map[string]interface{}, 0, minTraceInt(len(items), limit))
	for _, item := range items {
		if len(compact) >= limit {
			break
		}
		compact = append(compact, compactTraceObject(item, allowed))
	}
	return compact
}

func compactTraceStringSlice(value interface{}, limit int, maxRunes int) []string {
	items, ok := value.([]interface{})
	if !ok {
		return []string{}
	}
	compact := make([]string, 0, minTraceInt(len(items), limit))
	for _, item := range items {
		if len(compact) >= limit {
			break
		}
		text := strings.TrimSpace(interfaceToString(item))
		if text == "" {
			continue
		}
		compact = append(compact, truncateRunes(text, maxRunes))
	}
	return compact
}

func compactToolResultPreview(value interface{}) interface{} {
	switch typed := value.(type) {
	case string:
		var decoded map[string]interface{}
		if err := json.Unmarshal([]byte(typed), &decoded); err != nil {
			return truncateRunes(typed, 800)
		}
		compact, _ := json.Marshal(compactToolPreviewPayload(decoded))
		return string(compact)
	case map[string]interface{}:
		return compactToolPreviewPayload(typed)
	default:
		return value
	}
}

func compactToolPreviewPayload(payload map[string]interface{}) map[string]interface{} {
	compact := make(map[string]interface{})
	for _, key := range []string{"success", "error"} {
		if value, ok := payload[key]; ok {
			if text, ok := value.(string); ok {
				compact[key] = truncateRunes(text, 300)
			} else {
				compact[key] = value
			}
		}
	}
	if displayText := strings.TrimSpace(interfaceToString(payload["display_text"])); displayText != "" {
		compact["display_text"] = truncateRunes(displayText, 500)
	}
	data, ok := payload["data"].(map[string]interface{})
	if !ok {
		return compact
	}
	compactData := make(map[string]interface{})
	if query := strings.TrimSpace(interfaceToString(data["query"])); query != "" {
		compactData["query"] = truncateRunes(query, 240)
	}
	if rawResults, ok := data["results"].([]interface{}); ok {
		results := make([]map[string]interface{}, 0, minTraceInt(len(rawResults), 5))
		for _, rawResult := range rawResults {
			if len(results) >= 5 {
				break
			}
			result, ok := rawResult.(map[string]interface{})
			if !ok {
				continue
			}
			results = append(results, compactTraceObject(result, map[string]int{
				"title": 180, "url": 500, "source": 80, "snippet": 220,
			}))
		}
		compactData["results"] = results
	}
	if len(compactData) > 0 {
		compact["data"] = compactData
	}
	return compact
}

func interfaceToString(value interface{}) string {
	switch typed := value.(type) {
	case string:
		return typed
	case nil:
		return ""
	default:
		return strings.TrimSpace(toJSONForSummary(typed))
	}
}

func toJSONForSummary(value interface{}) string {
	data, err := json.Marshal(value)
	if err != nil {
		return ""
	}
	return string(data)
}

func minTraceInt(a int, b int) int {
	if a < b {
		return a
	}
	return b
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

func (h *ChatHandler) saveAssistantMessage(conversationID string, userID string, agentResp *bridge.ChatResponse) *models.Message {
	skillsJSON, _ := json.Marshal(agentResp.SkillsUsed)
	citationsJSON, _ := json.Marshal(agentResp.Citations)
	artifactsJSON, _ := json.Marshal(agentResp.Artifacts)
	traceEventsJSON, _ := json.Marshal(agentResp.Events)
	traceSummaryJSON, _ := json.Marshal(compactTraceEvents(agentResp.Events))
	assistantMsg := models.Message{
		ConversationID: conversationID,
		UserID:         normalizedUserID(userID),
		Role:           "assistant",
		Content:        agentResp.Response,
		SkillsUsed:     string(skillsJSON),
		Citations:      string(citationsJSON),
		Artifacts:      string(artifactsJSON),
		ModelUsed:      agentResp.ModelUsed,
		Runtime:        agentResp.Runtime,
		RunID:          agentResp.RunID,
		TraceEvents:    string(traceEventsJSON),
		TraceSummary:   string(traceSummaryJSON),
		ErrorType:      agentResp.ErrorType,
		CreatedAt:      time.Now(),
	}
	if err := database.DB.Create(&assistantMsg).Error; err != nil {
		slog.Error("Failed to save assistant message", "error", err)
		return nil
	}
	h.persistTokenUsage(conversationID, userID, &assistantMsg, agentResp)
	return &assistantMsg
}

type tokenUsageBreakdown struct {
	InputTokens              int
	OutputTokens             int
	TotalTokens              int
	CachedInputTokens        int
	CacheCreationInputTokens int
	ImageCount               int
}

func (h *ChatHandler) persistTokenUsage(
	conversationID string,
	userID string,
	message *models.Message,
	agentResp *bridge.ChatResponse,
) {
	if message == nil || agentResp == nil {
		return
	}
	persistTokenUsageRecord(conversationID, userID, message.ID, "", message.CreatedAt, agentResp)
}

func persistTokenUsageRecord(
	conversationID string,
	userID string,
	messageID uint,
	agentID string,
	createdAt time.Time,
	agentResp *bridge.ChatResponse,
) {
	if agentResp == nil {
		return
	}
	usage := normalizeTokenUsage(agentResp.TokensUsed)
	if !usage.hasTrackedCost() {
		return
	}
	if strings.TrimSpace(agentID) == "" {
		agentID = usageAgentID(conversationID, agentResp)
	}
	if createdAt.IsZero() {
		createdAt = time.Now()
	}

	usageJSON, _ := json.Marshal(agentResp.TokensUsed)
	record := models.TokenUsage{
		UserID:                   normalizedUserID(userID),
		ConversationID:           conversationID,
		MessageID:                messageID,
		RunID:                    firstNonEmpty(agentResp.RunID, latestEventRunID(agentResp.Events)),
		AgentID:                  agentID,
		Runtime:                  agentResp.Runtime,
		ModelUsed:                agentResp.ModelUsed,
		InputTokens:              usage.InputTokens,
		OutputTokens:             usage.OutputTokens,
		TotalTokens:              usage.TotalTokens,
		CachedInputTokens:        usage.CachedInputTokens,
		CacheCreationInputTokens: usage.CacheCreationInputTokens,
		ImageCount:               usage.ImageCount,
		UsageJSON:                string(usageJSON),
		CreatedAt:                createdAt,
	}
	if err := database.DB.Create(&record).Error; err != nil {
		slog.Warn("Failed to persist token usage", "conversation_id", conversationID, "message_id", messageID, "run_id", agentResp.RunID, "agent_id", agentID, "error", err)
	}
}

func normalizeTokenUsage(tokens map[string]int) tokenUsageBreakdown {
	usage := tokenUsageBreakdown{
		InputTokens:              firstUsageValue(tokens, "input", "input_tokens", "prompt_tokens"),
		OutputTokens:             firstUsageValue(tokens, "output", "output_tokens", "completion_tokens"),
		CachedInputTokens:        firstUsageValue(tokens, "input_cached", "cached_input_tokens", "cache_read_input_tokens", "cache_read"),
		CacheCreationInputTokens: firstUsageValue(tokens, "input_cache_creation", "cache_creation_input_tokens", "cache_creation"),
		ImageCount:               firstUsageValue(tokens, "images", "image_count"),
	}
	usage.TotalTokens = firstUsageValue(tokens, "total", "total_tokens")
	if usage.TotalTokens == 0 {
		usage.TotalTokens = usage.InputTokens + usage.OutputTokens
	}
	return usage
}

func firstUsageValue(tokens map[string]int, keys ...string) int {
	for _, key := range keys {
		if value, ok := tokens[key]; ok {
			return value
		}
	}
	return 0
}

func (usage tokenUsageBreakdown) hasTrackedCost() bool {
	return usage.InputTokens > 0 ||
		usage.OutputTokens > 0 ||
		usage.TotalTokens > 0 ||
		usage.CachedInputTokens > 0 ||
		usage.CacheCreationInputTokens > 0 ||
		usage.ImageCount > 0
}

func usageAgentID(conversationID string, agentResp *bridge.ChatResponse) string {
	if agentResp != nil {
		if value := strings.TrimSpace(agentResp.AgentID); value != "" {
			return value
		}
		if value := inferStoredRunAgentID(agentResp.Events); value != "" {
			return value
		}
	}
	var conv models.Conversation
	if err := database.DB.First(&conv, "id = ?", conversationID).Error; err == nil && strings.TrimSpace(conv.AgentID) != "" {
		return conv.AgentID
	}
	return superChatAgentID
}

func latestEventRunID(events []bridge.RunEvent) string {
	for i := len(events) - 1; i >= 0; i-- {
		if strings.TrimSpace(events[i].RunID) != "" {
			return events[i].RunID
		}
	}
	return ""
}

func (h *ChatHandler) generateFollowUpsAsync(req ChatRequestBody, assistantMsg *models.Message, agentResp *bridge.ChatResponse) {
	if assistantMsg == nil || agentResp == nil {
		return
	}
	if strings.TrimSpace(agentResp.ErrorType) != "" || strings.TrimSpace(agentResp.Response) == "" {
		return
	}
	agentID := strings.TrimSpace(req.AgentID)
	if agentID != "" && agentID != superChatAgentID {
		return
	}
	userQuestion := strings.TrimSpace(req.Query)
	assistantAnswer := strings.TrimSpace(agentResp.Response)
	messageID := assistantMsg.ID
	userID := normalizedUserID(req.UserID)
	modelPreference := req.ModelPreference
	language := followUpLanguage(userQuestion + "\n" + assistantAnswer)

	go func() {
		var stored models.Message
		if err := database.DB.First(&stored, "id = ? AND user_id = ?", messageID, userID).Error; err != nil {
			slog.Warn("Follow-up generation skipped; assistant message not found", "message_id", messageID, "error", err)
			return
		}
		if strings.TrimSpace(stored.FollowUps) != "" {
			return
		}

		resp, err := h.agent.GenerateFollowUps(bridge.FollowUpRequest{
			UserQuestion:    userQuestion,
			AssistantAnswer: assistantAnswer,
			Language:        language,
			ModelPreference: modelPreference,
		})
		if err != nil {
			slog.Warn("Follow-up generation failed", "message_id", messageID, "error", err)
			return
		}
		questions := normalizeFollowUpQuestions(resp.Questions)
		if len(questions) == 0 {
			return
		}
		payload, err := json.Marshal(questions)
		if err != nil {
			slog.Warn("Failed to marshal follow-ups", "message_id", messageID, "error", err)
			return
		}
		if err := database.DB.Model(&models.Message{}).
			Where("id = ? AND user_id = ? AND (follow_ups = '' OR follow_ups IS NULL)", messageID, userID).
			Update("follow_ups", string(payload)).Error; err != nil {
			slog.Warn("Failed to persist follow-ups", "message_id", messageID, "error", err)
		}
	}()
}

func followUpLanguage(text string) string {
	chinese := 0
	total := 0
	for _, r := range text {
		if r == ' ' || r == '\n' || r == '\t' {
			continue
		}
		total++
		if r >= '\u4e00' && r <= '\u9fff' {
			chinese++
		}
	}
	if chinese >= 4 && total > 0 && float64(chinese)/float64(total) > 0.08 {
		return "zh"
	}
	return "en"
}

func normalizeFollowUpQuestions(values []string) []string {
	questions := make([]string, 0, 3)
	seen := map[string]bool{}
	for _, value := range values {
		question := strings.Join(strings.Fields(value), " ")
		if question == "" {
			continue
		}
		key := strings.ToLower(question)
		if seen[key] {
			continue
		}
		seen[key] = true
		questions = append(questions, question)
		if len(questions) >= 3 {
			break
		}
	}
	return questions
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
	memories, err := h.agent.ListRoleMemories(
		c.Param("id"),
		requestUserID(c),
		c.Query("kind"),
		c.Query("agent_id"),
		c.Query("include_inactive") == "true",
	)
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

func (h *ChatHandler) UpdateRoleMemory(c *gin.Context) {
	var req bridge.MemoryWriteRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}
	req.UserID = requestUserIDWithBody(c, req.UserID)
	if req.Content != "" {
		req.Content = strings.TrimSpace(req.Content)
	}
	if req.Metadata == nil {
		req.Metadata = map[string]interface{}{}
	}
	req.Metadata["entrypoint"] = "super_chat_developer_memory"

	memory, err := h.agent.UpdateRoleMemory(c.Param("id"), c.Param("memory_id"), req)
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
	userID := requestUserID(c)
	tools, err := h.agent.ListSkills()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "agent error: " + err.Error()})
		return
	}
	settings, err := loadUserSettings(userID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load tool settings"})
		return
	}
	applyToolUserSettings(tools, settings)
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
	runID := c.Param("id")
	run, err := h.agent.GetRun(runID)
	if err == nil {
		if normalizedUserID(run.UserID) != userID {
			c.JSON(http.StatusNotFound, gin.H{"error": "run not found"})
			return
		}
		c.JSON(http.StatusOK, run)
		return
	}

	storedRun, storedErr := storedRunRecord(runID, userID)
	if storedErr == nil {
		c.JSON(http.StatusOK, storedRun)
		return
	}
	if errors.Is(storedErr, gorm.ErrRecordNotFound) && strings.Contains(err.Error(), "status 404") {
		c.JSON(http.StatusNotFound, gin.H{"error": "run not found"})
		return
	}

	c.JSON(http.StatusInternalServerError, gin.H{"error": "agent error: " + err.Error()})
}

func (h *ChatHandler) CancelRun(c *gin.Context) {
	userID := requestUserID(c)
	runID := strings.TrimSpace(c.Param("id"))
	if runID == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "run id is required"})
		return
	}
	if run, err := h.agent.GetRun(runID); err == nil && normalizedUserID(run.UserID) != userID {
		c.JSON(http.StatusNotFound, gin.H{"error": "run not found"})
		return
	}
	if err := h.agent.CancelRun(runID); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "agent error: " + err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"status": "cancelling", "run_id": runID})
}

func storedRunRecord(runID string, userID string) (*bridge.RunRecord, error) {
	var message models.Message
	if err := database.DB.
		Where("run_id = ? AND user_id = ? AND role = ?", runID, normalizedUserID(userID), "assistant").
		Order(messageReverseChronologicalOrder).
		First(&message).Error; err != nil {
		return nil, err
	}

	events := []bridge.RunEvent{}
	if strings.TrimSpace(message.TraceEvents) != "" {
		if err := json.Unmarshal([]byte(message.TraceEvents), &events); err != nil {
			return nil, err
		}
	}
	if events == nil {
		events = []bridge.RunEvent{}
	}
	skills := []string{}
	if strings.TrimSpace(message.SkillsUsed) != "" {
		_ = json.Unmarshal([]byte(message.SkillsUsed), &skills)
	}
	if skills == nil {
		skills = []string{}
	}
	artifacts := []bridge.ChatArtifact{}
	if strings.TrimSpace(message.Artifacts) != "" {
		_ = json.Unmarshal([]byte(message.Artifacts), &artifacts)
	}
	if artifacts == nil {
		artifacts = []bridge.ChatArtifact{}
	}

	input := storedRunInput(message)
	completedAt := firstNonEmpty(storedRunCompletedAt(events), message.CreatedAt.Format(time.RFC3339))
	errorType := storedRunErrorType(message, events)
	errorMessage := storedRunErrorMessage(message, events)
	return &bridge.RunRecord{
		RunID:          runID,
		ConversationID: message.ConversationID,
		UserID:         message.UserID,
		AgentID:        storedRunAgentID(message.ConversationID, events),
		Runtime:        message.Runtime,
		Status:         storedRunStatus(events, message.ErrorType),
		Input:          input,
		Output:         message.Content,
		ModelUsed:      message.ModelUsed,
		TokensUsed:     storedRunTokensUsed(message.ID),
		SkillsUsed:     skills,
		Artifacts:      artifacts,
		ErrorType:      optionalString(errorType),
		ErrorMessage:   optionalString(errorMessage),
		StartedAt:      firstNonEmpty(storedRunStartedAt(events), message.CreatedAt.Format(time.RFC3339)),
		CompletedAt:    &completedAt,
		Events:         events,
	}, nil
}

func storedRunTokensUsed(messageID uint) map[string]int {
	var usage models.TokenUsage
	if err := database.DB.Where("message_id = ?", messageID).First(&usage).Error; err != nil {
		return map[string]int{}
	}
	tokens := map[string]int{}
	if strings.TrimSpace(usage.UsageJSON) != "" {
		_ = json.Unmarshal([]byte(usage.UsageJSON), &tokens)
	}
	if tokens == nil {
		tokens = map[string]int{}
	}
	if len(tokens) == 0 {
		tokens["input"] = usage.InputTokens
		tokens["output"] = usage.OutputTokens
		tokens["total"] = usage.TotalTokens
	}
	return tokens
}

func storedRunInput(message models.Message) string {
	var userMessage models.Message
	err := database.DB.
		Where("conversation_id = ? AND user_id = ? AND role = ? AND id < ?", message.ConversationID, message.UserID, "user", message.ID).
		Order(messageReverseChronologicalOrder).
		First(&userMessage).Error
	if err != nil {
		return ""
	}
	return userMessage.Content
}

func storedRunAgentID(conversationID string, events []bridge.RunEvent) string {
	if agentID := inferStoredRunAgentID(events); agentID != "" {
		return agentID
	}
	var conv models.Conversation
	if err := database.DB.First(&conv, "id = ?", conversationID).Error; err == nil && strings.TrimSpace(conv.AgentID) != "" {
		return conv.AgentID
	}
	return "super_chat"
}

func inferStoredRunAgentID(events []bridge.RunEvent) string {
	for _, event := range events {
		if event.Type != "run.started" && event.Type != "agent.delegated" && event.Type != "agent.command.routed" {
			continue
		}
		for _, key := range []string{"agent_id", "target_agent_id"} {
			if value, ok := event.Payload[key].(string); ok && strings.TrimSpace(value) != "" {
				return value
			}
		}
	}
	return ""
}

func storedRunStatus(events []bridge.RunEvent, errorType string) string {
	if strings.TrimSpace(errorType) != "" {
		return "failed"
	}
	status := "completed"
	hasRunTerminalEvent := false
	for _, event := range events {
		if event.Type == "run.cancelled" {
			return "cancelled"
		}
		if event.Type == "run.failed" {
			return "failed"
		}
		if event.Type == "run.partial" {
			hasRunTerminalEvent = true
			status = "partial"
			continue
		}
		if event.Type == "run.completed" {
			hasRunTerminalEvent = true
			if status != "partial" {
				status = "completed"
			}
		}
	}
	if hasRunTerminalEvent {
		return status
	}
	for _, event := range events {
		if normalizeTraceStatus(event.Status) == "cancelled" {
			return "cancelled"
		}
		if normalizeTraceStatus(event.Status) == "error" {
			return "failed"
		}
		if normalizeTraceStatus(event.Status) == "partial" {
			status = "partial"
		}
	}
	return status
}

func storedRunStartedAt(events []bridge.RunEvent) string {
	for _, event := range events {
		if strings.TrimSpace(event.CreatedAt) != "" {
			return event.CreatedAt
		}
	}
	return ""
}

func storedRunCompletedAt(events []bridge.RunEvent) string {
	for i := len(events) - 1; i >= 0; i-- {
		if strings.TrimSpace(events[i].CreatedAt) != "" {
			return events[i].CreatedAt
		}
	}
	return ""
}

func storedRunErrorType(message models.Message, events []bridge.RunEvent) string {
	if strings.TrimSpace(message.ErrorType) != "" {
		return message.ErrorType
	}
	for _, event := range events {
		if value, ok := event.Payload["error_type"].(string); ok && strings.TrimSpace(value) != "" {
			return value
		}
	}
	return ""
}

func storedRunErrorMessage(message models.Message, events []bridge.RunEvent) string {
	if storedRunStatus(events, message.ErrorType) == "failed" && strings.TrimSpace(message.Content) != "" {
		return message.Content
	}
	for _, event := range events {
		if value, ok := event.Payload["error_message"].(string); ok && strings.TrimSpace(value) != "" {
			return value
		}
	}
	return ""
}

func optionalString(value string) *string {
	if strings.TrimSpace(value) == "" {
		return nil
	}
	return &value
}

func normalizeTraceStatus(value string) string {
	return strings.ToLower(strings.TrimSpace(value))
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
