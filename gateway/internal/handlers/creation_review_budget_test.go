package handlers

import (
	"context"
	"reflect"
	"testing"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/models"
)

func TestAutomaticImageReviewCapsRepairsAndSelectsEarlierBestAcrossAllBatches(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	repairs, ordinaryReviews := 0, 0
	first := ""
	seen := map[string]bool{}
	f.planHook = func(_ context.Context, req bridge.CreationPlanningRequest) (*bridge.CreationPlanningResponse, error) {
		repairs++
		return &bridge.CreationPlanningResponse{Plan: copyAutomaticPlan(req.CurrentPlan), Reply: "重新生成"}, nil
	}
	f.reviewDecision = func(req bridge.CreationReviewRequest) *bridge.CreationReviewResponse {
		if req.NodeID != "visual" {
			return nil
		}
		if first == "" {
			first = req.CandidateIDs[0]
		}
		if req.SelectionMode == "" {
			ordinaryReviews++
			return &bridge.CreationReviewResponse{Decision: "revise", Reason: "构图尚可改进"}
		}
		if len(req.CandidateIDs) > 4 {
			t.Error("unbounded preview batch")
		}
		for _, id := range req.CandidateIDs {
			seen[id] = true
			visible := false
			for _, asset := range req.Assets {
				visible = visible || asset.ID == id && asset.DataURL != ""
			}
			if !visible {
				t.Error("candidate was not visible", id)
			}
		}
		return &bridge.CreationReviewResponse{Decision: "select", AssetID: first, Reason: "首轮图构图最好，仍有轻微细节偏差"}
	}
	startAutomatic(t, r, h, token, row.ID, "cap")
	row = waitAutomatic(t, h, row.ID)
	doc, _ := projectDocument(row)
	if row.AutomaticStatus != "completed" || repairs != 5 || ordinaryReviews != 5 || len(f.requests) != 13 {
		t.Fatal(row.AutomaticStatus, repairs, ordinaryReviews, len(f.requests), doc.Automation.Steps)
	}
	state := doc.States["visual"]
	if state.SelectedAssetID != first || state.ApprovedBy != "agent" || !creativeApproved(state) || len(seen) != 12 || len(state.Candidates) != 12 {
		t.Fatal("did not select the best earlier candidate", state, len(seen))
	}
	if !creativeApproved(doc.States["video"]) {
		t.Fatal("downstream did not continue")
	}
	for _, id := range state.Candidates {
		if _, err := h.assetItem(row.UserID, id); err != nil {
			t.Fatal("lost old candidate", err)
		}
	}
}

func TestAutomaticImageReviewResumePreservesBudgetAndIgnoresLateSelection(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	f.planHook = func(_ context.Context, req bridge.CreationPlanningRequest) (*bridge.CreationPlanningResponse, error) {
		return &bridge.CreationPlanningResponse{Plan: copyAutomaticPlan(req.CurrentPlan), Reply: "重试"}, nil
	}
	f.reviewDecision = func(req bridge.CreationReviewRequest) *bridge.CreationReviewResponse {
		if req.NodeID != "visual" {
			return nil
		}
		if req.SelectionMode == "" {
			return &bridge.CreationReviewResponse{Decision: "revise", Reason: "调整构图"}
		}
		h.db.Model(&models.CreationProject{}).Where("id = ?", row.ID).Update("automatic_status", "stopping")
		return &bridge.CreationReviewResponse{Decision: "select", AssetID: req.CandidateIDs[0], Reason: "最佳"}
	}
	startAutomatic(t, r, h, token, row.ID, "before-stop")
	row = waitAutomatic(t, h, row.ID)
	doc, _ := projectDocument(row)
	if row.AutomaticStatus != "cancelled" || creativeApproved(doc.States["visual"]) || doc.Automation.ImageReviews["visual"].Retries != 5 {
		t.Fatal("late response changed approval or budget", doc)
	}
	generated := len(f.requests)
	f.reviewDecision = func(req bridge.CreationReviewRequest) *bridge.CreationReviewResponse {
		if req.NodeID == "visual" && req.SelectionMode != "best_available" {
			t.Error("resume reset budget")
		}
		return nil
	}
	startAutomatic(t, r, h, token, row.ID, "after-stop")
	row = waitAutomatic(t, h, row.ID)
	if row.AutomaticStatus != "completed" || len(f.requests) != generated+1 {
		t.Fatal("resume regenerated images", row.AutomaticStatus, len(f.requests))
	}
}

