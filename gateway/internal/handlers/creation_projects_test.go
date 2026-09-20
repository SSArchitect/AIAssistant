package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
)

type fakeCreativePlanner struct {
	fakeCreationGenerator
	response *bridge.CreationPlanningResponse
	err      error
	wait     chan struct{}
	called   chan bridge.CreationPlanningRequest
	deadline time.Time
}

func (f *fakeCreativePlanner) PlanCreation(ctx context.Context, req bridge.CreationPlanningRequest) (*bridge.CreationPlanningResponse, error) {
	f.deadline, _ = ctx.Deadline()
	if f.called != nil {
		f.called <- req
	}
	if f.wait != nil {
		<-f.wait
	}
	return f.response, f.err
}
func creativeTestPlan() bridge.CreativePlan {
	brief := bridge.CreativeNode{ID: "brief", Kind: "text", Purpose: "brief", Title: "创意简报", Content: "竹林里的相逢", Count: 1, AspectRatio: "16:9", DurationSeconds: 5, DependsOn: []string{}, References: []bridge.CreativeReference{}}
	image := bridge.CreativeNode{ID: "visual", Kind: "image", Purpose: "scene", Title: "主视觉", Content: "留白竹林", Prompt: "ink bamboo forest", Count: 2, AspectRatio: "16:9", DurationSeconds: 5, DependsOn: []string{"brief"}, References: []bridge.CreativeReference{}}
	script := brief
	script.ID = "script"
	script.Purpose = "script"
	script.Title = "分镜"
	script.Content = "0–5秒，缓慢推近竹林。"
	script.DependsOn = []string{"brief"}
	video := bridge.CreativeNode{ID: "video", Kind: "video", Purpose: "output", Title: "短片", Prompt: "compiled storyboard", Content: "竹林短片", Count: 1, AspectRatio: "16:9", DurationSeconds: 5, DependsOn: []string{"visual", "script"}, References: []bridge.CreativeReference{{NodeID: "visual", Role: "reference", Note: "只参考场景画风"}}, Storyboard: json.RawMessage(`{"style":"ink","shots":[{"start_seconds":0,"description":"Wind in bamboo"}],"overall_soundscape":"wind","non_diegetic_music":"N/A"}`)}
	return bridge.CreativePlan{Title: "竹林相逢", Summary: "先确定场景与分镜，再生成短片", Nodes: []bridge.CreativeNode{brief, image, script, video}, Questions: []bridge.CreativeQuestion{}}
}
func createTestProject(t *testing.T, r *gin.Engine, token string) models.CreationProject {
	t.Helper()
	response := creationRequest(t, r, token, "POST", "/api/creation/projects", map[string]string{})
	if response.Code != 201 {
		t.Fatal(response.Code, response.Body.String())
	}
	var result struct {
		Project models.CreationProject `json:"project"`
	}
	json.Unmarshal(response.Body.Bytes(), &result)
	return result.Project
}
func readTestProject(t *testing.T, h *CreationHandler, id string) models.CreationProject {
	t.Helper()
	var row models.CreationProject
	if err := h.db.First(&row, "id = ?", id).Error; err != nil {
		t.Fatal(err)
	}
	return row
}
func seedCreativePlan(t *testing.T, h *CreationHandler, row models.CreationProject) models.CreationProject {
	t.Helper()
	row = readTestProject(t, h, row.ID)
	doc, _ := projectDocument(row)
	doc = applyCreativePlan(doc, creativeTestPlan())
	row.Name = doc.Plan.Title
	if err := h.updateProject(&row, doc, true); err != nil {
		t.Fatal(err)
	}
	return row
}
func reviewTestNode(t *testing.T, r *gin.Engine, h *CreationHandler, token, id, node, asset string) models.CreationProject {
	t.Helper()
	row := readTestProject(t, h, id)
	response := creationRequest(t, r, token, "POST", "/api/creation/projects/"+id+"/review", map[string]interface{}{"revision": row.Revision, "node_id": node, "asset_id": asset})
	if response.Code != 200 {
		t.Fatal(response.Code, response.Body.String())
	}
	return readTestProject(t, h, id)
}
func waitCreativeRun(t *testing.T, h *CreationHandler, id string) models.CreationRun {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		var run models.CreationRun
		h.db.First(&run, "id = ?", id)
		if run.Status != "queued" && run.Status != "running" && run.Status != "stopping" {
			// Synchronize with the final project adoption that follows the run checkpoint.
			if run.ProjectID != "" {
				row := readTestProject(t, h, run.ProjectID)
				doc, _ := projectDocument(row)
				if len(doc.States[run.ProjectNodeID].Candidates) == 0 && run.Status == "completed" {
					time.Sleep(time.Millisecond)
					continue
				}
			}
			return run
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatal("run did not finish")
	return models.CreationRun{}
}
func TestCreativeProjectsRequireOwnerAndRejectStaleReviews(t *testing.T) {
	r, h, _, token := setupCreation(t)
	row := seedCreativePlan(t, h, createTestProject(t, r, token))
	bob, _ := createAccountSession("bob")
	for _, path := range []string{"/api/creation/projects", "/api/creation/projects/" + row.ID} {
		if response := creationRequest(t, r, "", "GET", path, nil); response.Code != 401 {
			t.Fatal(response.Code)
		}
	}
	for _, path := range []string{"", "/versions"} {
		if response := creationRequest(t, r, bob, "GET", "/api/creation/projects/"+row.ID+path, nil); response.Code != 404 {
			t.Fatal(response.Code)
		}
	}
	for _, path := range []string{"/review", "/generate", "/template"} {
		response := creationRequest(t, r, bob, "POST", "/api/creation/projects/"+row.ID+path, map[string]interface{}{"revision": row.Revision, "node_id": "brief", "request_id": "req"})
		if response.Code != 404 {
			t.Fatal(path, response.Code, response.Body.String())
		}
	}
	response := creationRequest(t, r, token, "POST", "/api/creation/projects/"+row.ID+"/review", map[string]interface{}{"revision": row.Revision - 1, "node_id": "brief"})
	if response.Code != 409 {
		t.Fatal(response.Code)
	}
	response = creationRequest(t, r, token, "POST", "/api/creation/projects/"+row.ID+"/review", map[string]interface{}{"revision": row.Revision, "node_id": "script"})
	if response.Code != 409 {
		t.Fatal("upstream review bypass", response.Code)
	}
}
func TestCreativePlanChangesInvalidateOnlyAffectedDescendants(t *testing.T) {
	doc := applyCreativePlan(emptyCreativeDocument(), creativeTestPlan())
	for id, s := range doc.States {
		s.ApprovedRevision = s.Revision
		s.Candidates = []string{"prior"}
		s.SelectedAssetID = "prior"
		doc.States[id] = s
	}
	replacement := creativeTestPlan()
	replacement.Nodes[2].Content = "第二个镜头慢一点"
	changed := applyCreativePlan(doc, replacement)
	if !creativeApproved(changed.States["brief"]) || !creativeApproved(changed.States["visual"]) {
		t.Fatal("unrelated approvals lost")
	}
	if creativeApproved(changed.States["script"]) || creativeApproved(changed.States["video"]) || len(changed.States["video"].Candidates) > 0 {
		t.Fatal("descendants remained approved")
	}
	if doc.States["video"].SelectedAssetID != "prior" {
		t.Fatal("previous snapshot mutated")
	}
	unchanged := applyCreativePlan(changed, replacement)
	if unchanged.States["script"].Revision != changed.States["script"].Revision {
		t.Fatal("unchanged proposal changed versions")
	}
}
func TestCreativePlanningIsAsyncIdempotentAndNeverGeneratesMedia(t *testing.T) {
	r, h, _, token := setupCreation(t)
	row := createTestProject(t, r, token)
	fake := &fakeCreativePlanner{response: &bridge.CreationPlanningResponse{Reply: "请先确认简报", Plan: creativeTestPlan(), ModelUsed: "model", TokensUsed: map[string]int{"input_tokens": 12, "output_tokens": 6}}, wait: make(chan struct{}), called: make(chan bridge.CreationPlanningRequest, 2)}
	h.generator = fake
	body := map[string]interface{}{"revision": row.Revision, "message": "帮我做竹林短片", "request_id": "message-1"}
	response := creationRequest(t, r, token, "POST", "/api/creation/projects/"+row.ID+"/messages", body)
	if response.Code != 202 {
		t.Fatal(response.Code, response.Body.String())
	}
	request := <-fake.called
	if !request.RequireVideoScenes || !request.RequireShotReferences {
		t.Fatal("new planning omitted scene preparation")
	}
	if remaining := time.Until(fake.deadline); remaining < 900*time.Second || remaining > 915*time.Second {
		t.Fatalf("gateway must allow the agent's active-stream budget: %s", remaining)
	}
	if request.UserID != "alice" || len(request.Templates) < 6 || request.Messages[0].Content != "帮我做竹林短片" {
		t.Fatalf("bad planning request %+v", request)
	}
	duplicate := creationRequest(t, r, token, "POST", "/api/creation/projects/"+row.ID+"/messages", body)
	if duplicate.Code != 200 {
		t.Fatal(duplicate.Code)
	}
	response = creationRequest(t, r, token, "POST", "/api/creation/projects/"+row.ID+"/generate", map[string]interface{}{"revision": row.Revision + 1, "node_id": "video", "request_id": "premature"})
	if response.Code != 409 {
		t.Fatal(response.Code)
	}
	close(fake.wait)
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		row = readTestProject(t, h, row.ID)
		if !row.Planning {
			break
		}
		time.Sleep(time.Millisecond)
	}
	if row.Planning || row.Error != "" {
		t.Fatal(row.Error, "planning failed")
	}
	doc, _ := projectDocument(row)
	if len(doc.Messages) != 2 || len(doc.Plan.Nodes) != 4 || len(fake.requests) != 0 {
		t.Fatalf("bad state %+v", doc)
	}
	for _, state := range doc.States {
		if creativeApproved(state) {
			t.Fatal("AI approved a node")
		}
	}
}
func TestCreativePlanningFailurePreservesPriorPlanAndRejectsForeignAssets(t *testing.T) {
	r, h, _, token := setupCreation(t)
	row := seedCreativePlan(t, h, createTestProject(t, r, token))
	fake := &fakeCreativePlanner{err: errors.New("SECRET")}
	h.generator = fake
	response := creationRequest(t, r, token, "POST", "/api/creation/projects/"+row.ID+"/messages", map[string]interface{}{"revision": row.Revision, "message": "修改", "asset_ids": []string{"foreign"}, "request_id": "bad-asset"})
	if response.Code != 400 {
		t.Fatal(response.Code)
	}
	doc, _ := projectDocument(row)
	row.Planning = true
	row.PlanningRequestID = "fail"
	h.updateProject(&row, doc, false)
	h.planProject(fake, row, bridge.CreationPlanningRequest{})
	row = readTestProject(t, h, row.ID)
	doc, _ = projectDocument(row)
	if row.Planning || row.Error == "" || strings.Contains(row.Error, "SECRET") || len(doc.Plan.Nodes) != 4 {
		t.Fatalf("unsafe failure: %+v", row)
	}
}
func TestCreativeVideoReviewGateCandidateChoiceAndFrozenIdempotentSubmission(t *testing.T) {
	r, h, f, token := setupCreation(t)
	row := seedCreativePlan(t, h, createTestProject(t, r, token))
	generate := func(node, key string) (models.CreationRun, int, string) {
		latest := readTestProject(t, h, row.ID)
		response := creationRequest(t, r, token, "POST", "/api/creation/projects/"+row.ID+"/generate", map[string]interface{}{"revision": latest.Revision, "node_id": node, "request_id": key})
		var result struct {
			Run models.CreationRun `json:"run"`
		}
		json.Unmarshal(response.Body.Bytes(), &result)
		return result.Run, response.Code, response.Body.String()
	}
	if _, code, _ := generate("video", "before-review"); code != 409 {
		t.Fatal(code)
	}
	reviewTestNode(t, r, h, token, row.ID, "brief", "")
	imageRun, code, body := generate("visual", "images")
	if code != 202 {
		t.Fatal(code, body)
	}
	waitCreativeRun(t, h, imageRun.ID)
	row = readTestProject(t, h, row.ID)
	doc, _ := projectDocument(row)
	candidates := doc.States["visual"].Candidates
	if len(candidates) != 2 {
		t.Fatal(candidates)
	}
	if _, code, _ = generate("video", "before-selection"); code != 409 {
		t.Fatal(code)
	}
	reviewTestNode(t, r, h, token, row.ID, "visual", candidates[1])
	reviewTestNode(t, r, h, token, row.ID, "script", "")
	if _, code, _ = generate("video", "before-reference-review"); code != 409 {
		t.Fatal(code)
	}
	row = reviewTestNode(t, r, h, token, row.ID, "video", "")
	videoRun, code, body := generate("video", "video-submit")
	if code != 202 {
		t.Fatal(code, body)
	}
	completed := waitCreativeRun(t, h, videoRun.ID)
	if completed.Status != "completed" {
		t.Fatal(completed.Error)
	}
	replay, code, _ := generate("video", "video-submit")
	if code != 200 || replay.ID != videoRun.ID {
		t.Fatal("duplicate submission", code)
	}
	if len(f.requests) != 3 || f.requests[2].VideoMode != "reference_to_video" || len(f.requests[2].InputImages) != 1 {
		t.Fatal("wrong media routing", f.requests)
	}
	if videoRun.ProjectRevision != row.Revision || !strings.Contains(videoRun.Snapshot, "0–5秒") || !strings.Contains(videoRun.Snapshot, candidates[1]) {
		t.Fatal("snapshot not frozen")
	}
	var versions []models.CreationProjectVersion
	h.db.Where("project_id = ?", row.ID).Find(&versions)
	if len(versions) < 4 {
		t.Fatal("review history missing")
	}
}
func TestCreativeQuestionsAndChangedDriveBytesBlockSubmission(t *testing.T) {
	r, h, _, token := setupCreation(t)
	row := seedCreativePlan(t, h, createTestProject(t, r, token))
	row = reviewTestNode(t, r, h, token, row.ID, "brief", "")
	doc, _ := projectDocument(row)
	doc.Plan.Questions = []bridge.CreativeQuestion{{Question: "结尾？", Options: []string{"反转", "悬疑"}}}
	h.updateProject(&row, doc, false)
	response := creationRequest(t, r, token, "POST", "/api/creation/projects/"+row.ID+"/generate", map[string]interface{}{"revision": row.Revision, "node_id": "visual", "request_id": "blocked-question"})
	if response.Code != 409 || !strings.Contains(response.Body.String(), "回答") {
		t.Fatal(response.Code, response.Body.String())
	}
	asset, err := h.saveAsset("alice", "reference.png", creationPNG, "image/png", "upload", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	doc.Plan.Questions = nil
	doc.Plan.Nodes[1].AssetID = asset.ID
	doc.Plan.Nodes[1].Count = 1
	doc.States["visual"] = creativeNodeState{Revision: 2, SelectedAssetID: asset.ID}
	h.updateProject(&row, doc, false)
	reviewTestNode(t, r, h, token, row.ID, "visual", asset.ID)
	reviewTestNode(t, r, h, token, row.ID, "script", "")
	row = reviewTestNode(t, r, h, token, row.ID, "video", "")
	h.db.Model(&models.DriveItem{}).Where("id = ?", asset.DriveItemID).Update("content", creationPNG+"AAAA")
	response = creationRequest(t, r, token, "POST", "/api/creation/projects/"+row.ID+"/generate", map[string]interface{}{"revision": row.Revision, "node_id": "video", "request_id": "changed-input"})
	if response.Code != 409 || !strings.Contains(response.Body.String(), "变更") {
		t.Fatal(response.Code, response.Body.String())
	}
}
func TestCreativeCandidateSwitchInvalidatesOnlyDownstreamAndOldResultsStayInHistory(t *testing.T) {
	r, h, _, token := setupCreation(t)
	row := seedCreativePlan(t, h, createTestProject(t, r, token))
	row = reviewTestNode(t, r, h, token, row.ID, "brief", "")
	a, _ := h.saveAsset("alice", "a.png", creationPNG, "image/png", "generated", "old-run", "visual", "")
	b, _ := h.saveAsset("alice", "b.png", creationPNG, "image/png", "generated", "old-run", "visual", "")
	doc, _ := projectDocument(row)
	state := doc.States["visual"]
	state.Candidates = []string{a.ID, b.ID}
	doc.States["visual"] = state
	h.updateProject(&row, doc, false)
	reviewTestNode(t, r, h, token, row.ID, "visual", a.ID)
	reviewTestNode(t, r, h, token, row.ID, "script", "")
	reviewTestNode(t, r, h, token, row.ID, "video", "")
	row = reviewTestNode(t, r, h, token, row.ID, "visual", b.ID)
	doc, _ = projectDocument(row)
	if !creativeApproved(doc.States["script"]) || creativeApproved(doc.States["video"]) {
		t.Fatal("invalid dependency propagation")
	}
	before := row.Document
	h.finishProjectRun(models.CreationRun{ID: "old-run", UserID: "alice", ProjectID: row.ID, ProjectNodeID: "visual", NodeRevision: 1}, []creationProgress{{AssetIDs: []string{"late-result"}}})
	if readTestProject(t, h, row.ID).Document != before {
		t.Fatal("outdated render overwrote latest selection")
	}
}
func TestCreativeProjectTemplatesRemoveAssetBindingsAndRecoveryDoesNotResubmit(t *testing.T) {
	r, h, f, token := setupCreation(t)
	row := seedCreativePlan(t, h, createTestProject(t, r, token))
	doc, _ := projectDocument(row)
	doc.Plan.Nodes[1].AssetID = "private-asset-id"
	doc.Plan.Nodes[3].References = append(doc.Plan.Nodes[3].References, bridge.CreativeReference{AssetID: "private-other-id", Role: "identity", Note: "角色图"})
	h.updateProject(&row, doc, false)
	response := creationRequest(t, r, token, "POST", "/api/creation/projects/"+row.ID+"/template", nil)
	if response.Code != 201 || strings.Contains(response.Body.String(), "private-asset-id") || strings.Contains(response.Body.String(), "private-other-id") {
		t.Fatal(response.Code, response.Body.String())
	}
	h.db.Model(&row).Update("planning", true)
	if err := h.Recover(); err != nil {
		t.Fatal(err)
	}
	row = readTestProject(t, h, row.ID)
	if row.Planning || row.Error == "" || len(f.requests) > 0 {
		t.Fatal("recovery replayed work")
	}
}
func TestCreativePlanValidationRejectsUnsupportedReferencesAndMissingScript(t *testing.T) {
	for index, change := range []func(*bridge.CreativePlan){
		func(p *bridge.CreativePlan) { p.Nodes[3].DependsOn = []string{"visual"} },
		func(p *bridge.CreativePlan) { p.Nodes[3].References[0].NodeID = "missing" },
		func(p *bridge.CreativePlan) {
			p.Nodes[3].References[0] = bridge.CreativeReference{AssetID: "foreign", Role: "identity"}
		},
		func(p *bridge.CreativePlan) {
			p.Nodes[1].References = []bridge.CreativeReference{{AssetID: "a", Role: "identity"}, {AssetID: "b", Role: "style"}, {AssetID: "c", Role: "identity"}, {AssetID: "d", Role: "identity"}}
		},
	} {
		t.Run(fmt.Sprint(index), func(t *testing.T) {
			p := creativeTestPlan()
			change(&p)
			if validateCreativePlan(p, map[string]bool{"a": true, "b": true}) == nil {
				t.Fatal("invalid plan accepted")
			}
		})
	}
}

func TestCreativePlanningProgressPersistsAndIgnoresStaleRequest(t *testing.T) {
	r, h, _, token := setupCreation(t)
	row := createTestProject(t, r, token)
	row = readTestProject(t, h, row.ID)
	doc, _ := projectDocument(row)
	row.Planning, row.PlanningRequestID = true, "current"
	doc.Planning = &bridge.CreativePlanningActivity{ID: "current", Status: "running", StartedAt: time.Now().Add(-time.Second), Steps: []bridge.CreativePlanningStep{}}
	h.updateProject(&row, doc, false)
	h.recordPlanningProgress(row, bridge.CreationPlanningProgress{Stage: "thinking", Message: "模型正在分析需求"})
	updated := readTestProject(t, h, row.ID)
	doc, _ = projectDocument(updated)
	if len(doc.Planning.Steps) != 1 || doc.Planning.Steps[0].Stage != "thinking" || updated.Revision <= row.Revision {
		t.Fatalf("progress not persisted: %+v", doc.Planning)
	}
	stale := row
	stale.PlanningRequestID = "old"
	h.recordPlanningProgress(stale, bridge.CreationPlanningProgress{Stage: "draft", Message: "stale"})
	foreign := row
	foreign.UserID = "bob"
	h.recordPlanningProgress(foreign, bridge.CreationPlanningProgress{Stage: "draft", Message: "foreign"})
	if readTestProject(t, h, row.ID).Revision != updated.Revision {
		t.Fatal("stale progress changed project")
	}
	h.planProject(&fakeCreativePlanner{response: &bridge.CreationPlanningResponse{Reply: "请审阅", Plan: creativeTestPlan()}}, row, bridge.CreationPlanningRequest{})
	updated = readTestProject(t, h, row.ID)
	doc, _ = projectDocument(updated)
	if updated.Planning || doc.Planning != nil || len(doc.Messages) != 1 || doc.Messages[0].Planning.Status != "completed" {
		t.Fatalf("terminal activity not saved: %+v", doc)
	}
	h.recordPlanningProgress(row, bridge.CreationPlanningProgress{Stage: "draft", Message: "late"})
	if readTestProject(t, h, row.ID).Revision != updated.Revision {
		t.Fatal("late progress reopened completed project")
	}
}

func TestCreativePlanningFailureIsSavedAsDialogueActivity(t *testing.T) {
	r, h, _, token := setupCreation(t)
	row := seedCreativePlan(t, h, createTestProject(t, r, token))
	doc, _ := projectDocument(row)
	doc.Messages = []bridge.CreativeMessage{{Role: "user", Content: "修改脚本"}}
	doc.Planning = &bridge.CreativePlanningActivity{ID: "fail", Status: "running", StartedAt: time.Now()}
	row.Planning, row.PlanningRequestID = true, "fail"
	h.updateProject(&row, doc, false)
	h.planProject(&fakeCreativePlanner{err: &bridge.CreationPlanningError{Message: "创作规划等待超时，原有内容已保留，请重试"}}, row, bridge.CreationPlanningRequest{})
	row = readTestProject(t, h, row.ID)
	doc, _ = projectDocument(row)
	if row.Planning || doc.Planning != nil || len(doc.Messages) != 2 || doc.Messages[1].Planning.Status != "failed" || !strings.Contains(doc.Messages[1].Content, "超时") || len(doc.Plan.Nodes) != 4 {
		t.Fatalf("failure invisible or lost plan: %+v", doc)
	}
}

func TestCreativePlanningRestartClosesProgressInDialogue(t *testing.T) {
	r, h, _, token := setupCreation(t)
	row := readTestProject(t, h, createTestProject(t, r, token).ID)
	doc, _ := projectDocument(row)
	doc.Planning = &bridge.CreativePlanningActivity{ID: "restart", Status: "running", StartedAt: time.Now()}
	row.Planning, row.PlanningRequestID = true, "restart"
	if err := h.updateProject(&row, doc, false); err != nil {
		t.Fatal(err)
	}
	if err := h.Recover(); err != nil {
		t.Fatal(err)
	}
	row = readTestProject(t, h, row.ID)
	doc, _ = projectDocument(row)
	if row.Planning || doc.Planning != nil || len(doc.Messages) != 1 || doc.Messages[0].Planning.Status != "interrupted" {
		t.Fatalf("stuck activity after restart: %+v", doc)
	}
}

func TestCreativeConversationCanAskForDirectionBeforeCreatingNodes(t *testing.T) {
	p := bridge.CreativePlan{Title: "参考图已收到", Summary: "等待用户描述创作目标", Nodes: []bridge.CreativeNode{}, Questions: []bridge.CreativeQuestion{}}
	if err := validateCreativePlan(p, nil); err != nil {
		t.Fatalf("conversational clarification rejected: %v", err)
	}
	p.Title = ""
	if err := validateCreativePlan(p, nil); err == nil {
		t.Fatal("invalid proposal accepted")
	}
}
