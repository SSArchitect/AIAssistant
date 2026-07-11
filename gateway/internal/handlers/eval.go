package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
)

const conversationEvalVersion = 2

type EvalHandler struct {
	projectRoot string
	dbPath      string
	agentURL    string
	mu          sync.Mutex
}

func NewEvalHandler(projectRoot string, dbPath string, agentURL string) *EvalHandler {
	return &EvalHandler{
		projectRoot: projectRoot,
		dbPath:      dbPath,
		agentURL:    strings.TrimRight(agentURL, "/"),
	}
}

type evalCollectRequest struct {
	Limit              int      `json:"limit,omitempty"`
	MaxContextMessages int      `json:"max_context_messages,omitempty"`
	UserID             string   `json:"user_id,omitempty"`
	ModelPreference    string   `json:"model_preference,omitempty"`
	ScenarioProfile    string   `json:"scenario_profile,omitempty"`
	QualityProfile     string   `json:"quality_profile,omitempty"`
	MinQualityScore    *float64 `json:"min_quality_score,omitempty"`
	UseLLM             *bool    `json:"use_llm,omitempty"`
	LLMMaxCandidates   int      `json:"llm_max_candidates,omitempty"`
}

type evalApproveRequest struct {
	Case map[string]interface{} `json:"case" binding:"required"`
}

type evalUpdateCaseRequest struct {
	Case map[string]interface{} `json:"case" binding:"required"`
}

type evalRunRequest struct {
	Mode            string `json:"mode,omitempty"`
	ModelPreference string `json:"model_preference,omitempty"`
}

func (h *EvalHandler) ConversationOverview(c *gin.Context) {
	candidates, _ := h.readJSON(h.candidatesPath(), emptyEvalPayload("candidates"))
	cases, _ := h.readJSON(h.casesPath(), emptyEvalPayload("cases"))
	report, _ := h.readJSON(h.latestReportPath(), map[string]interface{}{})
	runHistory, _ := h.readJSON(h.runHistoryPath(), emptyEvalPayload("runs"))

	c.JSON(http.StatusOK, gin.H{
		"candidate_count": evalItemCount(candidates, "candidates"),
		"case_count":      evalItemCount(cases, "cases"),
		"candidates":      candidates,
		"cases":           cases,
		"latest_report":   report,
		"run_history":     runHistory,
		"paths": gin.H{
			"candidates":  h.candidatesPath(),
			"cases":       h.casesPath(),
			"report":      h.latestReportPath(),
			"run_history": h.runHistoryPath(),
		},
	})
}

func (h *EvalHandler) ConversationCandidates(c *gin.Context) {
	payload, err := h.readJSON(h.candidatesPath(), emptyEvalPayload("candidates"))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to read candidates: " + err.Error()})
		return
	}
	c.JSON(http.StatusOK, payload)
}

func (h *EvalHandler) CollectConversationCandidates(c *gin.Context) {
	var req evalCollectRequest
	_ = c.ShouldBindJSON(&req)
	userID := requestUserIDWithBody(c, req.UserID)
	limit := req.Limit
	if limit <= 0 {
		limit = 80
	}
	maxContextMessages := req.MaxContextMessages
	if maxContextMessages <= 0 {
		maxContextMessages = 8
	}
	scenarioProfile := normalizeEvalScenarioProfile(req.ScenarioProfile)
	qualityProfile := normalizeEvalQualityProfile(req.QualityProfile)

	h.mu.Lock()
	defer h.mu.Unlock()

	if err := os.MkdirAll(filepath.Dir(h.candidatesPath()), 0755); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to create eval directory: " + err.Error()})
		return
	}

	collectTimeout := 90 * time.Second
	if req.UseLLM == nil || *req.UseLLM {
		collectTimeout = 8 * time.Minute
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), collectTimeout)
	defer cancel()
	cmd := exec.CommandContext(
		ctx,
		"python3",
		filepath.Join(h.projectRoot, "scripts", "collect_conversation_eval_cases.py"),
		"--local-db",
		h.dbPath,
		"--output",
		h.candidatesPath(),
		"--user-id",
		userID,
		"--limit",
		strconv.Itoa(limit),
		"--max-context-messages",
		strconv.Itoa(maxContextMessages),
		"--scenario-profile",
		scenarioProfile,
		"--quality-profile",
		qualityProfile,
	)
	if req.MinQualityScore != nil {
		cmd.Args = append(cmd.Args, "--min-quality-score", fmt.Sprintf("%.3f", *req.MinQualityScore))
	}
	if req.UseLLM == nil || *req.UseLLM {
		llmMaxCandidates := req.LLMMaxCandidates
		if llmMaxCandidates <= 0 {
			llmMaxCandidates = 4
		}
		if limit > 0 && llmMaxCandidates > limit {
			llmMaxCandidates = limit
		}
		if llmMaxCandidates > 48 {
			llmMaxCandidates = 48
		}
		cmd.Args = append(cmd.Args, "--llm", "--llm-max-candidates", strconv.Itoa(llmMaxCandidates))
		if strings.TrimSpace(req.ModelPreference) != "" {
			cmd.Args = append(cmd.Args, "--model-preference", strings.TrimSpace(req.ModelPreference))
		}
	}
	cmd.Dir = h.projectRoot
	output, err := cmd.CombinedOutput()
	if ctx.Err() == context.DeadlineExceeded {
		c.JSON(http.StatusGatewayTimeout, gin.H{"error": "conversation eval collection timed out"})
		return
	}
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error":  "conversation eval collection failed: " + err.Error(),
			"output": string(output),
		})
		return
	}

	payload, readErr := h.readJSON(h.candidatesPath(), emptyEvalPayload("candidates"))
	if readErr != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "collection completed but candidates could not be read: " + readErr.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{
		"status":     "ok",
		"output":     strings.TrimSpace(string(output)),
		"candidates": payload,
	})
}

