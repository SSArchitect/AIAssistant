package handlers

import (
	"encoding/json"
	"errors"
	"net/http"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"gorm.io/gorm"
)

const (
	todoStatusOpen       = "open"
	todoStatusDone       = "done"
	todoStatusArchived   = "archived"
	todoPriorityLow      = "low"
	todoPriorityNormal   = "normal"
	todoPriorityHigh     = "high"
	todoSourceManual     = "manual"
	todoSourceSuggestion = "suggestion"
	todoRepeatOnce       = "once"
	todoRepeatDaily      = "daily"
	todoRepeatWorkdays   = "workdays"

	todoSuggestionPending   = "pending"
	todoSuggestionAccepted  = "accepted"
	todoSuggestionDismissed = "dismissed"

	todoMinSuggestionConfidence = 82
)

var todoLocalLocation = time.FixedZone("Asia/Shanghai", 8*60*60)

type TodoHandler struct{}

func NewTodoHandler() *TodoHandler {
	return &TodoHandler{}
}

type todoWriteRequest struct {
	UserID               string   `json:"user_id,omitempty"`
	Title                string   `json:"title,omitempty"`
	Notes                string   `json:"notes,omitempty"`
	StartDate            string   `json:"start_date,omitempty"`
	DueDate              string   `json:"due_date,omitempty"`
	EndDate              string   `json:"end_date,omitempty"`
	DueTime              string   `json:"due_time,omitempty"`
	Timezone             string   `json:"timezone,omitempty"`
	RepeatRule           string   `json:"repeat_rule,omitempty"`
	Priority             string   `json:"priority,omitempty"`
	Tags                 []string `json:"tags,omitempty"`
	Source               string   `json:"source,omitempty"`
	OriginConversationID string   `json:"origin_conversation_id,omitempty"`
	OriginMessageID      uint     `json:"origin_message_id,omitempty"`
	OriginRunID          string   `json:"origin_run_id,omitempty"`
}

type todoPatchRequest struct {
	Title      *string   `json:"title,omitempty"`
	Notes      *string   `json:"notes,omitempty"`
	StartDate  *string   `json:"start_date,omitempty"`
	DueDate    *string   `json:"due_date,omitempty"`
	EndDate    *string   `json:"end_date,omitempty"`
	DueTime    *string   `json:"due_time,omitempty"`
	Timezone   *string   `json:"timezone,omitempty"`
	RepeatRule *string   `json:"repeat_rule,omitempty"`
	Priority   *string   `json:"priority,omitempty"`
	Tags       *[]string `json:"tags,omitempty"`
	Status     *string   `json:"status,omitempty"`
}

type todoSuggestionRefreshRequest struct {
	UserID string `json:"user_id,omitempty"`
	Limit  int    `json:"limit,omitempty"`
}

type todoResponse struct {
	ID                   string     `json:"id"`
	UserID               string     `json:"user_id"`
	Title                string     `json:"title"`
	Notes                string     `json:"notes,omitempty"`
	Status               string     `json:"status"`
	StartDate            string     `json:"start_date,omitempty"`
	DueDate              string     `json:"due_date,omitempty"`
	EndDate              string     `json:"end_date,omitempty"`
	DueTime              string     `json:"due_time,omitempty"`
	Timezone             string     `json:"timezone,omitempty"`
	RepeatRule           string     `json:"repeat_rule"`
	Priority             string     `json:"priority"`
	Tags                 []string   `json:"tags"`
	Source               string     `json:"source"`
	OriginConversationID string     `json:"origin_conversation_id,omitempty"`
	OriginMessageID      uint       `json:"origin_message_id,omitempty"`
	OriginRunID          string     `json:"origin_run_id,omitempty"`
	CreatedAt            time.Time  `json:"created_at"`
	UpdatedAt            time.Time  `json:"updated_at"`
	CompletedAt          *time.Time `json:"completed_at,omitempty"`
}

type todoSuggestionResponse struct {
	ID                   string                 `json:"id"`
	UserID               string                 `json:"user_id"`
	Title                string                 `json:"title"`
	Notes                string                 `json:"notes,omitempty"`
	ProposedStartDate    string                 `json:"proposed_start_date,omitempty"`
	ProposedDueDate      string                 `json:"proposed_due_date,omitempty"`
	Priority             string                 `json:"priority"`
	Confidence           int                    `json:"confidence"`
	Reason               string                 `json:"reason,omitempty"`
	Evidence             map[string]interface{} `json:"evidence,omitempty"`
	Source               string                 `json:"source"`
	State                string                 `json:"state"`
	AcceptedTodoID       string                 `json:"accepted_todo_id,omitempty"`
	OriginConversationID string                 `json:"origin_conversation_id,omitempty"`
	OriginMessageID      uint                   `json:"origin_message_id,omitempty"`
	OriginRunID          string                 `json:"origin_run_id,omitempty"`
	CreatedAt            time.Time              `json:"created_at"`
	UpdatedAt            time.Time              `json:"updated_at"`
	ResolvedAt           *time.Time             `json:"resolved_at,omitempty"`
}

type todoSuggestionCandidate struct {
	Title                string
	Notes                string
	ProposedStartDate    string
	ProposedDueDate      string
	Priority             string
	Confidence           int
	Reason               string
	Evidence             map[string]interface{}
	OriginConversationID string
	OriginMessageID      uint
	OriginRunID          string
}

func (h *TodoHandler) List(c *gin.Context) {
	userID := requestUserID(c)
	scope := strings.ToLower(strings.TrimSpace(c.DefaultQuery("scope", "today")))
	date := requestedTodoDate(c.Query("date"))
	rangeStart, rangeEnd := requestedTodoRange(c.Query("start"), c.Query("end"), date)
	includeCompleted := parseTodoBool(c.Query("include_completed"))

	items, err := loadTodos(userID, scope, date, rangeStart, rangeEnd, includeCompleted)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load todos"})
		return
	}
	counts, err := todoCounts(userID, date)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load todo counts"})
		return
	}
	c.JSON(http.StatusOK, gin.H{
		"items":  todoResponses(items),
		"counts": counts,
		"scope":  scope,
		"date":   date,
		"start":  rangeStart,
		"end":    rangeEnd,
	})
}

