package handlers

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"image"
	"image/color"
	"image/png"
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
	reviews        []bridge.CreationReviewRequest
	reviewHook     func(bridge.CreationReviewRequest)
	badChoice      bool
	reviewDecision func(bridge.CreationReviewRequest) *bridge.CreationReviewResponse
	planHook       func(context.Context, bridge.CreationPlanningRequest) (*bridge.CreationPlanningResponse, error)
}

func (f *fakeAutomaticDirector) ReviewCreation(ctx context.Context, req bridge.CreationReviewRequest) (*bridge.CreationReviewResponse, error) {
	f.reviews = append(f.reviews, req)
	if f.reviewHook != nil {
		f.reviewHook(req)
	}
	if f.reviewDecision != nil {
		if result := f.reviewDecision(req); result != nil {
			return result, nil
		}
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

func (f *fakeAutomaticDirector) PlanCreation(ctx context.Context, req bridge.CreationPlanningRequest) (*bridge.CreationPlanningResponse, error) {
	if f.planHook != nil {
		return f.planHook(ctx, req)
	}
	return f.fakeCreativePlanner.PlanCreation(ctx, req)
}
func copyAutomaticPlan(plan bridge.CreativePlan) bridge.CreativePlan {
	var result bridge.CreativePlan
	_ = json.Unmarshal([]byte(creationJSON(plan)), &result)
	return result
}

func TestAutomaticRepairPreservesLockedStoryboardAcrossJSONEncodings(t *testing.T) {
	plan := creativeTestPlan()
	plan.Nodes[3].Storyboard = json.RawMessage(`{"summary":"\u003cSubject 1\u003e","duration":5}`)
	doc := creativeDocument{Plan: plan, Automation: &creativeAutomation{}}
	repaired := copyAutomaticPlan(plan)
	repaired.Nodes[3].Storyboard = json.RawMessage("{\n\"duration\":5.0,\"summary\":\"<Subject 1>\"}")
	repaired.Nodes[2].Storyboard = json.RawMessage("null")
	req := bridge.CreationPlanningRequest{LockedNodeIDs: []string{"video", "script"}, Repair: &bridge.CreationRepairFeedback{NodeID: "visual"}}
	if err := validateAutomaticRepair(doc, repaired, req); err != nil {
		t.Fatal("unchanged storyboard rejected", err)
	}
	if !reflect.DeepEqual(repaired.Nodes[3], plan.Nodes[3]) {
		t.Fatal("locked node not preserved byte-for-byte")
	}
	if !reflect.DeepEqual(repaired.Nodes[2], plan.Nodes[2]) {
		t.Fatal("absent storyboard differs from null")
	}
	repaired.Nodes[3].Prompt = "changed execution prompt"
	if validateAutomaticRepair(doc, repaired, req) == nil {
		t.Fatal("real locked-node edit accepted")
	}
}

func TestAutomaticRepairCanAddSceneThenContinueGeneration(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	f.imageContent = func(req bridge.CreationNodeRequest) string {
		if req.Prompt != "empty glowing cave" {
			return creationPNG
		}
		picture := image.NewRGBA(image.Rect(0, 0, 1, 1))
		picture.Set(0, 0, color.RGBA{B: 180, A: 255})
		var out bytes.Buffer
		if err := png.Encode(&out, picture); err != nil {
			t.Fatal(err)
		}
		return base64.StdEncoding.EncodeToString(out.Bytes())
	}
	repaired := false
	f.reviewDecision = func(req bridge.CreationReviewRequest) *bridge.CreationReviewResponse {
		if req.NodeID == "video" && !repaired {
			return &bridge.CreationReviewResponse{Decision: "revise", Reason: "缺少后半段洞穴场景"}
		}
		return nil
	}
	f.planHook = func(ctx context.Context, req bridge.CreationPlanningRequest) (*bridge.CreationPlanningResponse, error) {
		if req.Repair == nil || req.Repair.NodeID != "video" || !req.RequireVideoScenes {
			t.Fatal("missing targeted repair")
		}
		p := copyAutomaticPlan(req.CurrentPlan)
		scene := p.Nodes[1]
		scene.ID, scene.Title, scene.Prompt, scene.Count = "cave", "洞穴", "empty glowing cave", 1
		video := p.Nodes[3]
		video.DependsOn = append(video.DependsOn, "cave")
		video.References[0].SceneIntervals = []bridge.CreativeSceneInterval{{StartSeconds: 0, EndSeconds: 2.5}}
		video.References = append(video.References, bridge.CreativeReference{NodeID: "cave", Role: "reference", SceneIntervals: []bridge.CreativeSceneInterval{{StartSeconds: 2.5, EndSeconds: 5}}})
		p.Nodes = append(p.Nodes[:3], scene, video)
		repaired = true
		return &bridge.CreationPlanningResponse{Plan: p, Reply: "补齐洞穴"}, nil
	}
	startAutomatic(t, r, h, token, row.ID, "repair-missing-scene")
	row = waitAutomatic(t, h, row.ID)
	doc, _ := projectDocument(row)
	if row.AutomaticStatus != "completed" || !creativeApproved(doc.States["cave"]) || len(f.requests) != 4 {
		t.Fatal("scene insertion interrupted loop", row.AutomaticStatus, doc.Automation.Steps, len(f.requests))
	}
	if f.requests[2].Kind != "image" || f.requests[3].Kind != "video" || len(f.requests[3].InputImages) != 2 {
		t.Fatal("new prerequisite not generated before video", f.requests)
	}
}

func TestAutomaticRepairRejectsNewDeliverablesOrUnrelatedScenes(t *testing.T) {
	for _, kind := range []string{"video", "image"} {
		plan := creativeTestPlan()
		doc := creativeDocument{Plan: plan, Automation: &creativeAutomation{}}
		p := copyAutomaticPlan(plan)
		node := plan.Nodes[1]
		node.ID, node.Kind, node.Count = "unrelated", kind, 1
		p.Nodes = append(p.Nodes, node)
		req := bridge.CreationPlanningRequest{Repair: &bridge.CreationRepairFeedback{NodeID: "video"}}
		if validateAutomaticRepair(doc, p, req) == nil {
			t.Fatal("accepted unrelated or extra delivery", kind)
		}
	}
}
func TestAutomaticCreationRevisesRejectedImagesUntilAcceptedThenGeneratesVideo(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	row = reviewTestNode(t, r, h, token, row.ID, "brief", "")
	row = reviewTestNode(t, r, h, token, row.ID, "script", "")
	before, _ := projectDocument(row)
	rejected := [][]string{}
	repairs := []bridge.CreationPlanningRequest{}
	f.reviewDecision = func(req bridge.CreationReviewRequest) *bridge.CreationReviewResponse {
		if req.NodeID == "visual" && len(req.CandidateIDs) > 0 && len(rejected) < 2 {
			rejected = append(rejected, append([]string{}, req.CandidateIDs...))
			return &bridge.CreationReviewResponse{Decision: "revise", Reason: "小伞错误继承兔大侠服饰，应为圆滚滚蘑菇生物"}
		}
		return nil
	}
	f.planHook = func(_ context.Context, req bridge.CreationPlanningRequest) (*bridge.CreationPlanningResponse, error) {
		repairs = append(repairs, req)
		p := copyAutomaticPlan(req.CurrentPlan)
		p.Nodes[1].Prompt = fmt.Sprintf("圆滚滚红白蘑菇生物，无兔耳无人类身体，第%d次修正", len(repairs))
		return &bridge.CreationPlanningResponse{Plan: p, Reply: "已强化蘑菇身份"}, nil
	}
	startAutomatic(t, r, h, token, row.ID, "repair-images")
	row = waitAutomatic(t, h, row.ID)
	doc, _ := projectDocument(row)
	if row.AutomaticStatus != "completed" || len(repairs) != 2 || len(f.requests) != 7 || f.requests[6].Kind != "video" {
		t.Fatal(row.AutomaticStatus, doc.Automation.Steps, len(f.requests))
	}
	for i, req := range repairs {
		if req.Repair == nil || req.Repair.NodeID != "visual" || req.Repair.Attempt != i+1 || !reflect.DeepEqual(req.Repair.CandidateIDs, rejected[i]) || len(req.Repair.PreviousFeedback) != i {
			t.Fatal("missing repair feedback", req.Repair)
		}
		for _, id := range rejected[i] {
			found := false
			for _, a := range req.Assets {
				found = found || a.ID == id && a.DataURL != ""
			}
			if !found {
				t.Fatal("rejected previews missing")
			}
		}
	}
	for _, id := range []string{"brief", "script"} {
		if !reflect.DeepEqual(before.States[id], doc.States[id]) {
			t.Fatal("confirmed node overwritten", id)
		}
	}
	for _, batch := range rejected {
		for _, id := range batch {
			if doc.States["visual"].SelectedAssetID == id {
				t.Fatal("reselected rejected output")
			}
			if _, err := h.assetItem(row.UserID, id); err != nil {
				t.Fatal("rejected asset lost")
			}
		}
	}
	if len(doc.States["visual"].Candidates) != 2 || doc.States["visual"].ApprovedBy != "agent" {
		t.Fatal(doc.States["visual"])
	}
}

func TestAutomaticCreationAdvancesIndependentImagesBeforeRetryingRejectedScene(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	doc, _ := projectDocument(row)
	plan := creativeTestPlan()
	scene := plan.Nodes[1]
	scene.Count = 1
	dependent, independent := scene, scene
	dependent.ID, dependent.Title, dependent.Prompt = "dependent", "落日分镜", "sunset storyboard"
	dependent.DependsOn = []string{"visual"}
	independent.ID, independent.Title, independent.Prompt = "independent", "菌林分镜", "forest storyboard"
	plan.Nodes = []bridge.CreativeNode{plan.Nodes[0], scene, dependent, independent}
	doc = applyCreativePlan(doc, plan)
	if err := h.updateProject(&row, doc, true); err != nil {
		t.Fatal(err)
	}
	row = reviewTestNode(t, r, h, token, row.ID, "brief", "")
	before, _ := projectDocument(row)
	order := []string{}
	rejected := false
	f.reviewDecision = func(req bridge.CreationReviewRequest) *bridge.CreationReviewResponse {
		order = append(order, req.NodeID)
		if req.NodeID == "visual" && !rejected {
			rejected = true
			return &bridge.CreationReviewResponse{Decision: "revise", Reason: "落日场景机位错误，需要重新生成"}
		}
		return nil
	}
	f.planHook = func(_ context.Context, req bridge.CreationPlanningRequest) (*bridge.CreationPlanningResponse, error) {
		return &bridge.CreationPlanningResponse{Plan: copyAutomaticPlan(req.CurrentPlan), Reply: "保留场景要求，重新生成候选"}, nil
	}
	startAutomatic(t, r, h, token, row.ID, "fair-scene-retry")
	row = waitAutomatic(t, h, row.ID)
	doc, _ = projectDocument(row)
	if row.AutomaticStatus != "completed" {
		t.Fatal(row.AutomaticStatus, doc.Automation.Steps)
	}
	want := []string{"visual", "independent", "visual", "dependent"}
	if !reflect.DeepEqual(order, want) {
		t.Fatalf("rejected scene blocked independent work or released its child early: got %v, want %v", order, want)
	}
	if len(f.requests) != 4 || !reflect.DeepEqual(before.States["brief"], doc.States["brief"]) {
		t.Fatal("duplicated generation or changed confirmed content")
	}
	for _, id := range []string{"visual", "independent", "dependent"} {
		if !creativeApproved(doc.States[id]) || doc.States[id].SelectedAssetID == "" {
			t.Fatal("did not return to unfinished work", id)
		}
	}
}

func TestAutomaticResumeKeepsRepairHistoryAndDoesNotStarveUntouchedNodes(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	doc, _ := projectDocument(row)
	plan := creativeTestPlan()
	image := plan.Nodes[1]
	image.Count = 1
	other := image
	other.ID, other.Title = "untouched", "未尝试的分镜"
	plan.Nodes = []bridge.CreativeNode{plan.Nodes[0], image, other}
	doc = applyCreativePlan(doc, plan)
	doc.Automation = &creativeAutomation{
		CreativePlanningActivity: bridge.CreativePlanningActivity{ID: "paused", Status: "cancelled"},
		RepairCounts:             map[string]int{"visual": 5, "deleted": 8},
		Repairs:                  []bridge.CreationRepairFeedback{{NodeID: "visual", Reason: "之前的构图问题", Attempt: 5}, {NodeID: "deleted", Reason: "不再存在"}},
	}
	row.AutomaticStatus = "cancelled"
	if err := h.updateProject(&row, doc, true); err != nil {
		t.Fatal(err)
	}
	row = reviewTestNode(t, r, h, token, row.ID, "brief", "")
	startAutomatic(t, r, h, token, row.ID, "resume-with-history")
	row = waitAutomatic(t, h, row.ID)
	doc, _ = projectDocument(row)
	if row.AutomaticStatus != "completed" || len(f.reviews) != 2 || f.reviews[0].NodeID != "untouched" {
		t.Fatal("resume restarted the same early node", row.AutomaticStatus, f.reviews)
	}
	if doc.Automation.RepairCounts["visual"] != 5 || doc.Automation.RepairCounts["deleted"] != 0 || len(doc.Automation.Repairs) != 1 {
		t.Fatal("lost useful repair history or retained removed nodes", doc.Automation)
	}
}

func TestAutomaticTargetedImagesIncludePrerequisitesButNeverSubmitDownstreamVideo(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	response := creationRequest(t, r, token, "POST", "/api/creation/projects/"+row.ID+"/automatic", map[string]interface{}{
		"revision": row.Revision, "request_id": "images-only", "target_node_ids": []string{"visual"},
	})
	if response.Code != 202 {
		t.Fatal(response.Code, response.Body.String())
	}
	row = waitAutomatic(t, h, row.ID)
	doc, _ := projectDocument(row)
	if row.AutomaticStatus != "completed" || !creativeApproved(doc.States["brief"]) || !creativeApproved(doc.States["visual"]) || creativeApproved(doc.States["video"]) {
		t.Fatal("targeted pass did not respect the dependency boundary", row.AutomaticStatus, doc.States)
	}
	for _, req := range f.requests {
		if req.Kind == "video" {
			t.Fatal("submitted unrequested video")
		}
	}
	if len(f.requests) != 2 {
		t.Fatal("did not complete the image candidates", len(f.requests))
	}
}

func TestAutomaticUnknownTargetIsRejectedWithoutStartingWork(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	response := creationRequest(t, r, token, "POST", "/api/creation/projects/"+row.ID+"/automatic", map[string]interface{}{
		"revision": row.Revision, "request_id": "invalid-target", "target_node_ids": []string{"missing"},
	})
	if response.Code != 400 || len(f.requests) != 0 || readTestProject(t, h, row.ID).Revision != row.Revision {
		t.Fatal(response.Code, "invalid target mutated project")
	}
}

func TestAutomaticCreationDoesNotCompleteWhenEveryPendingNodeIsBlocked(t *testing.T) {
	_, h, f, _, row := setupAutomatic(t)
	doc, _ := projectDocument(row)
	// A damaged/recovered dependency graph must fail visibly, never report completion.
	first, second := doc.Plan.Nodes[0], doc.Plan.Nodes[2]
	first.DependsOn = []string{second.ID}
	second.DependsOn = []string{first.ID}
	doc.Plan.Nodes = []bridge.CreativeNode{first, second}
	doc.Automation = &creativeAutomation{RepairCounts: map[string]int{}}
	row.AutomaticStatus, row.AutomaticRequestID = "running", "blocked-dependencies"
	if err := h.updateProject(&row, doc, false); err != nil {
		t.Fatal(err)
	}
	done, err := h.advanceAutomatic(context.Background(), row.ID, row.AutomaticRequestID)
	if done || err == nil || !strings.Contains(err.Error(), "上游") || len(f.requests) != 0 || len(f.reviews) != 0 {
		t.Fatalf("blocked workflow appeared complete: done=%v err=%v", done, err)
	}
}
func TestAutomaticCreationRepairStopDiscardsLatePlan(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	before, _ := projectDocument(row)
	entered := make(chan struct{}, 1)
	release := make(chan struct{})
	f.reviewDecision = func(req bridge.CreationReviewRequest) *bridge.CreationReviewResponse {
		return &bridge.CreationReviewResponse{Decision: "revise", Reason: "简报需要完善"}
	}
	f.planHook = func(_ context.Context, req bridge.CreationPlanningRequest) (*bridge.CreationPlanningResponse, error) {
		entered <- struct{}{}
		<-release
		p := copyAutomaticPlan(req.CurrentPlan)
		p.Nodes[0].Content = "迟到修改"
		return &bridge.CreationPlanningResponse{Plan: p}, nil
	}
	startAutomatic(t, r, h, token, row.ID, "stop-repair")
	<-entered
	res := creationRequest(t, r, token, "POST", "/api/creation/projects/"+row.ID+"/automatic/stop", map[string]interface{}{})
	if res.Code != 200 {
		t.Fatal(res.Code)
	}
	close(release)
	row = waitAutomatic(t, h, row.ID)
	doc, _ := projectDocument(row)
	if row.AutomaticStatus != "cancelled" || !reflect.DeepEqual(before.Plan, doc.Plan) || len(f.requests) > 0 {
		t.Fatal("late repair applied")
	}
}
func TestAutomaticCreationRepairCannotChangeLockedNodesOrAdoptRejectedImage(t *testing.T) {
	for _, bad := range []string{"locked", "candidate"} {
		t.Run(bad, func(t *testing.T) {
			r, h, f, token, row := setupAutomatic(t)
			row = reviewTestNode(t, r, h, token, row.ID, "brief", "")
			before, _ := projectDocument(row)
			f.reviewDecision = func(req bridge.CreationReviewRequest) *bridge.CreationReviewResponse {
				if len(req.CandidateIDs) > 0 {
					return &bridge.CreationReviewResponse{Decision: "revise", Reason: "角色身份错误"}
				}
				return nil
			}
			f.planHook = func(_ context.Context, req bridge.CreationPlanningRequest) (*bridge.CreationPlanningResponse, error) {
				p := copyAutomaticPlan(req.CurrentPlan)
				if bad == "locked" {
					p.Nodes[0].Content = "覆盖用户确认"
				} else {
					p.Nodes[1].AssetID = req.Repair.CandidateIDs[0]
				}
				return &bridge.CreationPlanningResponse{Plan: p}, nil
			}
			startAutomatic(t, r, h, token, row.ID, "unsafe-repair")
			row = waitAutomatic(t, h, row.ID)
			doc, _ := projectDocument(row)
			if row.AutomaticStatus != "failed" || !reflect.DeepEqual(before.Plan, doc.Plan) || len(doc.States["visual"].Candidates) != 2 || len(f.requests) != 2 {
				t.Fatal("invalid repair changed project", doc.Automation.Steps)
			}
		})
	}
}
func TestAutomaticCreationKeepsWorkingPastFormerStepLimit(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	round := 0
	f.reviewDecision = func(req bridge.CreationReviewRequest) *bridge.CreationReviewResponse {
		if req.NodeID == "brief" && round < 85 {
			return &bridge.CreationReviewResponse{Decision: "revise", Reason: "继续优化未确认的简报"}
		}
		return nil
	}
	f.planHook = func(_ context.Context, req bridge.CreationPlanningRequest) (*bridge.CreationPlanningResponse, error) {
		round++
		p := copyAutomaticPlan(req.CurrentPlan)
		p.Nodes[0].Content = fmt.Sprintf("完善简报%d", round)
		return &bridge.CreationPlanningResponse{Plan: p}, nil
	}
	startAutomatic(t, r, h, token, row.ID, "long-creation")
	row = waitAutomatic(t, h, row.ID)
	doc, _ := projectDocument(row)
	if row.AutomaticStatus != "completed" || round != 85 || doc.Automation.Steps[len(doc.Automation.Steps)-1].Stage != "completed" {
		t.Fatal("stopped at arbitrary step limit", round, doc.Automation.Steps)
	}
}
func TestAutomaticCreationOnlyBlocksForMissingRequiredInput(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	f.reviewDecision = func(req bridge.CreationReviewRequest) *bridge.CreationReviewResponse {
		return &bridge.CreationReviewResponse{Decision: "blocked", Reason: "用户要求严格复刻的商标原图尚未提供，无法代替"}
	}
	startAutomatic(t, r, h, token, row.ID, "missing-required-input")
	row = waitAutomatic(t, h, row.ID)
	if row.AutomaticStatus != "failed" || len(f.requests) > 0 {
		t.Fatal("invented missing input")
	}
}

func TestAutomaticCreationUnchangedRepairStillGeneratesFreshCandidates(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	rejected := false
	f.reviewDecision = func(req bridge.CreationReviewRequest) *bridge.CreationReviewResponse {
		if len(req.CandidateIDs) > 0 && !rejected {
			rejected = true
			return &bridge.CreationReviewResponse{Decision: "revise", Reason: "本批画面失真，需要重新生成"}
		}
		return nil
	}
	f.planHook = func(_ context.Context, req bridge.CreationPlanningRequest) (*bridge.CreationPlanningResponse, error) {
		return &bridge.CreationPlanningResponse{Plan: copyAutomaticPlan(req.CurrentPlan)}, nil
	}
	startAutomatic(t, r, h, token, row.ID, "retry-render")
	row = waitAutomatic(t, h, row.ID)
	doc, _ := projectDocument(row)
	if row.AutomaticStatus != "completed" || len(f.requests) != 5 || f.requests[4].Kind != "video" || len(doc.States["visual"].Candidates) != 2 {
		t.Fatal("reused rejected candidates", doc.Automation.Steps, len(f.requests))
	}
	var runs []models.CreationRun
	h.db.Where("project_id = ? AND project_node_id = ?", row.ID, "visual").Order("node_revision").Find(&runs)
	if len(runs) != 2 || runs[0].NodeRevision == runs[1].NodeRevision || runs[0].RequestID == runs[1].RequestID {
		t.Fatal("regeneration did not receive fresh submission identity", runs)
	}
}
func TestAutomaticCreationRejectsAssetChangedDuringRepair(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	f.reviewDecision = func(req bridge.CreationReviewRequest) *bridge.CreationReviewResponse {
		if len(req.CandidateIDs) > 0 {
			return &bridge.CreationReviewResponse{Decision: "revise", Reason: "需修正角色"}
		}
		return nil
	}
	f.planHook = func(_ context.Context, req bridge.CreationPlanningRequest) (*bridge.CreationPlanningResponse, error) {
		var asset models.CreationAsset
		h.db.First(&asset, "id = ?", req.Repair.CandidateIDs[0])
		h.db.Model(&models.DriveItem{}).Where("id = ?", asset.DriveItemID).Update("content", "changed")
		return &bridge.CreationPlanningResponse{Plan: copyAutomaticPlan(req.CurrentPlan)}, nil
	}
	startAutomatic(t, r, h, token, row.ID, "changed-repair-asset")
	row = waitAutomatic(t, h, row.ID)
	doc, _ := projectDocument(row)
	if row.AutomaticStatus != "failed" || len(f.requests) != 2 || !strings.Contains(doc.Automation.Steps[len(doc.Automation.Steps)-1].Message, "图片发生变化") {
		t.Fatal("changed asset used for repair")
	}
}

func TestAutomaticImageGenerationPrecedesOutputReview(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	emptyImageReviews := 0
	f.reviewDecision = func(req bridge.CreationReviewRequest) *bridge.CreationReviewResponse {
		if req.NodeID == "visual" && len(req.CandidateIDs) == 0 {
			emptyImageReviews++
			return &bridge.CreationReviewResponse{Decision: "revise", Reason: "没有候选，需要先生成"}
		}
		return nil
	}
	startAutomatic(t, r, h, token, row.ID, "generate-before-review")
	row = waitAutomatic(t, h, row.ID)
	if row.AutomaticStatus != "completed" || emptyImageReviews != 0 || len(f.requests) != 3 {
		t.Fatal("empty-candidate revision loop", emptyImageReviews, row.AutomaticStatus)
	}
}

func TestAutomaticImageFreezesReferenceRoleAndNoteThroughExecution(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	asset, err := h.saveAsset(row.UserID, "forest-style.png", creationPNG, "image/png", "upload", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	doc, _ := projectDocument(row)
	doc.AssetIDs = []string{asset.ID}
	doc.Plan.Nodes[1].References = []bridge.CreativeReference{{AssetID: asset.ID, Role: "style", Note: "只借用线条和上色，不保留兔子或森林构图"}}
	doc.Plan.Nodes[1].CharacterStyle = "chibi" // Legacy plans are routed by the stronger style-only role.
	doc.Plan.Nodes[1].Purpose = "key_visual"
	doc.Plan.Nodes = doc.Plan.Nodes[:3] // This regression exercises an image-only legacy canvas.
	if err = h.updateProject(&row, doc, false); err != nil {
		t.Fatal(err)
	}
	startAutomatic(t, r, h, token, row.ID, "style-context")
	row = waitAutomatic(t, h, row.ID)
	if row.AutomaticStatus != "completed" {
		t.Fatal(row.AutomaticStatus)
	}
	expected := []bridge.ImageReferenceContext{{Role: "style", Note: doc.Plan.Nodes[1].References[0].Note}}
	for _, req := range f.requests {
		if req.Kind == "image" && (!reflect.DeepEqual(req.ImageReferences, expected) || req.ImagePurpose != "key_visual") {
			t.Fatal("reference semantics lost", req)
		}
	}
	var run models.CreationRun
	h.db.Where("project_id = ? AND project_node_id = ?", row.ID, "visual").First(&run)
	var graph creationGraph
	_ = json.Unmarshal([]byte(run.Definition), &graph)
	if !reflect.DeepEqual(graph.Nodes[0].ImageReferences, expected) || graph.Nodes[0].ImagePurpose != "key_visual" {
		t.Fatal("reference context not frozen")
	}
}