func (h *EvalHandler) ConversationCases(c *gin.Context) {
	payload, err := h.readJSON(h.casesPath(), emptyEvalPayload("cases"))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to read cases: " + err.Error()})
		return
	}
	c.JSON(http.StatusOK, payload)
}

func (h *EvalHandler) ConversationRunReport(c *gin.Context) {
	runID := strings.TrimSpace(c.Param("id"))
	if runID == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "run id is required"})
		return
	}
	if filepath.Base(runID) != runID {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid run id"})
		return
	}
	data, err := os.ReadFile(h.runReportPath(runID))
	if errors.Is(err, os.ErrNotExist) {
		c.JSON(http.StatusNotFound, gin.H{"error": "eval report not found"})
		return
	}
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to read eval report: " + err.Error()})
		return
	}
	var payload map[string]interface{}
	if err := json.Unmarshal(data, &payload); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to parse eval report: " + err.Error()})
		return
	}
	c.JSON(http.StatusOK, payload)
}

func (h *EvalHandler) UpdateConversationCandidate(c *gin.Context) {
	h.updateConversationEvalItem(c, h.candidatesPath(), "candidates", false)
}

func (h *EvalHandler) UpdateConversationCase(c *gin.Context) {
	h.updateConversationEvalItem(c, h.casesPath(), "cases", true)
}

func (h *EvalHandler) ApproveConversationCase(c *gin.Context) {
	var req evalApproveRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}
	caseID := strings.TrimSpace(fmt.Sprint(req.Case["id"]))
	if caseID == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "case id is required"})
		return
	}

	h.mu.Lock()
	defer h.mu.Unlock()

	payload, err := h.readJSON(h.casesPath(), emptyEvalPayload("cases"))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to read cases: " + err.Error()})
		return
	}
	req.Case["status"] = "approved"
	metadata, _ := req.Case["metadata"].(map[string]interface{})
	if metadata == nil {
		metadata = map[string]interface{}{}
	}
	metadata["approved_at"] = time.Now().UTC().Format(time.RFC3339)
	metadata["approved_by"] = requestUserID(c)
	req.Case["metadata"] = metadata

	cases := evalItems(payload, "cases")
	updated := false
	for index, item := range cases {
		if strings.TrimSpace(fmt.Sprint(item["id"])) == caseID {
			cases[index] = req.Case
			updated = true
			break
		}
	}
	if !updated {
		cases = append(cases, req.Case)
	}
	payload["version"] = conversationEvalVersion
	payload["updated_at"] = time.Now().UTC().Format(time.RFC3339)
	payload["case_count"] = len(cases)
	payload["cases"] = cases

	if err := h.writeJSON(h.casesPath(), payload); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to write cases: " + err.Error()})
		return
	}
	c.JSON(http.StatusOK, payload)
}