func (h *TodoHandler) Create(c *gin.Context) {
	var req todoWriteRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}
	userID := requestUserIDWithBody(c, req.UserID)
	item, err := todoFromCreateRequest(userID, req)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	if err := database.DB.Create(&item).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to create todo"})
		return
	}
	c.JSON(http.StatusCreated, gin.H{"todo": todoResponseFromModel(item)})
}

func (h *TodoHandler) Update(c *gin.Context) {
	userID := requestUserID(c)
	var item models.TodoItem
	if err := database.DB.First(&item, "id = ? AND user_id = ?", c.Param("id"), userID).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "todo not found"})
		return
	}

	var req todoPatchRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}
	if err := applyTodoPatch(&item, req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	item.UpdatedAt = time.Now()
	if err := saveTodoItem(&item); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to update todo"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"todo": todoResponseFromModel(item)})
}

func (h *TodoHandler) Complete(c *gin.Context) {
	userID := requestUserID(c)
	var item models.TodoItem
	if err := database.DB.First(&item, "id = ? AND user_id = ?", c.Param("id"), userID).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "todo not found"})
		return
	}
	now := time.Now()
	item.Status = todoStatusDone
	item.CompletedAt = &now
	item.UpdatedAt = now
	if err := saveTodoItem(&item); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to complete todo"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"todo": todoResponseFromModel(item)})
}

func (h *TodoHandler) Delete(c *gin.Context) {
	userID := requestUserID(c)
	result := database.DB.Delete(&models.TodoItem{}, "id = ? AND user_id = ?", c.Param("id"), userID)
	if result.Error != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to delete todo"})
		return
	}
	if result.RowsAffected == 0 {
		c.JSON(http.StatusNotFound, gin.H{"error": "todo not found"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"status": "deleted"})
}

func (h *TodoHandler) ListSuggestions(c *gin.Context) {
	userID := requestUserID(c)
	state := normalizeTodoSuggestionState(c.DefaultQuery("state", todoSuggestionPending))
	suggestions, err := loadTodoSuggestions(userID, state, 20)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load todo suggestions"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"suggestions": todoSuggestionResponses(suggestions)})
}

func (h *TodoHandler) RefreshSuggestions(c *gin.Context) {
	var req todoSuggestionRefreshRequest
	_ = c.ShouldBindJSON(&req)
	userID := requestUserIDWithBody(c, req.UserID)
	limit := req.Limit
	if limit <= 0 || limit > 10 {
		limit = 6
	}
	if _, err := h.generateSuggestions(userID, limit); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to refresh todo suggestions"})
		return
	}
	suggestions, err := loadTodoSuggestions(userID, todoSuggestionPending, 20)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load todo suggestions"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"suggestions": todoSuggestionResponses(suggestions)})
}

func (h *TodoHandler) AcceptSuggestion(c *gin.Context) {
	userID := requestUserID(c)
	var suggestion models.TodoSuggestion
	if err := database.DB.First(&suggestion, "id = ? AND user_id = ?", c.Param("id"), userID).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "todo suggestion not found"})
		return
	}
	if suggestion.State != todoSuggestionPending {
		c.JSON(http.StatusBadRequest, gin.H{"error": "todo suggestion is not pending"})
		return
	}
	now := time.Now()
	item := models.TodoItem{
		ID:                   uuid.NewString(),
		UserID:               userID,
		Title:                suggestion.Title,
		Notes:                suggestion.Notes,
		Status:               todoStatusOpen,
		StartDate:            suggestion.ProposedStartDate,
		DueDate:              suggestion.ProposedDueDate,
		Timezone:             "Asia/Shanghai",
		RepeatRule:           todoRepeatOnce,
		Priority:             normalizeTodoPriority(suggestion.Priority),
		TagsJSON:             encodeTodoTags([]string{"suggested"}),
		Source:               todoSourceSuggestion,
		OriginConversationID: suggestion.OriginConversationID,
		OriginMessageID:      suggestion.OriginMessageID,
		OriginRunID:          suggestion.OriginRunID,
		CreatedAt:            now,
		UpdatedAt:            now,
	}
	err := database.DB.Transaction(func(tx *gorm.DB) error {
		if err := tx.Create(&item).Error; err != nil {
			return err
		}
		suggestion.State = todoSuggestionAccepted
		suggestion.AcceptedTodoID = item.ID
		suggestion.ResolvedAt = &now
		suggestion.UpdatedAt = now
		return tx.Save(&suggestion).Error
	})
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to accept todo suggestion"})
		return
	}
	c.JSON(http.StatusOK, gin.H{
		"todo":       todoResponseFromModel(item),
		"suggestion": todoSuggestionResponseFromModel(suggestion),
	})
}

func (h *TodoHandler) DismissSuggestion(c *gin.Context) {
	userID := requestUserID(c)
	var suggestion models.TodoSuggestion
	if err := database.DB.First(&suggestion, "id = ? AND user_id = ?", c.Param("id"), userID).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "todo suggestion not found"})
		return
	}
	now := time.Now()
	suggestion.State = todoSuggestionDismissed
	suggestion.ResolvedAt = &now
	suggestion.UpdatedAt = now
	if err := database.DB.Save(&suggestion).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to dismiss todo suggestion"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"suggestion": todoSuggestionResponseFromModel(suggestion)})
}

