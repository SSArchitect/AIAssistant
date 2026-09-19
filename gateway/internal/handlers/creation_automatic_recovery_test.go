package handlers

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/models"
)

type recoveringDirector struct {
	*fakeAutomaticDirector
	failures int
	failure  *bridge.CreationMediaError
}

func (f *recoveringDirector) CreateMedia(ctx context.Context, req bridge.CreationNodeRequest) (*bridge.CreationNodeResponse, error) {
	if f.failures > 0 {
		f.failures--
		f.requests = append(f.requests, req)
		return nil, f.failure
	}
	return f.fakeAutomaticDirector.CreateMedia(ctx, req)
}

func TestAutomaticRecoversTemporaryImageErrorWithinSameLoop(t *testing.T) {
	r, h, base, token, row := setupAutomatic(t)
	f := &recoveringDirector{base, 1, &bridge.CreationMediaError{Code: "media_connection_failed", Message: "原任务连接中断", ProviderTaskID: "original-image", Retryable: true}}
	h.generator = f
	h.retryWait = func(context.Context, time.Duration) error { return nil }
	startAutomatic(t, r, h, token, row.ID, "auto-recover")
	row = waitAutomatic(t, h, row.ID)
	doc, _ := projectDocument(row)
	if row.AutomaticStatus != "completed" || len(f.requests) != 4 || len(doc.States["visual"].Candidates) != 2 {
		t.Fatal(row.AutomaticStatus, doc.Automation.Steps, len(f.requests))
	}
	if f.requests[0].IdempotencyKey != f.requests[1].IdempotencyKey || f.requests[1].ResumeTaskID != "original-image" {
		t.Fatal("recovery duplicated task", f.requests)
	}
}

func TestAutomaticContinueFindsOlderAcceptedImageBehindLaterFailedRun(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	row = reviewTestNode(t, r, h, token, row.ID, "brief", "")
	doc, _ := projectDocument(row)
	first, err := h.prepareProjectRun(row, doc, "visual", "old-image")
	if err != nil {
		t.Fatal(err)
	}
	progress := []creationProgress{{NodeID: "visual", Status: "failed", AssetIDs: []string{}, ErrorCode: "media_provider_error", ProviderTaskID: "accepted-image"}}
	h.db.Model(&models.CreationRun{}).Where("id = ?", first.run.ID).Updates(map[string]interface{}{"status": "failed", "progress": creationJSON(progress)})
	latest := first.run
	latest.ID = "later-failed-run"
	latest.Status = "failed"
	latest.RequestID = "later-request"
	progress[0].ProviderTaskID = ""
	latest.Progress = creationJSON(progress)
	latest.CreatedAt = time.Now()
	latest.UpdatedAt = time.Now()
	if err = h.db.Create(&latest).Error; err != nil {
		t.Fatal(err)
	}
	row = readTestProject(t, h, row.ID)
	doc, _ = projectDocument(row)
	state := doc.States["visual"]
	state.RunID = latest.ID
	doc.States["visual"] = state
	if err = h.updateProject(&row, doc, false); err != nil {
		t.Fatal(err)
	}
	startAutomatic(t, r, h, token, row.ID, "continue-old-task")
	row = waitAutomatic(t, h, row.ID)
	if row.AutomaticStatus != "completed" || f.requests[0].ResumeTaskID != "accepted-image" || f.requests[0].IdempotencyKey != fmt.Sprintf("creation-%s-0-0", first.run.ID) {
		t.Fatal(row.AutomaticStatus, f.requests)
	}
}

func TestAutomaticTakesOverRunningManualNodeWithoutSubmittingAgain(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	row = reviewTestNode(t, r, h, token, row.ID, "brief", "")
	entered, release := make(chan struct{}, 1), make(chan struct{})
	f.hook = func() {
		if len(f.requests) == 1 {
			entered <- struct{}{}
			<-release
		}
	}
	response := creationRequest(t, r, token, "POST", "/api/creation/projects/"+row.ID+"/generate", map[string]interface{}{"revision": row.Revision, "node_id": "visual", "request_id": "manual-active"})
	if response.Code != 202 {
		t.Fatal(response.Code, response.Body.String())
	}
	<-entered
	startAutomatic(t, r, h, token, row.ID, "takeover")
	startAutomatic(t, r, h, token, row.ID, "duplicate-takeover")
	if readTestProject(t, h, row.ID).AutomaticRequestID != "takeover" {
		t.Fatal("replaced running controller")
	}
	close(release)
	row = waitAutomatic(t, h, row.ID)
	if row.AutomaticStatus != "completed" || len(f.requests) != 3 {
		t.Fatal(row.AutomaticStatus, len(f.requests))
	}
	doc, _ := projectDocument(row)
	if len(doc.States["visual"].Candidates) != 2 {
		t.Fatal("duplicated adopted assets", doc.States)
	}
}

func TestAutomaticFailureReportsReasonAndDoesNotRetryAuthentication(t *testing.T) {
	r, h, base, token, row := setupAutomatic(t)
	f := &recoveringDirector{base, 5, &bridge.CreationMediaError{Code: "media_unauthorized", Message: "生成服务鉴权失败，请检查服务配置"}}
	h.generator = f
	startAutomatic(t, r, h, token, row.ID, "auth-error")
	row = waitAutomatic(t, h, row.ID)
	doc, _ := projectDocument(row)
	last := doc.Automation.Steps[len(doc.Automation.Steps)-1].Message
	if row.AutomaticStatus != "failed" || len(f.requests) != 1 || !strings.Contains(last, "鉴权") || strings.Contains(last, "当前节点未完成") {
		t.Fatal(last, len(f.requests))
	}
}

