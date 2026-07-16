package handlers

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
)

func setupTodoTest(t *testing.T) (*gin.Engine, *TodoHandler) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	if err := database.Init(filepath.Join(t.TempDir(), "assistant.db")); err != nil {
		t.Fatalf("init database: %v", err)
	}
	handler := NewTodoHandler()
	router := gin.New()
	router.GET("/api/todos", handler.List)
	router.POST("/api/todos", handler.Create)
	router.PUT("/api/todos/:id", handler.Update)
	router.POST("/api/todos/:id/complete", handler.Complete)
	router.DELETE("/api/todos/:id", handler.Delete)
	router.GET("/api/todo-suggestions", handler.ListSuggestions)
	router.POST("/api/todo-suggestions/refresh", handler.RefreshSuggestions)
	router.POST("/api/todo-suggestions/:id/accept", handler.AcceptSuggestion)
	router.POST("/api/todo-suggestions/:id/dismiss", handler.DismissSuggestion)
	return router, handler
}

func todoResponseByID(items []todoResponse, id string) (todoResponse, bool) {
	for _, item := range items {
		if item.ID == id {
			return item, true
		}
	}
	return todoResponse{}, false
}

func containsTodoDate(dates []string, date string) bool {
	for _, candidate := range dates {
		if candidate == date {
			return true
		}
	}
	return false
}