func (h *TodoHandler) generateSuggestions(userID string, limit int) ([]models.TodoSuggestion, error) {
	userID = normalizedUserID(userID)
	existingKeys, err := loadExistingTodoSuggestionKeys(userID)
	if err != nil {
		return nil, err
	}

	var messages []models.Message
	if err := database.DB.Where("user_id = ? AND role = ?", userID, "user").
		Order(messageReverseChronologicalOrder).
		Limit(80).
		Find(&messages).Error; err != nil {
		return nil, err
	}

	candidates := make([]todoSuggestionCandidate, 0, limit)
	for _, message := range messages {
		candidate, ok := todoSuggestionCandidateFromMessage(message)
		if !ok {
			continue
		}
		key := todoDedupKey(candidate.Title)
		if key == "" || existingKeys[key] {
			continue
		}
		existingKeys[key] = true
		candidates = append(candidates, candidate)
		if len(candidates) >= limit {
			break
		}
	}
	if len(candidates) == 0 {
		return []models.TodoSuggestion{}, nil
	}

	now := time.Now()
	suggestions := make([]models.TodoSuggestion, 0, len(candidates))
	for _, candidate := range candidates {
		evidenceJSON := ""
		if len(candidate.Evidence) > 0 {
			if data, err := json.Marshal(candidate.Evidence); err == nil {
				evidenceJSON = limitText(string(data), 2000)
			}
		}
		suggestions = append(suggestions, models.TodoSuggestion{
			ID:                   uuid.NewString(),
			UserID:               userID,
			Title:                candidate.Title,
			Notes:                candidate.Notes,
			ProposedStartDate:    candidate.ProposedStartDate,
			ProposedDueDate:      candidate.ProposedDueDate,
			Priority:             normalizeTodoPriority(candidate.Priority),
			Confidence:           clampTodoConfidence(candidate.Confidence),
			Reason:               candidate.Reason,
			EvidenceJSON:         evidenceJSON,
			Source:               "conversation",
			State:                todoSuggestionPending,
			OriginConversationID: candidate.OriginConversationID,
			OriginMessageID:      candidate.OriginMessageID,
			OriginRunID:          candidate.OriginRunID,
			CreatedAt:            now,
			UpdatedAt:            now,
		})
	}
	if err := database.DB.Create(&suggestions).Error; err != nil {
		return nil, err
	}
	return suggestions, nil
}

func loadTodoSuggestions(userID string, state string, limit int) ([]models.TodoSuggestion, error) {
	if limit <= 0 {
		limit = 20
	}
	var suggestions []models.TodoSuggestion
	normalizedState := normalizeTodoSuggestionState(state)
	query := database.DB.Where("user_id = ? AND state = ?", normalizedUserID(userID), normalizedState)
	if normalizedState == todoSuggestionPending {
		query = query.Where("confidence >= ?", todoMinSuggestionConfidence)
	}
	err := query.
		Order("confidence desc, created_at desc").
		Limit(limit).
		Find(&suggestions).Error
	return suggestions, err
}

func saveTodoItem(item *models.TodoItem) error {
	if err := database.DB.Select("*").Save(item).Error; err != nil {
		return err
	}
	if item.CompletedAt == nil {
		return database.DB.Model(&models.TodoItem{}).
			Where("id = ? AND user_id = ?", item.ID, item.UserID).
			Update("completed_at", nil).Error
	}
	return nil
}

func todoFromCreateRequest(userID string, req todoWriteRequest) (models.TodoItem, error) {
	title := normalizeTodoTitle(req.Title)
	if title == "" {
		return models.TodoItem{}, errors.New("todo title is required")
	}
	startDate, dueDate, err := normalizeTodoDateRange(req.StartDate, firstNonEmptyTodo(req.EndDate, req.DueDate))
	if err != nil {
		return models.TodoItem{}, err
	}
	dueTime, err := normalizeTodoTime(req.DueTime)
	if err != nil {
		return models.TodoItem{}, err
	}
	now := time.Now()
	source := strings.TrimSpace(req.Source)
	if source == "" {
		source = todoSourceManual
	}
	repeatRule := normalizeTodoRepeatRule(req.RepeatRule)
	return models.TodoItem{
		ID:                   uuid.NewString(),
		UserID:               normalizedUserID(userID),
		Title:                title,
		Notes:                limitText(strings.TrimSpace(req.Notes), 4000),
		Status:               todoStatusOpen,
		StartDate:            startDate,
		DueDate:              dueDate,
		DueTime:              dueTime,
		Timezone:             firstNonEmptyTodo(strings.TrimSpace(req.Timezone), "Asia/Shanghai"),
		RepeatRule:           repeatRule,
		Priority:             normalizeTodoPriority(req.Priority),
		TagsJSON:             encodeTodoTags(req.Tags),
		Source:               source,
		OriginConversationID: strings.TrimSpace(req.OriginConversationID),
		OriginMessageID:      req.OriginMessageID,
		OriginRunID:          strings.TrimSpace(req.OriginRunID),
		CreatedAt:            now,
		UpdatedAt:            now,
	}, nil
}

func applyTodoPatch(item *models.TodoItem, req todoPatchRequest) error {
	if req.Title != nil {
		title := normalizeTodoTitle(*req.Title)
		if title == "" {
			return errors.New("todo title is required")
		}
		item.Title = title
	}
	if req.Notes != nil {
		item.Notes = limitText(strings.TrimSpace(*req.Notes), 4000)
	}
	startDate := item.StartDate
	dueDate := item.DueDate
	if req.StartDate != nil {
		normalized, err := normalizeTodoDate(*req.StartDate, "start_date")
		if err != nil {
			return err
		}
		startDate = normalized
	}
	if req.EndDate != nil {
		normalized, err := normalizeTodoDate(*req.EndDate, "end_date")
		if err != nil {
			return err
		}
		dueDate = normalized
	} else if req.DueDate != nil {
		normalized, err := normalizeTodoDate(*req.DueDate, "due_date")
		if err != nil {
			return err
		}
		dueDate = normalized
	}
	if err := validateTodoDateRange(startDate, dueDate); err != nil {
		return err
	}
	item.StartDate = startDate
	item.DueDate = dueDate
	if req.DueTime != nil {
		dueTime, err := normalizeTodoTime(*req.DueTime)
		if err != nil {
			return err
		}
		item.DueTime = dueTime
	}
	if req.Timezone != nil {
		item.Timezone = firstNonEmptyTodo(strings.TrimSpace(*req.Timezone), "Asia/Shanghai")
	}
	if req.RepeatRule != nil {
		item.RepeatRule = normalizeTodoRepeatRule(*req.RepeatRule)
	}
	if req.Priority != nil {
		item.Priority = normalizeTodoPriority(*req.Priority)
	}
	if req.Tags != nil {
		item.TagsJSON = encodeTodoTags(*req.Tags)
	}
	if req.Status != nil {
		status := normalizeTodoStatus(*req.Status)
		if status == "" {
			return errors.New("unsupported todo status")
		}
		item.Status = status
		now := time.Now()
		if status == todoStatusDone {
			item.CompletedAt = &now
		} else {
			item.CompletedAt = nil
		}
	}
	return nil
}