func (h *EvalHandler) updateConversationEvalItem(c *gin.Context, path string, key string, approved bool) {
	caseID := strings.TrimSpace(c.Param("id"))
	if caseID == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "case id is required"})
		return
	}
	var req evalUpdateCaseRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}
	bodyID := strings.TrimSpace(fmt.Sprint(req.Case["id"]))
	if bodyID == "" {
		req.Case["id"] = caseID
	} else if bodyID != caseID {
		c.JSON(http.StatusBadRequest, gin.H{"error": "case id cannot be changed"})
		return
	}

	h.mu.Lock()
	defer h.mu.Unlock()

	payload, err := h.readJSON(path, emptyEvalPayload(key))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to read eval items: " + err.Error()})
		return
	}
	items := evalItems(payload, key)
	updated := false
	for index, item := range items {
		if strings.TrimSpace(fmt.Sprint(item["id"])) == caseID {
			req.Case["status"] = "candidate"
			if approved {
				req.Case["status"] = "approved"
			}
			metadata, _ := req.Case["metadata"].(map[string]interface{})
			if metadata == nil {
				metadata = map[string]interface{}{}
			}
			metadata["edited_at"] = time.Now().UTC().Format(time.RFC3339)
			metadata["edited_by"] = requestUserID(c)
			req.Case["metadata"] = metadata
			items[index] = req.Case
			updated = true
			break
		}
	}
	if !updated {
		c.JSON(http.StatusNotFound, gin.H{"error": "case not found"})
		return
	}
	payload["version"] = conversationEvalVersion
	payload["updated_at"] = time.Now().UTC().Format(time.RFC3339)
	payload[strings.TrimSuffix(key, "s")+"_count"] = len(items)
	payload[key] = items
	if err := h.writeJSON(path, payload); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to write eval items: " + err.Error()})
		return
	}
	c.JSON(http.StatusOK, payload)
}

func (h *EvalHandler) DeleteConversationCase(c *gin.Context) {
	caseID := strings.TrimSpace(c.Param("id"))
	if caseID == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "case id is required"})
		return
	}

	h.mu.Lock()
	defer h.mu.Unlock()

	payload, err := h.readJSON(h.casesPath(), emptyEvalPayload("cases"))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to read cases: " + err.Error()})
		return
	}
	cases := evalItems(payload, "cases")
	next := make([]map[string]interface{}, 0, len(cases))
	removed := false
	for _, item := range cases {
		if strings.TrimSpace(fmt.Sprint(item["id"])) == caseID {
			removed = true
			continue
		}
		next = append(next, item)
	}
	if !removed {
		c.JSON(http.StatusNotFound, gin.H{"error": "case not found"})
		return
	}
	payload["updated_at"] = time.Now().UTC().Format(time.RFC3339)
	payload["case_count"] = len(next)
	payload["cases"] = next
	if err := h.writeJSON(h.casesPath(), payload); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to write cases: " + err.Error()})
		return
	}
	c.JSON(http.StatusOK, payload)
}

func (h *EvalHandler) RunConversationEval(c *gin.Context) {
	var req evalRunRequest
	_ = c.ShouldBindJSON(&req)
	mode := strings.TrimSpace(req.Mode)
	if mode == "" {
		mode = "historical"
	}
	if mode != "historical" && mode != "agent" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "eval mode must be historical or agent"})
		return
	}

	h.mu.Lock()
	defer h.mu.Unlock()

	timeout := 90 * time.Second
	if mode == "agent" {
		timeout = 30 * time.Minute
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), timeout)
	defer cancel()
	args := []string{
		"python3",
		filepath.Join(h.projectRoot, "scripts", "eval_conversation.py"),
		"--cases",
		h.casesPath(),
		"--mode",
		mode,
		"--json",
		"--no-fail",
		"--output",
		h.latestReportPath(),
	}
	if mode == "agent" {
		agentURL := h.agentURL
		if agentURL == "" {
			agentURL = "http://127.0.0.1:9090"
		}
		args = append(
			args,
			"--endpoint",
			agentURL+"/agent/chat",
			"--user-id",
			"__eval__",
		)
		if strings.TrimSpace(req.ModelPreference) != "" {
			args = append(args, "--model-preference", strings.TrimSpace(req.ModelPreference))
		}
	}
	cmd := exec.CommandContext(ctx, args[0], args[1:]...)
	cmd.Dir = h.projectRoot
	output, err := cmd.CombinedOutput()
	if ctx.Err() == context.DeadlineExceeded {
		c.JSON(http.StatusGatewayTimeout, gin.H{"error": "conversation eval timed out"})
		return
	}
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error":  "conversation eval failed: " + err.Error(),
			"output": string(output),
		})
		return
	}
	report, readErr := h.readJSON(h.latestReportPath(), map[string]interface{}{})
	if readErr != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "eval completed but report could not be read: " + readErr.Error()})
		return
	}
	runID := "eval_" + time.Now().UTC().Format("20060102T150405.000000000Z")
	report["run_id"] = runID
	report["completed_at"] = time.Now().UTC().Format(time.RFC3339Nano)
	report["stdout"] = strings.TrimSpace(string(output))
	if err := h.writeJSON(h.latestReportPath(), report); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "eval completed but latest report could not be updated: " + err.Error()})
		return
	}
	if err := h.writeJSON(h.runReportPath(runID), report); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "eval completed but run report could not be written: " + err.Error()})
		return
	}
	runHistory, err := h.appendRunHistory(report)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "eval completed but run history could not be written: " + err.Error()})
		return
	}
	report["run_history"] = runHistory
	c.JSON(http.StatusOK, report)
}