func TestTodoCRUDScopesByUserAndDate(t *testing.T) {
	router, _ := setupTodoTest(t)
	today := time.Now().In(todoLocalLocation)
	todayText := today.Format("2006-01-02")
	yesterdayText := today.AddDate(0, 0, -1).Format("2006-01-02")
	tomorrowText := today.AddDate(0, 0, 1).Format("2006-01-02")
	nextWeekText := today.AddDate(0, 0, 7).Format("2006-01-02")
	now := time.Now()
	items := []models.TodoItem{
		{ID: "today-a", UserID: "user-a", Title: "Today A", Status: todoStatusOpen, DueDate: todayText, Priority: todoPriorityNormal, Source: todoSourceManual, CreatedAt: now, UpdatedAt: now},
		{ID: "tomorrow-a", UserID: "user-a", Title: "Tomorrow A", Status: todoStatusOpen, DueDate: tomorrowText, Priority: todoPriorityHigh, Source: todoSourceManual, CreatedAt: now, UpdatedAt: now},
		{ID: "range-a", UserID: "user-a", Title: "Range A", Status: todoStatusOpen, StartDate: yesterdayText, DueDate: nextWeekText, Priority: todoPriorityNormal, Source: todoSourceManual, CreatedAt: now, UpdatedAt: now},
		{ID: "daily-a", UserID: "user-a", Title: "Daily A", Status: todoStatusOpen, StartDate: yesterdayText, RepeatRule: todoRepeatDaily, Priority: todoPriorityNormal, Source: todoSourceManual, CreatedAt: now, UpdatedAt: now},
		{ID: "inbox-a", UserID: "user-a", Title: "Inbox A", Status: todoStatusOpen, Priority: todoPriorityLow, Source: todoSourceManual, CreatedAt: now, UpdatedAt: now},
		{ID: "today-b", UserID: "user-b", Title: "Today B", Status: todoStatusOpen, DueDate: todayText, Priority: todoPriorityNormal, Source: todoSourceManual, CreatedAt: now, UpdatedAt: now},
	}
	if err := database.DB.Create(&items).Error; err != nil {
		t.Fatalf("create todos: %v", err)
	}

	req := httptest.NewRequest(http.MethodGet, "/api/todos?scope=today&date="+todayText, nil)
	req.Header.Set("X-User-ID", "user-a")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)
	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	var payload struct {
		Items  []todoResponse   `json:"items"`
		Counts map[string]int64 `json:"counts"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if len(payload.Items) != 3 || payload.Items[0].ID != "range-a" || payload.Items[1].ID != "daily-a" || payload.Items[2].ID != "today-a" {
		t.Fatalf("expected today's user-a todos including active range, got %#v", payload.Items)
	}
	if payload.Counts["today"] != 3 || payload.Counts["upcoming"] != 1 || payload.Counts["inbox"] != 1 {
		t.Fatalf("unexpected counts: %#v", payload.Counts)
	}

	createReq := httptest.NewRequest(http.MethodPost, "/api/todos", bytes.NewBufferString(`{"title":"Review todo UI","start_date":"`+todayText+`","end_date":"`+tomorrowText+`","priority":"high","tags":["ui"]}`))
	createReq.Header.Set("Content-Type", "application/json")
	createReq.Header.Set("X-User-ID", "user-a")
	createRecorder := httptest.NewRecorder()
	router.ServeHTTP(createRecorder, createReq)
	if createRecorder.Code != http.StatusCreated {
		t.Fatalf("unexpected create status %d: %s", createRecorder.Code, createRecorder.Body.String())
	}
	var created struct {
		Todo todoResponse `json:"todo"`
	}
	if err := json.Unmarshal(createRecorder.Body.Bytes(), &created); err != nil {
		t.Fatalf("decode created todo: %v", err)
	}
	if created.Todo.Title != "Review todo UI" || created.Todo.Priority != todoPriorityHigh || created.Todo.StartDate != todayText || created.Todo.EndDate != tomorrowText || len(created.Todo.Tags) != 1 {
		t.Fatalf("unexpected created todo: %#v", created.Todo)
	}

	editReq := httptest.NewRequest(http.MethodPut, "/api/todos/"+created.Todo.ID, bytes.NewBufferString(`{"title":"Review todo polish","notes":"tighten card UI","start_date":"`+yesterdayText+`","end_date":"`+nextWeekText+`","repeat_rule":"daily","priority":"low"}`))
	editReq.Header.Set("Content-Type", "application/json")
	editReq.Header.Set("X-User-ID", "user-a")
	editRecorder := httptest.NewRecorder()
	router.ServeHTTP(editRecorder, editReq)
	if editRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected edit status %d: %s", editRecorder.Code, editRecorder.Body.String())
	}
	var edited struct {
		Todo todoResponse `json:"todo"`
	}
	if err := json.Unmarshal(editRecorder.Body.Bytes(), &edited); err != nil {
		t.Fatalf("decode edited todo: %v", err)
	}
	if edited.Todo.Title != "Review todo polish" || edited.Todo.Notes != "tighten card UI" || edited.Todo.StartDate != yesterdayText || edited.Todo.EndDate != nextWeekText || edited.Todo.RepeatRule != todoRepeatDaily || edited.Todo.Priority != todoPriorityLow {
		t.Fatalf("unexpected edited todo: %#v", edited.Todo)
	}

	completeReq := httptest.NewRequest(http.MethodPost, "/api/todos/"+created.Todo.ID+"/complete?occurrence_date="+todayText, nil)
	completeReq.Header.Set("X-User-ID", "user-a")
	completeRecorder := httptest.NewRecorder()
	router.ServeHTTP(completeRecorder, completeReq)
	if completeRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected complete status %d: %s", completeRecorder.Code, completeRecorder.Body.String())
	}
	var completed models.TodoItem
	if err := database.DB.First(&completed, "id = ?", created.Todo.ID).Error; err != nil {
		t.Fatalf("load completed todo: %v", err)
	}
	if completed.Status != todoStatusOpen || completed.CompletedAt != nil {
		t.Fatalf("expected repeating todo to stay globally open, got %#v", completed)
	}
	var occurrenceCount int64
	if err := database.DB.Model(&models.TodoCompletion{}).Where("todo_id = ? AND occurrence_date = ?", created.Todo.ID, todayText).Count(&occurrenceCount).Error; err != nil {
		t.Fatalf("count completion occurrence: %v", err)
	}
	if occurrenceCount != 1 {
		t.Fatalf("expected one completed occurrence, got %d", occurrenceCount)
	}

	doneReq := httptest.NewRequest(http.MethodGet, "/api/todos?scope=today&include_completed=true&date="+todayText, nil)
	doneReq.Header.Set("X-User-ID", "user-a")
	doneRecorder := httptest.NewRecorder()
	router.ServeHTTP(doneRecorder, doneReq)
	if doneRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected include completed status %d: %s", doneRecorder.Code, doneRecorder.Body.String())
	}
	var donePayload struct {
		Items []todoResponse `json:"items"`
	}
	if err := json.Unmarshal(doneRecorder.Body.Bytes(), &donePayload); err != nil {
		t.Fatalf("decode include completed response: %v", err)
	}
	doneTodo, ok := todoResponseByID(donePayload.Items, created.Todo.ID)
	if len(donePayload.Items) != 4 || !ok || doneTodo.Status != todoStatusDone || !doneTodo.OccurrenceCompleted || doneTodo.OccurrenceDate != todayText {
		t.Fatalf("expected completed occurrence in today list, got %#v", donePayload.Items)
	}

	reopenReq := httptest.NewRequest(http.MethodPut, "/api/todos/"+created.Todo.ID, bytes.NewBufferString(`{"status":"open","occurrence_date":"`+todayText+`"}`))
	reopenReq.Header.Set("Content-Type", "application/json")
	reopenReq.Header.Set("X-User-ID", "user-a")
	reopenRecorder := httptest.NewRecorder()
	router.ServeHTTP(reopenRecorder, reopenReq)
	if reopenRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected reopen status %d: %s", reopenRecorder.Code, reopenRecorder.Body.String())
	}
	var reopened models.TodoItem
	if err := database.DB.First(&reopened, "id = ?", created.Todo.ID).Error; err != nil {
		t.Fatalf("reload reopened todo: %v", err)
	}
	if reopened.Status != todoStatusOpen || reopened.CompletedAt != nil {
		t.Fatalf("expected reopened todo, got %#v", reopened)
	}
	if err := database.DB.Model(&models.TodoCompletion{}).Where("todo_id = ? AND occurrence_date = ?", created.Todo.ID, todayText).Count(&occurrenceCount).Error; err != nil {
		t.Fatalf("count reopened occurrence: %v", err)
	}
	if occurrenceCount != 0 {
		t.Fatalf("expected reopened occurrence to be removed, got %d", occurrenceCount)
	}
}

func TestRepeatingTodoCompletionOnlyAffectsSingleOccurrence(t *testing.T) {
	router, _ := setupTodoTest(t)
	now := time.Now()
	item := models.TodoItem{
		ID:         "daily-one",
		UserID:     "user-a",
		Title:      "Daily one",
		Status:     todoStatusOpen,
		StartDate:  "2026-07-01",
		DueDate:    "2026-07-31",
		RepeatRule: todoRepeatDaily,
		Priority:   todoPriorityNormal,
		Source:     todoSourceManual,
		CreatedAt:  now,
		UpdatedAt:  now,
	}
	if err := database.DB.Create(&item).Error; err != nil {
		t.Fatalf("create todo: %v", err)
	}

	completeReq := httptest.NewRequest(http.MethodPut, "/api/todos/daily-one", bytes.NewBufferString(`{"status":"done","occurrence_date":"2026-07-11"}`))
	completeReq.Header.Set("Content-Type", "application/json")
	completeReq.Header.Set("X-User-ID", "user-a")
	completeRecorder := httptest.NewRecorder()
	router.ServeHTTP(completeRecorder, completeReq)
	if completeRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected complete status %d: %s", completeRecorder.Code, completeRecorder.Body.String())
	}

	dayReq := httptest.NewRequest(http.MethodGet, "/api/todos?scope=today&date=2026-07-11&include_completed=false", nil)
	dayReq.Header.Set("X-User-ID", "user-a")
	dayRecorder := httptest.NewRecorder()
	router.ServeHTTP(dayRecorder, dayReq)
	if dayRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected completed day status %d: %s", dayRecorder.Code, dayRecorder.Body.String())
	}
	var completedDay struct {
		Items []todoResponse `json:"items"`
	}
	if err := json.Unmarshal(dayRecorder.Body.Bytes(), &completedDay); err != nil {
		t.Fatalf("decode completed day: %v", err)
	}
	if _, ok := todoResponseByID(completedDay.Items, "daily-one"); ok {
		t.Fatalf("completed occurrence should be hidden when include_completed=false, got %#v", completedDay.Items)
	}

	nextReq := httptest.NewRequest(http.MethodGet, "/api/todos?scope=today&date=2026-07-12&include_completed=false", nil)
	nextReq.Header.Set("X-User-ID", "user-a")
	nextRecorder := httptest.NewRecorder()
	router.ServeHTTP(nextRecorder, nextReq)
	if nextRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected next day status %d: %s", nextRecorder.Code, nextRecorder.Body.String())
	}
	var nextDay struct {
		Items []todoResponse `json:"items"`
	}
	if err := json.Unmarshal(nextRecorder.Body.Bytes(), &nextDay); err != nil {
		t.Fatalf("decode next day: %v", err)
	}
	if nextTodo, ok := todoResponseByID(nextDay.Items, "daily-one"); !ok || nextTodo.Status != todoStatusOpen {
		t.Fatalf("future occurrence should remain open, got %#v", nextDay.Items)
	}

	monthReq := httptest.NewRequest(http.MethodGet, "/api/todos?scope=month&start=2026-07-01&end=2026-07-31&include_completed=true", nil)
	monthReq.Header.Set("X-User-ID", "user-a")
	monthRecorder := httptest.NewRecorder()
	router.ServeHTTP(monthRecorder, monthReq)
	if monthRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected month status %d: %s", monthRecorder.Code, monthRecorder.Body.String())
	}
	var monthPayload struct {
		Items []todoResponse `json:"items"`
	}
	if err := json.Unmarshal(monthRecorder.Body.Bytes(), &monthPayload); err != nil {
		t.Fatalf("decode month: %v", err)
	}
	monthTodo, ok := todoResponseByID(monthPayload.Items, "daily-one")
	if !ok || monthTodo.Status != todoStatusOpen || !containsTodoDate(monthTodo.CompletedDates, "2026-07-11") || containsTodoDate(monthTodo.CompletedDates, "2026-07-12") {
		t.Fatalf("month payload should mark only completed date, got %#v", monthPayload.Items)
	}
}

func TestLegacyRepeatingDoneTodoStillShowsOpenOccurrences(t *testing.T) {
	router, _ := setupTodoTest(t)
	now := time.Now()
	item := models.TodoItem{
		ID:          "legacy-done",
		UserID:      "user-a",
		Title:       "Legacy done",
		Status:      todoStatusDone,
		StartDate:   "2026-07-01",
		DueDate:     "2026-07-31",
		RepeatRule:  todoRepeatDaily,
		Priority:    todoPriorityNormal,
		Source:      todoSourceManual,
		CompletedAt: &now,
		CreatedAt:   now,
		UpdatedAt:   now,
	}
	if err := database.DB.Create(&item).Error; err != nil {
		t.Fatalf("create legacy todo: %v", err)
	}

	req := httptest.NewRequest(http.MethodGet, "/api/todos?scope=today&date=2026-07-12&include_completed=false", nil)
	req.Header.Set("X-User-ID", "user-a")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)
	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, recorder.Body.String())
	}
	var payload struct {
		Items []todoResponse `json:"items"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	todo, ok := todoResponseByID(payload.Items, "legacy-done")
	if !ok || todo.Status != todoStatusOpen || todo.CompletedAt != nil {
		t.Fatalf("legacy repeating todo should render as open occurrence, got %#v", payload.Items)
	}
}