func TestImageReviewHistoryResetsOnUserEditAndMigratesLegacyBudget(t *testing.T) {
	doc := creativeDocument{States: map[string]creativeNodeState{"image": {Revision: 3}}, Automation: &creativeAutomation{
		RepairCounts: map[string]int{"image": 61}, Repairs: []bridge.CreationRepairFeedback{{NodeID: "image", CandidateIDs: []string{"old"}}}}}
	history := imageReviewHistory(&doc, "image", []string{"new"})
	if history.Retries != 61 || !reflect.DeepEqual(history.CandidateIDs, []string{"old", "new"}) {
		t.Fatal(history)
	}
	doc.States["image"] = creativeNodeState{Revision: 4}
	history = imageReviewHistory(&doc, "image", []string{"edited"})
	if history.Retries != 0 || !reflect.DeepEqual(history.CandidateIDs, []string{"edited"}) {
		t.Fatal("user edit inherited old comparison", history)
	}
}

func TestImageReviewBudgetSurvivesAutomaticDependencyChanges(t *testing.T) {
	doc := creativeDocument{States: map[string]creativeNodeState{"image": {Revision: 4}}, Automation: &creativeAutomation{
		ImageReviews: map[string]*creativeImageReview{"image": {Revision: 3, Retries: 5, CandidateIDs: []string{"first", "second"}, Compared: 1, BestAssetID: "first"}}}}
	syncAutomaticImageReviewRevisions(&doc)
	history := imageReviewHistory(&doc, "image", nil)
	if history.Retries != 5 || history.Revision != 4 || history.Compared != 0 || history.BestAssetID != "" || len(history.CandidateIDs) != 2 {
		t.Fatal("automatic prerequisite change reset budget or reused stale comparison", history)
	}
}

func TestAutomaticImageReviewUserEditStartsFreshBudget(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	doc, _ := projectDocument(row)
	doc.Automation = &creativeAutomation{RepairCounts: map[string]int{"visual": 5}, ImageReviews: map[string]*creativeImageReview{
		"visual": {Revision: doc.States["visual"].Revision - 1, Retries: 5, CandidateIDs: []string{"old-requirements"}},
	}}
	if err := h.updateProject(&row, doc, false); err != nil {
		t.Fatal(err)
	}
	reviews := 0
	f.reviewDecision = func(req bridge.CreationReviewRequest) *bridge.CreationReviewResponse {
		if req.NodeID != "visual" {
			return nil
		}
		if req.SelectionMode != "" {
			t.Error("new user requirements inherited old budget")
		}
		reviews++
		if reviews == 1 {
			return &bridge.CreationReviewResponse{Decision: "revise", Reason: "调整构图"}
		}
		return nil
	}
	f.planHook = func(_ context.Context, req bridge.CreationPlanningRequest) (*bridge.CreationPlanningResponse, error) {
		return &bridge.CreationPlanningResponse{Plan: copyAutomaticPlan(req.CurrentPlan), Reply: "重试"}, nil
	}
	startAutomatic(t, r, h, token, row.ID, "new-user-requirements")
	row = waitAutomatic(t, h, row.ID)
	doc, _ = projectDocument(row)
	if row.AutomaticStatus != "completed" || len(f.requests) != 5 || doc.Automation.ImageReviews["visual"].Retries != 1 {
		t.Fatal(doc.Automation.Steps)
	}
	for _, id := range doc.Automation.ImageReviews["visual"].CandidateIDs {
		if id == "old-requirements" {
			t.Fatal("stale candidates retained after user edit")
		}
	}
}

func TestBestImageReviewBatchVisitsEveryCandidateWithBoundedPreviews(t *testing.T) {
	history := &creativeImageReview{CandidateIDs: []string{"a", "b", "c", "d", "e", "f", "g"}}
	seen := map[string]bool{}
	for history.Compared < len(history.CandidateIDs) {
		batch, end := bestImageReviewBatch(history)
		if len(batch) > 4 || end <= history.Compared {
			t.Fatal("invalid comparison batch", batch, end)
		}
		for _, id := range batch {
			seen[id] = true
		}
		history.Compared, history.BestAssetID = end, batch[0]
	}
	if len(seen) != 7 {
		t.Fatal("history was truncated", seen)
	}
}