func loadTodos(userID string, scope string, date string, rangeStart string, rangeEnd string, includeCompleted bool) ([]models.TodoItem, error) {
	userID = normalizedUserID(userID)
	var items []models.TodoItem
	query := database.DB.Where("user_id = ?", userID)
	switch scope {
	case "done", "completed":
		query = query.Where("status = ?", todoStatusDone)
	case "month":
		query = todoStatusQuery(query, includeCompleted)
		query = query.Where(todoMonthSQL(), rangeEnd, rangeStart, rangeEnd, rangeStart, rangeStart, rangeEnd, rangeStart, rangeEnd)
	case "upcoming":
		query = todoStatusQuery(query, includeCompleted)
		query = query.Where(todoUpcomingSQL(), date, date, date)
	case "inbox":
		query = todoStatusQuery(query, includeCompleted)
		query = query.Where(todoInboxSQL())
	default:
		query = todoStatusQuery(query, includeCompleted)
		query = query.Where(todoTodaySQL(), date, date, date, date, date)
	}
	if err := query.Find(&items).Error; err != nil {
		return nil, err
	}
	items = filterTodoItemsForScope(items, scope, date, rangeStart, rangeEnd)
	sortTodoItems(items, scope)
	return items, nil
}

func todoStatusQuery(query *gorm.DB, includeCompleted bool) *gorm.DB {
	if includeCompleted {
		return query.Where("status IN ?", []string{todoStatusOpen, todoStatusDone})
	}
	return query.Where("status = ?", todoStatusOpen)
}

func sortTodoItems(items []models.TodoItem, scope string) {
	sort.SliceStable(items, func(i, j int) bool {
		left, right := items[i], items[j]
		if scope == "done" || scope == "completed" {
			return todoCompletedUnix(left) > todoCompletedUnix(right)
		}
		if left.Status != right.Status {
			return left.Status == todoStatusOpen
		}
		leftDate := todoSortDate(left)
		rightDate := todoSortDate(right)
		if leftDate != rightDate {
			if leftDate == "" {
				return false
			}
			if rightDate == "" {
				return true
			}
			return leftDate < rightDate
		}
		if left.DueTime != right.DueTime {
			if left.DueTime == "" {
				return false
			}
			if right.DueTime == "" {
				return true
			}
			return left.DueTime < right.DueTime
		}
		if todoPriorityRank(left.Priority) != todoPriorityRank(right.Priority) {
			return todoPriorityRank(left.Priority) > todoPriorityRank(right.Priority)
		}
		return left.CreatedAt.Before(right.CreatedAt)
	})
}

func todoTodaySQL() string {
	return "((repeat_rule IN ('daily', 'workdays') AND (start_date IS NULL OR start_date = '' OR start_date <= ?) AND (due_date IS NULL OR due_date = '' OR due_date >= ?)) OR ((repeat_rule IS NULL OR repeat_rule = '' OR repeat_rule = 'once') AND ((due_date IS NOT NULL AND due_date != '' AND due_date <= ?) OR (start_date IS NOT NULL AND start_date != '' AND start_date <= ? AND (due_date IS NULL OR due_date = '' OR due_date >= ?)))))"
}

func todoUpcomingSQL() string {
	return "((repeat_rule IN ('daily', 'workdays') AND start_date IS NOT NULL AND start_date != '' AND start_date > ?) OR ((repeat_rule IS NULL OR repeat_rule = '' OR repeat_rule = 'once') AND ((start_date IS NOT NULL AND start_date != '' AND start_date > ?) OR ((start_date IS NULL OR start_date = '') AND due_date IS NOT NULL AND due_date != '' AND due_date > ?))))"
}

func todoInboxSQL() string {
	return "(repeat_rule IS NULL OR repeat_rule = '' OR repeat_rule = 'once') AND (start_date IS NULL OR start_date = '') AND (due_date IS NULL OR due_date = '')"
}

func todoMonthSQL() string {
	return "((repeat_rule IN ('daily', 'workdays') AND (start_date IS NULL OR start_date = '' OR start_date <= ?) AND (due_date IS NULL OR due_date = '' OR due_date >= ?)) OR ((repeat_rule IS NULL OR repeat_rule = '' OR repeat_rule = 'once') AND ((start_date IS NOT NULL AND start_date != '' AND due_date IS NOT NULL AND due_date != '' AND start_date <= ? AND due_date >= ?) OR (start_date IS NOT NULL AND start_date != '' AND (due_date IS NULL OR due_date = '') AND start_date BETWEEN ? AND ?) OR ((start_date IS NULL OR start_date = '') AND due_date IS NOT NULL AND due_date != '' AND due_date BETWEEN ? AND ?))))"
}

func filterTodoItemsForScope(items []models.TodoItem, scope string, date string, rangeStart string, rangeEnd string) []models.TodoItem {
	filtered := make([]models.TodoItem, 0, len(items))
	for _, item := range items {
		switch scope {
		case "month":
			if todoOccursInRange(item, rangeStart, rangeEnd) {
				filtered = append(filtered, item)
			}
		case "inbox", "done", "completed", "upcoming":
			filtered = append(filtered, item)
		default:
			if todoOccursOnDate(item, date) {
				filtered = append(filtered, item)
			}
		}
	}
	return filtered
}