func (h *EvalHandler) candidatesPath() string {
	return filepath.Join(h.projectRoot, "evals", "conversation", "candidates.json")
}

func (h *EvalHandler) casesPath() string {
	return filepath.Join(h.projectRoot, "evals", "conversation", "cases.json")
}

func (h *EvalHandler) latestReportPath() string {
	return filepath.Join(h.projectRoot, "evals", "conversation", "latest_report.json")
}

func (h *EvalHandler) runHistoryPath() string {
	return filepath.Join(h.projectRoot, "evals", "conversation", "run_history.json")
}

func (h *EvalHandler) runReportsDir() string {
	return filepath.Join(h.projectRoot, "evals", "conversation", "runs")
}

func (h *EvalHandler) runReportPath(runID string) string {
	return filepath.Join(h.runReportsDir(), filepath.Base(runID)+".json")
}

func (h *EvalHandler) appendRunHistory(report map[string]interface{}) (map[string]interface{}, error) {
	payload, err := h.readJSON(h.runHistoryPath(), emptyEvalPayload("runs"))
	if err != nil {
		return nil, err
	}
	runs := evalItems(payload, "runs")
	runs = append([]map[string]interface{}{compactEvalRun(report)}, runs...)
	if len(runs) > 30 {
		runs = runs[:30]
	}
	payload["version"] = conversationEvalVersion
	payload["updated_at"] = time.Now().UTC().Format(time.RFC3339Nano)
	payload["run_count"] = len(runs)
	payload["runs"] = runs
	if err := h.writeJSON(h.runHistoryPath(), payload); err != nil {
		return nil, err
	}
	return payload, nil
}

func (h *EvalHandler) readJSON(path string, fallback map[string]interface{}) (map[string]interface{}, error) {
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return fallback, nil
	}
	if err != nil {
		return nil, err
	}
	if len(strings.TrimSpace(string(data))) == 0 {
		return fallback, nil
	}
	var payload map[string]interface{}
	if err := json.Unmarshal(data, &payload); err != nil {
		return nil, err
	}
	return payload, nil
}

func (h *EvalHandler) writeJSON(path string, payload map[string]interface{}) error {
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(payload, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	return os.WriteFile(path, data, 0644)
}

func compactEvalRun(report map[string]interface{}) map[string]interface{} {
	summary, _ := report["summary"].(map[string]interface{})
	replay, _ := report["replay"].(map[string]interface{})
	runID := strings.TrimSpace(fmt.Sprint(report["run_id"]))
	return map[string]interface{}{
		"run_id":       runID,
		"generated_at": report["generated_at"],
		"completed_at": report["completed_at"],
		"mode":         report["mode"],
		"replay":       replay,
		"summary":      summary,
		"report_path":  filepath.ToSlash(filepath.Join("evals", "conversation", "runs", runID+".json")),
	}
}

func normalizeEvalScenarioProfile(value string) string {
	switch strings.TrimSpace(value) {
	case "default_qa", "deep_research", "tool_use", "coding":
		return strings.TrimSpace(value)
	default:
		return "all"
	}
}

func normalizeEvalQualityProfile(value string) string {
	switch strings.TrimSpace(value) {
	case "high_recall", "high_precision":
		return strings.TrimSpace(value)
	default:
		return "balanced"
	}
}

func emptyEvalPayload(key string) map[string]interface{} {
	return map[string]interface{}{
		"version": conversationEvalVersion,
		key:       []map[string]interface{}{},
	}
}

func evalItemCount(payload map[string]interface{}, key string) int {
	if count, ok := payload[key[:len(key)-1]+"_count"].(float64); ok {
		return int(count)
	}
	return len(evalItems(payload, key))
}

func evalItems(payload map[string]interface{}, key string) []map[string]interface{} {
	raw, ok := payload[key].([]interface{})
	if !ok {
		if typed, ok := payload[key].([]map[string]interface{}); ok {
			return typed
		}
		return []map[string]interface{}{}
	}
	items := make([]map[string]interface{}, 0, len(raw))
	for _, item := range raw {
		if typed, ok := item.(map[string]interface{}); ok {
			items = append(items, typed)
		}
	}
	return items
}