func TestBestImageReviewDropsDeletedAndForeignCandidates(t *testing.T) {
	r, h, _, token, row := setupAutomatic(t)
	own := libraryUpload(t, r, token, row.ID, "own.png")
	bob, _ := createAccountSession("bob")
	other := createTestProject(t, r, bob)
	foreign := libraryUpload(t, r, bob, other.ID, "foreign.png")
	history := &creativeImageReview{Retries: 5, CandidateIDs: []string{"deleted", foreign.ID, own.ID}, Compared: 1, BestAssetID: foreign.ID}
	if err := h.availableImageReviewHistory(row.UserID, history); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(history.CandidateIDs, []string{own.ID}) || history.Compared != 0 || history.BestAssetID != "" || history.Retries != 5 {
		t.Fatal(history)
	}
}

func TestAutomaticImageBudgetRejectsForeignChoiceAndFurtherRevision(t *testing.T) {
	for _, decision := range []string{"revise", "select"} {
		t.Run(decision, func(t *testing.T) {
			r, h, f, token, row := setupAutomatic(t)
			// Generate the first batch manually, then emulate a persisted exhausted budget.
			row = reviewTestNode(t, r, h, token, row.ID, "brief", "")
			response := creationRequest(t, r, token, "POST", "/api/creation/projects/"+row.ID+"/generate", map[string]interface{}{"revision": row.Revision, "node_id": "visual", "request_id": "initial"})
			if response.Code != 202 {
				t.Fatal(response.Code, response.Body.String())
			}
			var run models.CreationRun
			if err := h.db.Where("project_id = ?", row.ID).First(&run).Error; err != nil {
				t.Fatal(err)
			}
			waitCreativeRun(t, h, run.ID)
			row = readTestProject(t, h, row.ID)
			doc, _ := projectDocument(row)
			doc.Automation = &creativeAutomation{ImageReviews: map[string]*creativeImageReview{"visual": {Revision: doc.States["visual"].Revision, Retries: 5}}}
			if err := h.updateProject(&row, doc, false); err != nil {
				t.Fatal(err)
			}
			f.reviewDecision = func(req bridge.CreationReviewRequest) *bridge.CreationReviewResponse {
				if req.NodeID != "visual" {
					return nil
				}
				return &bridge.CreationReviewResponse{Decision: decision, AssetID: "foreign", Reason: "无效结果"}
			}
			generated := len(f.requests)
			startAutomatic(t, r, h, token, row.ID, "invalid-best")
			row = waitAutomatic(t, h, row.ID)
			doc, _ = projectDocument(row)
			if row.AutomaticStatus != "failed" || len(f.requests) != generated || creativeApproved(doc.States["visual"]) {
				t.Fatal("invalid best result accepted", doc.Automation.Steps)
			}
		})
	}
}

func TestFinalFailedForegroundEndsPendingGenerationWithoutMoreRepair(t *testing.T) {
	_, h, f, _, row := setupAutomatic(t)
	doc, _ := projectDocument(row)
	node, _ := creativeNode(doc, "visual")
	doc.Automation = &creativeAutomation{ImageReviews: map[string]*creativeImageReview{
		"visual": {Revision: doc.States["visual"].Revision, Retries: 5, PendingGeneration: true, CandidateIDs: []string{"earlier"}},
	}}
	h.mu.Lock()
	stop, err := h.repairAutomatic(context.Background(), row, doc, node, nil, "前景无效", "unused", nil)
	if stop || err != nil {
		t.Fatal(stop, err)
	}
	row = readTestProject(t, h, row.ID)
	doc, _ = projectDocument(row)
	history := doc.Automation.ImageReviews["visual"]
	if history.PendingGeneration || history.Retries != 5 || len(f.requests) != 0 || !f.deadline.IsZero() {
		t.Fatal("exhausted foreground started another repair", history)
	}
	ids, end := bestImageReviewBatch(history)
	if end != 1 || len(ids) != 1 || ids[0] != "earlier" {
		t.Fatal(ids, end)
	}
}