func todoSortDate(item models.TodoItem) string {
	if item.StartDate != "" {
		return item.StartDate
	}
	return item.DueDate
}

func todoOccursOnDate(item models.TodoItem, date string) bool {
	if date == "" {
		return false
	}
	repeatRule := normalizeTodoRepeatRule(item.RepeatRule)
	switch repeatRule {
	case todoRepeatDaily:
		return todoDateInLifecycle(date, item.StartDate, item.DueDate)
	case todoRepeatWorkdays:
		return todoDateInLifecycle(date, item.StartDate, item.DueDate) && todoDateIsWorkday(date)
	default:
		startDate := item.StartDate
		endDate := item.DueDate
		if startDate != "" && endDate != "" {
			return startDate <= date && endDate >= date
		}
		if endDate != "" {
			return endDate <= date
		}
		return startDate != "" && startDate <= date
	}
}

func todoOccursInRange(item models.TodoItem, startDate string, endDate string) bool {
	if startDate == "" || endDate == "" {
		return false
	}
	repeatRule := normalizeTodoRepeatRule(item.RepeatRule)
	switch repeatRule {
	case todoRepeatDaily:
		return todoLifecycleIntersectsRange(item.StartDate, item.DueDate, startDate, endDate)
	case todoRepeatWorkdays:
		if !todoLifecycleIntersectsRange(item.StartDate, item.DueDate, startDate, endDate) {
			return false
		}
		return todoRangeHasWorkday(maxTodoDate(startDate, firstNonEmptyTodo(item.StartDate, startDate)), minTodoDate(endDate, firstNonEmptyTodo(item.DueDate, endDate)))
	default:
		start := item.StartDate
		end := item.DueDate
		if start != "" && end != "" {
			return start <= endDate && end >= startDate
		}
		if start != "" {
			return start >= startDate && start <= endDate
		}
		return end != "" && end >= startDate && end <= endDate
	}
}

func todoDateInLifecycle(date string, startDate string, endDate string) bool {
	if startDate != "" && date < startDate {
		return false
	}
	if endDate != "" && date > endDate {
		return false
	}
	return true
}

func todoLifecycleIntersectsRange(itemStart string, itemEnd string, rangeStart string, rangeEnd string) bool {
	start := firstNonEmptyTodo(itemStart, rangeStart)
	end := firstNonEmptyTodo(itemEnd, rangeEnd)
	return start <= rangeEnd && end >= rangeStart
}

func todoDateIsWorkday(date string) bool {
	parsed, err := time.ParseInLocation("2006-01-02", date, todoLocalLocation)
	if err != nil {
		return false
	}
	weekday := parsed.Weekday()
	return weekday >= time.Monday && weekday <= time.Friday
}

func todoRangeHasWorkday(startDate string, endDate string) bool {
	start, err := time.ParseInLocation("2006-01-02", startDate, todoLocalLocation)
	if err != nil {
		return false
	}
	end, err := time.ParseInLocation("2006-01-02", endDate, todoLocalLocation)
	if err != nil || end.Before(start) {
		return false
	}
	for day := start; !day.After(end); day = day.AddDate(0, 0, 1) {
		if day.Weekday() >= time.Monday && day.Weekday() <= time.Friday {
			return true
		}
	}
	return false
}

func maxTodoDate(left string, right string) string {
	if left > right {
		return left
	}
	return right
}

func minTodoDate(left string, right string) string {
	if left < right {
		return left
	}
	return right
}

func todoCounts(userID string, date string) (map[string]int64, error) {
	userID = normalizedUserID(userID)
	counts := map[string]int64{
		"today":    0,
		"upcoming": 0,
		"inbox":    0,
		"done":     0,
	}
	for _, scope := range []string{"today", "upcoming", "inbox"} {
		items, err := loadTodos(userID, scope, date, date, date, false)
		if err != nil {
			return nil, err
		}
		counts[scope] = int64(len(items))
	}
	var doneCount int64
	if err := database.DB.Model(&models.TodoItem{}).Where("user_id = ? AND status = ?", userID, todoStatusDone).Count(&doneCount).Error; err != nil {
		return nil, err
	}
	counts["done"] = doneCount
	var suggestionCount int64
	if err := database.DB.Model(&models.TodoSuggestion{}).Where("user_id = ? AND state = ? AND confidence >= ?", userID, todoSuggestionPending, todoMinSuggestionConfidence).Count(&suggestionCount).Error; err != nil {
		return nil, err
	}
	counts["suggestions"] = suggestionCount
	return counts, nil
}

func todoSuggestionCandidateFromMessage(message models.Message) (todoSuggestionCandidate, bool) {
	content := strings.TrimSpace(message.Content)
	if !hasTodoSignal(content) {
		return todoSuggestionCandidate{}, false
	}
	title := suggestionTitleFromText(content)
	if title == "" {
		return todoSuggestionCandidate{}, false
	}
	startDate, dueDate := inferTodoDateRange(content)
	confidence := 62
	if dueDate != "" {
		confidence += 8
	}
	if startDate != "" && startDate != dueDate {
		confidence += 4
	}
	if hasDirectTodoIntent(content) {
		confidence += 14
	}
	if confidence < todoMinSuggestionConfidence {
		return todoSuggestionCandidate{}, false
	}
	return todoSuggestionCandidate{
		Title:             title,
		Notes:             limitText(content, 500),
		ProposedStartDate: startDate,
		ProposedDueDate:   dueDate,
		Priority:          inferTodoPriority(content),
		Confidence:        confidence,
		Reason:            "近期会话里出现了可执行的后续行动信号",
		Evidence: map[string]interface{}{
			"message_id":      message.ID,
			"conversation_id": message.ConversationID,
			"created_at":      message.CreatedAt.Format(time.RFC3339),
			"excerpt":         limitText(content, 220),
		},
		OriginConversationID: message.ConversationID,
		OriginMessageID:      message.ID,
		OriginRunID:          message.RunID,
	}, true
}

