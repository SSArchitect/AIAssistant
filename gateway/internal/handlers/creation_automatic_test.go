package handlers

import (
	"context"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
)

type fakeAutomaticDirector struct {
	fakeCreativePlanner
	reviews    []bridge.CreationReviewRequest
	reviewHook func(bridge.CreationReviewRequest)
	badChoice  bool
}

func (f *fakeAutomaticDirector) ReviewCreation(ctx context.Context, req bridge.CreationReviewRequest) (*bridge.CreationReviewResponse, error) {
	f.reviews = append(f.reviews, req)
	if f.reviewHook != nil {
		f.reviewHook(req)
	}
	result := &bridge.CreationReviewResponse{Decision: "approve", Reason: "内容符合已确认的创作要求"}
	if len(req.CandidateIDs) > 0 {
		result.Decision = "select"
		result.AssetID = req.CandidateIDs[len(req.CandidateIDs)-1]
	}
	if f.badChoice {
		result.Decision = "select"
		result.AssetID = "another-account"
	}
	return result, nil
}
func setupAutomatic(t *testing.T) (*gin.Engine, *CreationHandler, *fakeAutomaticDirector, string, models.CreationProject) {
	r, h, _, token := setupCreation(t)
	f := &fakeAutomaticDirector{}
	h.generator = f
	row := seedCreativePlan(t, h, createTestProject(t, r, token))
	return r, h, f, token, row
}
func startAutomatic(t *testing.T, r *gin.Engine, h *CreationHandler, token, id, key string) {
	t.Helper()
	row := readTestProject(t, h, id)
	response := creationRequest(t, r, token, "POST", "/api/creation/projects/"+id+"/automatic", map[string]interface{}{"revision": row.Revision, "request_id": key})
	if response.Code != 202 {
		t.Fatal(response.Code, response.Body.String())
	}
}
func waitAutomatic(t *testing.T, h *CreationHandler, id string) models.CreationProject {
	t.Helper()
	deadline := time.Now().Add(4 * time.Second)
	for time.Now().Before(deadline) {
		row := readTestProject(t, h, id)
		if !automaticActive(row.AutomaticStatus) {
			return row
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatal("automatic workflow did not finish")
	return models.CreationProject{}
}
func TestAutomaticCreationPreservesUserApprovalsChoosesCandidateAndCompletesOnce(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	row = reviewTestNode(t, r, h, token, row.ID, "brief", "")
	row = reviewTestNode(t, r, h, token, row.ID, "script", "")
	before, _ := projectDocument(row)
	startAutomatic(t, r, h, token, row.ID, "auto-1")
	row = waitAutomatic(t, h, row.ID)
	doc, _ := projectDocument(row)
	if row.AutomaticStatus != "completed" {
		t.Fatal(row.AutomaticStatus, doc.Automation.Steps)
	}
	for _, id := range []string{"brief", "script"} {
		if !reflect.DeepEqual(before.States[id], doc.States[id]) {
			t.Fatal("overwrote user approval", id)
		}
	}
	if len(f.requests) != 3 || f.requests[2].Kind != "video" || len(f.requests[2].InputImages) != 1 {
		t.Fatal(f.requests)
	}
	if doc.States["visual"].SelectedAssetID != doc.States["visual"].Candidates[1] || doc.States["visual"].ApprovedBy != "agent" {
		t.Fatal(doc.States)
	}
	for _, review := range f.reviews {
		if review.NodeID == "brief" || review.NodeID == "script" {
			t.Fatal("re-reviewed confirmed node")
		}
	}
	if !creativeApproved(doc.States["video"]) {
		t.Fatal("generation revoked approved video")
	}
	// Reusing the request ID and starting a fresh completion pass must not pay again.
	response := creationRequest(t, r, token, "POST", "/api/creation/projects/"+row.ID+"/automatic", map[string]interface{}{"revision": 1, "request_id": "auto-1"})
	if response.Code != 200 {
		t.Fatal(response.Code)
	}
	startAutomatic(t, r, h, token, row.ID, "auto-2")
	waitAutomatic(t, h, row.ID)
	if len(f.requests) != 3 {
		t.Fatal("regenerated completed media")
	}
}
func TestAutomaticCreationStopsLateReviewAndRejectsConcurrentMutations(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	entered := make(chan struct{}, 1)
	release := make(chan struct{})
	f.reviewHook = func(bridge.CreationReviewRequest) { entered <- struct{}{}; <-release }
	startAutomatic(t, r, h, token, row.ID, "auto-stop")
	<-entered
	current := readTestProject(t, h, row.ID)
	for _, path := range []string{"review", "generate", "messages"} {
		response := creationRequest(t, r, token, "POST", "/api/creation/projects/"+row.ID+"/"+path, map[string]interface{}{"revision": current.Revision, "node_id": "brief", "message": "change", "request_id": "manual"})
		if response.Code != 409 {
			t.Fatal(path, response.Code, response.Body.String())
		}
	}
	duplicate := creationRequest(t, r, token, "POST", "/api/creation/projects/"+row.ID+"/automatic", map[string]interface{}{"revision": 1, "request_id": "auto-stop"})
	if duplicate.Code != 200 {
		t.Fatal(duplicate.Code)
	}
	other := seedCreativePlan(t, h, createTestProject(t, r, token))
	busy := creationRequest(t, r, token, "POST", "/api/creation/projects/"+other.ID+"/automatic", map[string]interface{}{"revision": other.Revision, "request_id": "other"})
	if busy.Code != 409 {
		t.Fatal("account reservation missing")
	}
	bob, _ := createAccountSession("bob")
	denied := creationRequest(t, r, bob, "POST", "/api/creation/projects/"+row.ID+"/automatic/stop", map[string]interface{}{})
	if denied.Code != 404 {
		t.Fatal("foreign stop allowed")
	}
	stop := creationRequest(t, r, token, "POST", "/api/creation/projects/"+row.ID+"/automatic/stop", map[string]interface{}{})
	if stop.Code != 200 {
		t.Fatal(stop.Code)
	}
	close(release)
	row = waitAutomatic(t, h, row.ID)
	doc, _ := projectDocument(row)
	if row.AutomaticStatus != "cancelled" || creativeApproved(doc.States["brief"]) || len(f.requests) != 0 {
		t.Fatal("late review applied after stop")
	}
}
func TestAutomaticCreationFailedPartialImagesResumeWithoutGeneratingThemAgain(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	f.failAt = 2
	startAutomatic(t, r, h, token, row.ID, "partial")
	row = waitAutomatic(t, h, row.ID)
	doc, _ := projectDocument(row)
	if row.AutomaticStatus != "failed" || len(doc.States["visual"].Candidates) != 1 || len(f.requests) != 2 {
		t.Fatal("partial output lost", doc.Automation.Steps)
	}
	f.failAt = 0
	startAutomatic(t, r, h, token, row.ID, "resume")
	row = waitAutomatic(t, h, row.ID)
	if row.AutomaticStatus != "completed" || len(f.requests) != 3 || f.requests[2].Kind != "video" {
		t.Fatal("partial images were generated again", f.requests)
	}
}
func TestAutomaticCreationStopDuringMediaArchivesCurrentOutputOnly(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	entered := make(chan struct{}, 1)
	release := make(chan struct{})
	f.hook = func() { entered <- struct{}{}; <-release }
	startAutomatic(t, r, h, token, row.ID, "stop-media")
	<-entered
	response := creationRequest(t, r, token, "POST", "/api/creation/projects/"+row.ID+"/automatic/stop", map[string]interface{}{})
	if response.Code != 200 {
		t.Fatal(response.Code)
	}
	close(release)
	row = waitAutomatic(t, h, row.ID)
	doc, _ := projectDocument(row)
	if row.AutomaticStatus != "cancelled" || len(f.requests) != 1 || len(doc.States["visual"].Candidates) != 1 {
		t.Fatal("lost output or started extra task", doc)
	}
}
func TestAutomaticCreationRejectsForeignCandidateWithoutGenerating(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	f.badChoice = true
	startAutomatic(t, r, h, token, row.ID, "bad-choice")
	row = waitAutomatic(t, h, row.ID)
	if row.AutomaticStatus != "failed" || len(f.requests) != 0 {
		t.Fatal("invalid reviewer decision accepted")
	}
}
func TestAutomaticCreationProtectsConfirmedNodesFromDirectionReplanning(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	row = reviewTestNode(t, r, h, token, row.ID, "brief", "")
	doc, _ := projectDocument(row)
	doc.Plan.Questions = []bridge.CreativeQuestion{{Question: "选择氛围", Options: []string{"温暖", "冷峻"}}}
	if err := h.updateProject(&row, doc, false); err != nil {
		t.Fatal(err)
	}
	plan := creativeTestPlan()
	plan.Nodes[0].Content = "changed confirmed brief"
	f.response = &bridge.CreationPlanningResponse{Plan: plan, Reply: "changed"}
	startAutomatic(t, r, h, token, row.ID, "bad-plan")
	row = waitAutomatic(t, h, row.ID)
	after, _ := projectDocument(row)
	if row.AutomaticStatus != "failed" || after.Plan.Nodes[0].Content != doc.Plan.Nodes[0].Content || len(f.requests) != 0 {
		t.Fatal("confirmed content overwritten")
	}
}

func TestAutomaticCreationShowsConfigurationFailureAndCanContinue(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	row = reviewTestNode(t, r, h, token, row.ID, "brief", "")
	doc, _ := projectDocument(row)
	doc.Plan.Questions = []bridge.CreativeQuestion{{Question: "选择氛围", Options: []string{"温暖", "冷峻"}}}
	if err := h.updateProject(&row, doc, false); err != nil {
		t.Fatal(err)
	}
	f.err = &bridge.CreationPlanningError{Message: "创作服务配置同步失败，原有内容已保留，请稍后重试"}
	startAutomatic(t, r, h, token, row.ID, "missing-config")
	row = waitAutomatic(t, h, row.ID)
	after, _ := projectDocument(row)
	if row.AutomaticStatus != "failed" || !strings.Contains(after.Messages[len(after.Messages)-1].Content, "配置同步失败") || !reflect.DeepEqual(after.States["brief"], doc.States["brief"]) || len(f.requests) != 0 {
		t.Fatal("configuration error hidden or existing work changed")
	}
	f.err = nil
	f.response = &bridge.CreationPlanningResponse{Plan: creativeTestPlan(), Reply: "方向已确定"}
	startAutomatic(t, r, h, token, row.ID, "restored-config")
	row = waitAutomatic(t, h, row.ID)
	if row.AutomaticStatus != "completed" || len(f.requests) != 3 {
		t.Fatal("resume failed", row.AutomaticStatus)
	}
}
func TestAutomaticCreationRecoverMarksInterruptedWithoutResubmitting(t *testing.T) {
	_, h, f, _, row := setupAutomatic(t)
	doc, _ := projectDocument(row)
	row.AutomaticStatus = "running"
	row.AutomaticRequestID = "restart"
	doc.Automation = &creativeAutomation{CreativePlanningActivity: bridge.CreativePlanningActivity{ID: "restart", Status: "running", StartedAt: time.Now()}}
	if err := h.updateProject(&row, doc, false); err != nil {
		t.Fatal(err)
	}
	if err := h.Recover(); err != nil {
		t.Fatal(err)
	}
	row = readTestProject(t, h, row.ID)
	if row.AutomaticStatus != "interrupted" || len(f.requests) != 0 || len(f.reviews) != 0 {
		t.Fatal("restart resubmitted work")
	}
}
func TestAutomaticCreationKeepsUserSelectedImageAndVideoConfirmation(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	row = reviewTestNode(t, r, h, token, row.ID, "brief", "")
	row = reviewTestNode(t, r, h, token, row.ID, "script", "")
	asset, err := h.saveAsset(row.UserID, "chosen.png", creationPNG, "image/png", "upload", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	doc, _ := projectDocument(row)
	state := doc.States["visual"]
	state.Candidates = []string{asset.ID}
	doc.States["visual"] = state
	if err = h.updateProject(&row, doc, false); err != nil {
		t.Fatal(err)
	}
	row = reviewTestNode(t, r, h, token, row.ID, "visual", asset.ID)
	row = reviewTestNode(t, r, h, token, row.ID, "video", "")
	before, _ := projectDocument(row)
	startAutomatic(t, r, h, token, row.ID, "confirmed-video")
	row = waitAutomatic(t, h, row.ID)
	after, _ := projectDocument(row)
	if row.AutomaticStatus != "completed" || len(f.reviews) != 0 || len(f.requests) != 1 || f.requests[0].Kind != "video" {
		t.Fatal("did not reuse decisions")
	}
	if !reflect.DeepEqual(before.States["visual"], after.States["visual"]) || after.States["video"].ApprovedBy != "user" {
		t.Fatal("user decision overwritten")
	}
}

func TestAutomaticCreationRejectsReferenceChangedDuringReview(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	row = reviewTestNode(t, r, h, token, row.ID, "brief", "")
	asset, err := h.saveAsset(row.UserID, "reference.png", creationPNG, "image/png", "upload", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	doc, _ := projectDocument(row)
	s := doc.States["visual"]
	s.Candidates = []string{asset.ID}
	doc.States["visual"] = s
	if err = h.updateProject(&row, doc, false); err != nil {
		t.Fatal(err)
	}
	f.reviewHook = func(req bridge.CreationReviewRequest) {
		if req.NodeID == "visual" {
			if err := h.db.Model(&models.DriveItem{}).Where("id = ?", asset.DriveItemID).Update("content", "changed").Error; err != nil {
				t.Error(err)
			}
		}
	}
	startAutomatic(t, r, h, token, row.ID, "changed-reference")
	row = waitAutomatic(t, h, row.ID)
	doc, _ = projectDocument(row)
	last := doc.Automation.Steps[len(doc.Automation.Steps)-1]
	if row.AutomaticStatus != "failed" || creativeApproved(doc.States["visual"]) || len(f.requests) != 0 || !strings.Contains(last.Message, "图片发生变化") {
		t.Fatal("changed image approved", last)
	}
}

func TestAutomaticCreationResolvesQuestionsWithExistingSelectionsAndKeepsApprovals(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	row = reviewTestNode(t, r, h, token, row.ID, "brief", "")
	asset, err := h.saveAsset(row.UserID, "reference.png", creationPNG, "image/png", "generated", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	doc, _ := projectDocument(row)
	s := doc.States["visual"]
	s.Candidates = []string{asset.ID}
	s.SelectedAssetID = asset.ID
	doc.States["visual"] = s
	doc.Plan.Questions = []bridge.CreativeQuestion{{Question: "氛围", Options: []string{"温暖", "冷峻"}}}
	if err = h.updateProject(&row, doc, false); err != nil {
		t.Fatal(err)
	}
	f.called = make(chan bridge.CreationPlanningRequest, 1)
	p := doc.Plan
	p.Questions = []bridge.CreativeQuestion{}
	f.response = &bridge.CreationPlanningResponse{Plan: p, Reply: "依据简报确定温暖氛围"}
	startAutomatic(t, r, h, token, row.ID, "resolve-question")
	row = waitAutomatic(t, h, row.ID)
	after, _ := projectDocument(row)
	req := <-f.called
	if row.AutomaticStatus != "completed" || len(req.Assets) != 1 || req.Assets[0].ID != asset.ID || !reflect.DeepEqual(doc.States["brief"], after.States["brief"]) {
		t.Fatal("lost approved context", after.Automation.Steps)
	}
}