func TestAutomaticStopDuringRecoveryBackoffDoesNotRetry(t *testing.T) {
	r, h, base, token, row := setupAutomatic(t)
	f := &recoveringDirector{base, 5, &bridge.CreationMediaError{Code: "media_connection_failed", Message: "连接中断", Retryable: true}}
	h.generator = f
	entered := make(chan struct{}, 1)
	h.retryWait = func(ctx context.Context, _ time.Duration) error {
		entered <- struct{}{}
		<-ctx.Done()
		return ctx.Err()
	}
	startAutomatic(t, r, h, token, row.ID, "stop-reconnect")
	<-entered
	response := creationRequest(t, r, token, "POST", "/api/creation/projects/"+row.ID+"/automatic/stop", map[string]interface{}{})
	if response.Code != 200 {
		t.Fatal(response.Code)
	}
	row = waitAutomatic(t, h, row.ID)
	if row.AutomaticStatus != "cancelled" || len(f.requests) != 1 {
		t.Fatal(row.AutomaticStatus, len(f.requests))
	}
}

func TestRecoveredProgressAdoptsAssetsOnlyOnce(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	startAutomatic(t, r, h, token, row.ID, "complete")
	row = waitAutomatic(t, h, row.ID)
	doc, _ := projectDocument(row)
	var run models.CreationRun
	h.db.First(&run, "id = ?", doc.States["visual"].RunID)
	var progress []creationProgress
	_ = json.Unmarshal([]byte(run.Progress), &progress)
	h.finishProjectRun(run, progress)
	after, _ := projectDocument(readTestProject(t, h, row.ID))
	if len(after.States["visual"].Candidates) != 2 || len(f.requests) != 3 || !creativeApproved(after.States["visual"]) {
		t.Fatal("duplicate result invalidated state", after.States)
	}
}

func TestAutomaticRecoveryHasFiniteBudgetAndKeepsAcceptedTask(t *testing.T) {
	r, h, base, token, row := setupAutomatic(t)
	f := &recoveringDirector{base, 10, &bridge.CreationMediaError{Code: "media_download_failed", Message: "结果下载中断", ProviderTaskID: "same-task", Retryable: true}}
	h.generator = f
	h.retryWait = func(context.Context, time.Duration) error { return nil }
	startAutomatic(t, r, h, token, row.ID, "exhaust")
	row = waitAutomatic(t, h, row.ID)
	if row.AutomaticStatus != "failed" || len(f.requests) != 3 {
		t.Fatal(row.AutomaticStatus, len(f.requests))
	}
	for _, req := range f.requests {
		if req.IdempotencyKey != f.requests[0].IdempotencyKey {
			t.Fatal("created another task")
		}
	}
}

func TestAutomaticRecoversPartialCandidatesWithoutRepeatingSavedImage(t *testing.T) {
	r, h, base, token, row := setupAutomatic(t)
	row = reviewTestNode(t, r, h, token, row.ID, "brief", "")
	doc, _ := projectDocument(row)
	first, err := h.prepareProjectRun(row, doc, "visual", "partial")
	if err != nil {
		t.Fatal(err)
	}
	asset, err := h.saveAsset(row.UserID, "first.png", creationPNG, "image/png", "generated", first.run.ID, "visual", "first-task")
	if err != nil {
		t.Fatal(err)
	}
	progress := []creationProgress{{NodeID: "visual", Status: "failed", AssetIDs: []string{asset.ID}, ProviderTaskID: "second-task", Retryable: true, ErrorCode: "media_download_failed"}}
	h.db.Model(&models.CreationRun{}).Where("id = ?", first.run.ID).Updates(map[string]interface{}{"status": "failed", "progress": creationJSON(progress)})
	h.finishProjectRun(first.run, progress)
	startAutomatic(t, r, h, token, row.ID, "continue-partial")
	row = waitAutomatic(t, h, row.ID)
	if row.AutomaticStatus != "completed" || len(base.requests) != 2 || base.requests[0].ResumeTaskID != "second-task" || base.requests[0].IdempotencyKey != fmt.Sprintf("creation-%s-0-1", first.run.ID) {
		t.Fatal(row.AutomaticStatus, base.requests)
	}
	doc, _ = projectDocument(row)
	if len(doc.States["visual"].Candidates) != 2 || doc.States["visual"].Candidates[0] != asset.ID {
		t.Fatal(doc.States)
	}
	h.execute(first.run, first.graph, progress)
	if len(base.requests) != 2 {
		t.Fatal("executed completed task twice")
	}
}

func TestStoppedQueuedSubmissionNeverGeneratesOrBlocksFutureRuns(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	row = reviewTestNode(t, r, h, token, row.ID, "brief", "")
	doc, _ := projectDocument(row)
	submission, err := h.prepareProjectRun(row, doc, "visual", "queued")
	if err != nil {
		t.Fatal(err)
	}
	response := creationRequest(t, r, token, "POST", "/api/creation/runs/"+submission.run.ID+"/cancel", nil)
	if response.Code != 200 {
		t.Fatal(response.Code, response.Body.String())
	}
	h.execute(submission.run, submission.graph, submission.progress)
	var run models.CreationRun
	h.db.First(&run, "id = ?", submission.run.ID)
	if run.Status != "cancelled" || len(f.requests) != 0 {
		t.Fatal(run.Status, len(f.requests))
	}
}