func hasTodoSignal(text string) bool {
	value := strings.ToLower(strings.TrimSpace(text))
	if len([]rune(value)) < 6 {
		return false
	}
	if hasDirectTodoIntent(value) {
		return true
	}
	if looksLikeImmediateAgentRequest(value) || looksLikeQuestion(value) {
		return false
	}
	return hasTodoTimeSignal(value) && hasTodoActionSignal(value)
}

func hasDirectTodoIntent(text string) bool {
	value := strings.ToLower(strings.TrimSpace(text))
	for _, signal := range []string{"待办", "记得", "提醒我", "remind me", "deadline", "加到todo", "加到 todo", "add to todo", "put on todo", "todo:", "todo：", "to-do:", "to-do："} {
		if strings.Contains(value, signal) {
			return true
		}
	}
	return false
}

func hasTodoTimeSignal(text string) bool {
	value := strings.ToLower(strings.TrimSpace(text))
	if regexp.MustCompile(`\d{4}-\d{1,2}-\d{1,2}|\d{1,2}\s*月\s*\d{1,2}\s*[日号]?|\d{1,2}\s*[日号]\s*(到|至|~|-)\s*\d{1,2}\s*[日号]`).MatchString(value) {
		return true
	}
	for _, signal := range []string{"今天", "明天", "后天", "本周", "这周", "下周", "月底", "周一", "周二", "周三", "周四", "周五", "周六", "周日", "today", "tomorrow", "next week"} {
		if strings.Contains(value, signal) {
			return true
		}
	}
	return false
}

func hasTodoActionSignal(text string) bool {
	value := strings.ToLower(strings.TrimSpace(text))
	for _, signal := range []string{
		"跟进", "安排", "完成", "处理", "检查", "复盘",
		"整理", "提交", "联系", "确认", "上线", "review", "follow up", "finish",
		"submit", "check", "schedule", "call",
	} {
		if strings.Contains(value, signal) {
			return true
		}
	}
	return false
}

func looksLikeImmediateAgentRequest(text string) bool {
	value := strings.TrimSpace(text)
	if hasDirectTodoIntent(value) {
		return false
	}
	prefixes := []string{"帮我", "你帮我", "请帮我", "麻烦你", "看看", "优化一下", "改一下", "可以，动手吧", "可以,动手吧"}
	for _, prefix := range prefixes {
		if strings.HasPrefix(value, prefix) {
			return true
		}
	}
	return false
}

func looksLikeQuestion(text string) bool {
	value := strings.TrimSpace(text)
	return strings.Contains(value, "?") || strings.Contains(value, "？") || strings.HasPrefix(value, "为什么") || strings.HasPrefix(strings.ToLower(value), "why ")
}

func suggestionTitleFromText(text string) string {
	clean := strings.TrimSpace(text)
	clean = regexp.MustCompile(`(?i)^(请|帮我|麻烦)?\s*(记得|提醒我|把这个加到待办|加到待办|todo[:：]?|to-do[:：]?|remind me to)\s*`).ReplaceAllString(clean, "")
	clean = regexp.MustCompile(`^(今天|明天|后天|本周|这周|下周|月底)\s*`).ReplaceAllString(clean, "")
	clean = regexp.MustCompile(`^\d{1,2}\s*[日号]\s*(到|至|~|-)\s*\d{1,2}\s*[日号]?\s*`).ReplaceAllString(clean, "")
	clean = regexp.MustCompile(`\s+`).ReplaceAllString(clean, " ")
	clean = strings.Trim(clean, " ，。,.!?？；;：:")
	if clean == "" {
		return ""
	}
	if strings.Contains(clean, "\n") {
		clean = strings.TrimSpace(strings.Split(clean, "\n")[0])
	}
	if len([]rune(clean)) > 90 {
		runes := []rune(clean)
		clean = string(runes[:90]) + "..."
	}
	return clean
}

func inferTodoDueDate(text string) string {
	_, dueDate := inferTodoDateRange(text)
	return dueDate
}

func inferTodoDateRange(text string) (string, string) {
	value := strings.ToLower(text)
	today := time.Now().In(todoLocalLocation)
	if start, end := inferExplicitTodoDateRange(value, today); start != "" || end != "" {
		return start, end
	}
	switch {
	case strings.Contains(value, "今天") || strings.Contains(value, "today"):
		date := today.Format("2006-01-02")
		return date, date
	case strings.Contains(value, "明天") || strings.Contains(value, "tomorrow"):
		return "", today.AddDate(0, 0, 1).Format("2006-01-02")
	case strings.Contains(value, "后天"):
		return "", today.AddDate(0, 0, 2).Format("2006-01-02")
	case strings.Contains(value, "下周") || strings.Contains(value, "next week"):
		start := today.AddDate(0, 0, 7)
		return start.Format("2006-01-02"), start.AddDate(0, 0, 6).Format("2006-01-02")
	default:
		return "", ""
	}
}