func TestTodoMonthScopeIncludesRepeatingAndRangedTodos(t *testing.T) {
	router, _ := setupTodoTest(t)
	now := time.Now()
	items := []models.TodoItem{
		{ID: "july-once", UserID: "user-a", Title: "July once", Status: todoStatusOpen, DueDate: "2026-07-11", RepeatRule: todoRepeatOnce, Priority: todoPriorityNormal, Source: todoSourceManual, CreatedAt: now, UpdatedAt: now},
		{ID: "july-range", UserID: "user-a", Title: "July range", Status: todoStatusOpen, StartDate: "2026-07-01", DueDate: "2026-07-05", RepeatRule: todoRepeatOnce, Priority: todoPriorityNormal, Source: todoSourceManual, CreatedAt: now, UpdatedAt: now},
		{ID: "july-daily", UserID: "user-a", Title: "July daily", Status: todoStatusOpen, StartDate: "2026-07-03", RepeatRule: todoRepeatDaily, Priority: todoPriorityNormal, Source: todoSourceManual, CreatedAt: now, UpdatedAt: now},
		{ID: "july-workdays", UserID: "user-a", Title: "July workdays", Status: todoStatusOpen, StartDate: "2026-07-01", DueDate: "2026-07-31", RepeatRule: todoRepeatWorkdays, Priority: todoPriorityNormal, Source: todoSourceManual, CreatedAt: now, UpdatedAt: now},
		{ID: "august-once", UserID: "user-a", Title: "August once", Status: todoStatusOpen, DueDate: "2026-08-01", RepeatRule: todoRepeatOnce, Priority: todoPriorityNormal, Source: todoSourceManual, CreatedAt: now, UpdatedAt: now},
	}
	if err := database.DB.Create(&items).Error; err != nil {
		t.Fatalf("create todos: %v", err)
	}

	req := httptest.NewRequest(http.MethodGet, "/api/todos?scope=month&start=2026-07-01&end=2026-07-31&include_completed=true", nil)
	req.Header.Set("X-User-ID", "user-a")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, req)
	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected month status %d: %s", recorder.Code, recorder.Body.String())
	}
	var payload struct {
		Items []todoResponse `json:"items"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode month response: %v", err)
	}
	ids := map[string]bool{}
	for _, item := range payload.Items {
		ids[item.ID] = true
	}
	for _, id := range []string{"july-once", "july-range", "july-daily", "july-workdays"} {
		if !ids[id] {
			t.Fatalf("expected %s in month payload, got %#v", id, payload.Items)
		}
	}
	if ids["august-once"] {
		t.Fatalf("did not expect august todo in July payload: %#v", payload.Items)
	}
}

func TestTodoSuggestionRefreshAcceptAndDismiss(t *testing.T) {
	router, _ := setupTodoTest(t)
	now := time.Now()
	messages := []models.Message{
		{
			ConversationID: "conv-a",
			UserID:         "user-a",
			Role:           "user",
			Content:        "明天继续优化 todo list 左侧导航和智能建议",
			CreatedAt:      now,
		},
		{
			ConversationID: "conv-a",
			UserID:         "user-a",
			Role:           "user",
			Content:        "记得明天提交周报",
			CreatedAt:      now.Add(time.Second),
		},
		{
			ConversationID: "conv-b",
			UserID:         "user-b",
			Role:           "user",
			Content:        "记得明天提交别人的周报",
			CreatedAt:      now,
		},
	}
	if err := database.DB.Create(&messages).Error; err != nil {
		t.Fatalf("create messages: %v", err)
	}

	refreshReq := httptest.NewRequest(http.MethodPost, "/api/todo-suggestions/refresh", bytes.NewBufferString(`{"limit":3}`))
	refreshReq.Header.Set("Content-Type", "application/json")
	refreshReq.Header.Set("X-User-ID", "user-a")
	refreshRecorder := httptest.NewRecorder()
	router.ServeHTTP(refreshRecorder, refreshReq)
	if refreshRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected refresh status %d: %s", refreshRecorder.Code, refreshRecorder.Body.String())
	}
	var refreshPayload struct {
		Suggestions []todoSuggestionResponse `json:"suggestions"`
	}
	if err := json.Unmarshal(refreshRecorder.Body.Bytes(), &refreshPayload); err != nil {
		t.Fatalf("decode suggestions: %v", err)
	}
	if len(refreshPayload.Suggestions) != 1 {
		t.Fatalf("expected one suggestion, got %#v", refreshPayload.Suggestions)
	}
	suggestion := refreshPayload.Suggestions[0]
	if suggestion.OriginConversationID != "conv-a" || suggestion.ProposedDueDate == "" {
		t.Fatalf("unexpected suggestion: %#v", suggestion)
	}

	var todoCount int64
	if err := database.DB.Model(&models.TodoItem{}).Where("user_id = ?", "user-a").Count(&todoCount).Error; err != nil {
		t.Fatalf("count todos: %v", err)
	}
	if todoCount != 0 {
		t.Fatalf("suggestions should not create todos automatically, got %d", todoCount)
	}

	acceptReq := httptest.NewRequest(http.MethodPost, "/api/todo-suggestions/"+suggestion.ID+"/accept", nil)
	acceptReq.Header.Set("X-User-ID", "user-a")
	acceptRecorder := httptest.NewRecorder()
	router.ServeHTTP(acceptRecorder, acceptReq)
	if acceptRecorder.Code != http.StatusOK {
		t.Fatalf("unexpected accept status %d: %s", acceptRecorder.Code, acceptRecorder.Body.String())
	}
	var acceptPayload struct {
		Todo       todoResponse           `json:"todo"`
		Suggestion todoSuggestionResponse `json:"suggestion"`
	}
	if err := json.Unmarshal(acceptRecorder.Body.Bytes(), &acceptPayload); err != nil {
		t.Fatalf("decode accepted suggestion: %v", err)
	}
	if acceptPayload.Todo.Source != todoSourceSuggestion || acceptPayload.Suggestion.State != todoSuggestionAccepted {
		t.Fatalf("unexpected accepted payload: %#v", acceptPayload)
	}

	dismissReq := httptest.NewRequest(http.MethodPost, "/api/todo-suggestions/"+suggestion.ID+"/dismiss", nil)
	dismissReq.Header.Set("X-User-ID", "user-a")
	dismissRecorder := httptest.NewRecorder()
	router.ServeHTTP(dismissRecorder, dismissReq)
	if dismissRecorder.Code != http.StatusOK {
		t.Fatalf("dismiss should be idempotent-ish enough for resolved suggestions, got %d: %s", dismissRecorder.Code, dismissRecorder.Body.String())
	}
}