func inferExplicitTodoDateRange(text string, today time.Time) (string, string) {
	if matches := regexp.MustCompile(`(\d{4}-\d{1,2}-\d{1,2})(?:\s*(?:到|至|~|-)\s*(\d{4}-\d{1,2}-\d{1,2}))?`).FindStringSubmatch(text); len(matches) > 0 {
		start := normalizeLooseDate(matches[1])
		end := normalizeLooseDate(firstNonEmptyTodo(matches[2], matches[1]))
		if start != "" && end != "" && start <= end {
			return start, end
		}
	}
	if matches := regexp.MustCompile(`(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?\s*(?:到|至|~|-)\s*(?:(\d{1,2})\s*月\s*)?(\d{1,2})\s*[日号]?`).FindStringSubmatch(text); len(matches) > 0 {
		startMonth := atoiDefault(matches[1], 0)
		startDay := atoiDefault(matches[2], 0)
		endMonth := atoiDefault(firstNonEmptyTodo(matches[3], matches[1]), 0)
		endDay := atoiDefault(matches[4], 0)
		start := todoMonthDayDate(today, startMonth, startDay, false)
		end := todoMonthDayDate(today, endMonth, endDay, false)
		if start != "" && end != "" && end < start {
			endTime, err := time.ParseInLocation("2006-01-02", end, todoLocalLocation)
			if err == nil {
				end = endTime.AddDate(1, 0, 0).Format("2006-01-02")
			}
		}
		if start != "" && end != "" {
			return start, end
		}
	}
	if matches := regexp.MustCompile(`(\d{1,2})\s*[日号]\s*(?:到|至|~|-)\s*(\d{1,2})\s*[日号]?`).FindStringSubmatch(text); len(matches) > 0 {
		startDay := atoiDefault(matches[1], 0)
		endDay := atoiDefault(matches[2], 0)
		year, month, _ := today.Date()
		startTime := time.Date(year, month, startDay, 0, 0, 0, 0, todoLocalLocation)
		endTime := time.Date(year, month, endDay, 0, 0, 0, 0, todoLocalLocation)
		if !validTodoMonthDay(startTime, int(month), startDay) || !validTodoMonthDay(endTime, int(month), endDay) {
			return "", ""
		}
		if endTime.Before(today) {
			startTime = startTime.AddDate(0, 1, 0)
			endTime = endTime.AddDate(0, 1, 0)
		}
		if endTime.Before(startTime) {
			endTime = endTime.AddDate(0, 1, 0)
		}
		return startTime.Format("2006-01-02"), endTime.Format("2006-01-02")
	}
	return "", ""
}

func normalizeLooseDate(value string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return ""
	}
	parsed, err := time.Parse("2006-1-2", value)
	if err != nil {
		return ""
	}
	return parsed.Format("2006-01-02")
}

func todoMonthDayDate(today time.Time, month int, day int, preferFuture bool) string {
	if month < 1 || month > 12 || day < 1 || day > 31 {
		return ""
	}
	year := today.Year()
	date := time.Date(year, time.Month(month), day, 0, 0, 0, 0, todoLocalLocation)
	if !validTodoMonthDay(date, month, day) {
		return ""
	}
	if preferFuture && date.Before(today) {
		date = date.AddDate(1, 0, 0)
	}
	return date.Format("2006-01-02")
}

func validTodoMonthDay(date time.Time, month int, day int) bool {
	return int(date.Month()) == month && date.Day() == day
}

func atoiDefault(value string, fallback int) int {
	value = strings.TrimSpace(value)
	if value == "" {
		return fallback
	}
	total := 0
	for _, char := range value {
		if char < '0' || char > '9' {
			return fallback
		}
		total = total*10 + int(char-'0')
	}
	return total
}

func inferTodoPriority(text string) string {
	value := strings.ToLower(text)
	if strings.Contains(value, "紧急") || strings.Contains(value, "重要") || strings.Contains(value, "urgent") || strings.Contains(value, "important") {
		return todoPriorityHigh
	}
	return todoPriorityNormal
}

func loadExistingTodoSuggestionKeys(userID string) (map[string]bool, error) {
	keys := map[string]bool{}
	var todos []models.TodoItem
	if err := database.DB.Where("user_id = ? AND status = ?", userID, todoStatusOpen).Find(&todos).Error; err != nil {
		return nil, err
	}
	for _, todo := range todos {
		if key := todoDedupKey(todo.Title); key != "" {
			keys[key] = true
		}
	}
	var suggestions []models.TodoSuggestion
	if err := database.DB.Where("user_id = ? AND state = ?", userID, todoSuggestionPending).Find(&suggestions).Error; err != nil {
		return nil, err
	}
	for _, suggestion := range suggestions {
		if key := todoDedupKey(suggestion.Title); key != "" {
			keys[key] = true
		}
	}
	return keys, nil
}

func todoDedupKey(text string) string {
	return strings.ToLower(regexp.MustCompile(`\s+`).ReplaceAllString(strings.TrimSpace(text), " "))
}

func todoResponses(items []models.TodoItem) []todoResponse {
	responses := make([]todoResponse, 0, len(items))
	for _, item := range items {
		responses = append(responses, todoResponseFromModel(item))
	}
	return responses
}

func todoResponseFromModel(item models.TodoItem) todoResponse {
	return todoResponse{
		ID:                   item.ID,
		UserID:               item.UserID,
		Title:                item.Title,
		Notes:                item.Notes,
		Status:               item.Status,
		StartDate:            item.StartDate,
		DueDate:              item.DueDate,
		EndDate:              item.DueDate,
		DueTime:              item.DueTime,
		Timezone:             item.Timezone,
		RepeatRule:           normalizeTodoRepeatRule(item.RepeatRule),
		Priority:             item.Priority,
		Tags:                 decodeTodoTags(item.TagsJSON),
		Source:               item.Source,
		OriginConversationID: item.OriginConversationID,
		OriginMessageID:      item.OriginMessageID,
		OriginRunID:          item.OriginRunID,
		CreatedAt:            item.CreatedAt,
		UpdatedAt:            item.UpdatedAt,
		CompletedAt:          item.CompletedAt,
	}
}

func todoSuggestionResponses(suggestions []models.TodoSuggestion) []todoSuggestionResponse {
	responses := make([]todoSuggestionResponse, 0, len(suggestions))
	for _, suggestion := range suggestions {
		responses = append(responses, todoSuggestionResponseFromModel(suggestion))
	}
	return responses
}

func todoSuggestionResponseFromModel(suggestion models.TodoSuggestion) todoSuggestionResponse {
	evidence := map[string]interface{}{}
	if strings.TrimSpace(suggestion.EvidenceJSON) != "" {
		_ = json.Unmarshal([]byte(suggestion.EvidenceJSON), &evidence)
	}
	return todoSuggestionResponse{
		ID:                   suggestion.ID,
		UserID:               suggestion.UserID,
		Title:                suggestion.Title,
		Notes:                suggestion.Notes,
		ProposedStartDate:    suggestion.ProposedStartDate,
		ProposedDueDate:      suggestion.ProposedDueDate,
		Priority:             suggestion.Priority,
		Confidence:           suggestion.Confidence,
		Reason:               suggestion.Reason,
		Evidence:             evidence,
		Source:               suggestion.Source,
		State:                suggestion.State,
		AcceptedTodoID:       suggestion.AcceptedTodoID,
		OriginConversationID: suggestion.OriginConversationID,
		OriginMessageID:      suggestion.OriginMessageID,
		OriginRunID:          suggestion.OriginRunID,
		CreatedAt:            suggestion.CreatedAt,
		UpdatedAt:            suggestion.UpdatedAt,
		ResolvedAt:           suggestion.ResolvedAt,
	}
}

func normalizeTodoTitle(title string) string {
	return limitText(strings.TrimSpace(regexp.MustCompile(`\s+`).ReplaceAllString(title, " ")), 180)
}

func normalizeTodoStatus(status string) string {
	switch strings.ToLower(strings.TrimSpace(status)) {
	case "", todoStatusOpen:
		return todoStatusOpen
	case todoStatusDone, "completed":
		return todoStatusDone
	case todoStatusArchived:
		return todoStatusArchived
	default:
		return ""
	}
}

func normalizeTodoSuggestionState(state string) string {
	switch strings.ToLower(strings.TrimSpace(state)) {
	case todoSuggestionAccepted:
		return todoSuggestionAccepted
	case todoSuggestionDismissed:
		return todoSuggestionDismissed
	default:
		return todoSuggestionPending
	}
}

func normalizeTodoPriority(priority string) string {
	switch strings.ToLower(strings.TrimSpace(priority)) {
	case todoPriorityLow:
		return todoPriorityLow
	case todoPriorityHigh:
		return todoPriorityHigh
	default:
		return todoPriorityNormal
	}
}

func normalizeTodoRepeatRule(rule string) string {
	switch strings.ToLower(strings.TrimSpace(rule)) {
	case todoRepeatDaily:
		return todoRepeatDaily
	case todoRepeatWorkdays, "weekday", "weekdays":
		return todoRepeatWorkdays
	default:
		return todoRepeatOnce
	}
}

func normalizeTodoDateRange(startValue string, endValue string) (string, string, error) {
	startDate, err := normalizeTodoDate(startValue, "start_date")
	if err != nil {
		return "", "", err
	}
	endDate, err := normalizeTodoDate(endValue, "end_date")
	if err != nil {
		return "", "", err
	}
	if err := validateTodoDateRange(startDate, endDate); err != nil {
		return "", "", err
	}
	return startDate, endDate, nil
}

func validateTodoDateRange(startDate string, endDate string) error {
	if startDate != "" && endDate != "" && startDate > endDate {
		return errors.New("start_date must be on or before end_date")
	}
	return nil
}

func normalizeTodoDate(value string, field string) (string, error) {
	value = strings.TrimSpace(value)
	if value == "" {
		return "", nil
	}
	if _, err := time.Parse("2006-01-02", value); err != nil {
		return "", errors.New("invalid " + field + ", expected YYYY-MM-DD")
	}
	return value, nil
}

func normalizeTodoTime(value string) (string, error) {
	value = strings.TrimSpace(value)
	if value == "" {
		return "", nil
	}
	if _, err := time.Parse("15:04", value); err != nil {
		return "", errors.New("invalid due_time, expected HH:MM")
	}
	return value, nil
}

func requestedTodoDate(value string) string {
	date, err := normalizeTodoDate(value, "date")
	if err == nil && date != "" {
		return date
	}
	return time.Now().In(todoLocalLocation).Format("2006-01-02")
}

func requestedTodoRange(startValue string, endValue string, fallbackDate string) (string, string) {
	startDate, err := normalizeTodoDate(startValue, "start")
	if err != nil || startDate == "" {
		startDate = fallbackDate
	}
	endDate, err := normalizeTodoDate(endValue, "end")
	if err != nil || endDate == "" {
		endDate = startDate
	}
	if endDate < startDate {
		endDate = startDate
	}
	return startDate, endDate
}

func parseTodoBool(value string) bool {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case "1", "true", "yes", "y", "on":
		return true
	default:
		return false
	}
}

func encodeTodoTags(tags []string) string {
	normalized := make([]string, 0, len(tags))
	seen := map[string]bool{}
	for _, tag := range tags {
		tag = limitText(strings.TrimSpace(tag), 40)
		key := strings.ToLower(tag)
		if tag == "" || seen[key] {
			continue
		}
		seen[key] = true
		normalized = append(normalized, tag)
		if len(normalized) >= 8 {
			break
		}
	}
	if len(normalized) == 0 {
		return ""
	}
	data, _ := json.Marshal(normalized)
	return string(data)
}

func decodeTodoTags(raw string) []string {
	if strings.TrimSpace(raw) == "" {
		return []string{}
	}
	var tags []string
	if err := json.Unmarshal([]byte(raw), &tags); err != nil {
		return []string{}
	}
	return tags
}

func todoPriorityRank(priority string) int {
	switch normalizeTodoPriority(priority) {
	case todoPriorityHigh:
		return 3
	case todoPriorityNormal:
		return 2
	case todoPriorityLow:
		return 1
	default:
		return 0
	}
}

func todoCompletedUnix(item models.TodoItem) int64 {
	if item.CompletedAt != nil {
		return item.CompletedAt.Unix()
	}
	return item.UpdatedAt.Unix()
}

func clampTodoConfidence(value int) int {
	if value < 0 {
		return 0
	}
	if value > 100 {
		return 100
	}
	return value
}

func firstNonEmptyTodo(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return strings.TrimSpace(value)
		}
	}
	return ""
}

func findTodoByID(userID string, id string) (models.TodoItem, error) {
	var item models.TodoItem
	err := database.DB.First(&item, "id = ? AND user_id = ?", id, normalizedUserID(userID)).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return item, err
	}
	return item, err
}
