package handlers

import (
	"context"
	"encoding/json"
	"reflect"
	"testing"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/models"
)

func TestAutomaticDraftEditRetainsRequirementsReviewsNewImageAndPreservesOldAssets(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	var draft string
	reviewedEdited := false
	f.reviewDecision = func(req bridge.CreationReviewRequest) *bridge.CreationReviewResponse {
		if req.NodeID != "visual" {
			return nil
		}
		if draft == "" {
			draft = req.CandidateIDs[0]
			return &bridge.CreationReviewResponse{Decision: "revise", Reason: "主体过大，需要局部缩小"}
		}
		if len(req.CandidateIDs) != 1 || req.CandidateIDs[0] == draft {
			t.Fatal("original draft reused as final", req.CandidateIDs)
		}
		reviewedEdited = true
		return nil
	}
	f.planHook = func(_ context.Context, req bridge.CreationPlanningRequest) (*bridge.CreationPlanningResponse, error) {
		p := copyAutomaticPlan(req.CurrentPlan)
		p.Nodes[1].EditSourceAssetID = draft
		p.Nodes[1].Prompt = "Edit Picture 1: reduce only the rider, preserve the scene"
		p.Nodes[1].Count = 1
		return &bridge.CreationPlanningResponse{Reply: "局部编辑后复审", Plan: p}, nil
	}
	startAutomatic(t, r, h, token, row.ID, "edit-draft")
	row = waitAutomatic(t, h, row.ID)
	doc, _ := projectDocument(row)
	if row.AutomaticStatus != "completed" || !reviewedEdited {
		t.Fatal(row.AutomaticStatus, doc.Automation.Steps)
	}
	if len(f.requests) != 4 || f.requests[2].ImageOperation != "edit" || len(f.requests[2].InputImages) != 1 || len(f.requests[2].ImageReferences) != 0 {
		t.Fatal("wrong edit request", f.requests)
	}
	source, err := h.imageInput(row.UserID, draft)
	if err != nil || source != f.requests[2].InputImages[0] {
		t.Fatal("draft pixels lost")
	}
	if doc.Plan.Nodes[1].AssetID != "" || doc.Plan.Nodes[1].Content != creativeTestPlan().Nodes[1].Content || !creativeApproved(doc.States["visual"]) {
		t.Fatal("acceptance bypassed", doc)
	}
	if !documentUsesAsset(doc, map[string]bool{draft: true}) {
		t.Fatal("editable source could be deleted")
	}
	var run models.CreationRun
	h.db.First(&run, "id = ?", doc.States["visual"].RunID)
	var snapshot creativeDocument
	if json.Unmarshal([]byte(run.Snapshot), &snapshot) != nil || snapshot.Plan.Nodes[1].EditSourceAssetID != draft {
		t.Fatal("edit provenance missing from snapshot")
	}
	before := len(f.requests)
	startAutomatic(t, r, h, token, row.ID, "edit-completed")
	waitAutomatic(t, h, row.ID)
	if len(f.requests) != before {
		t.Fatal("completed edit was resubmitted")
	}
}

func TestDraftEditSourceScopeAndReferenceGuards(t *testing.T) {
	plan := creativeTestPlan()
	doc := creativeDocument{Plan: plan, States: map[string]creativeNodeState{"visual": {Candidates: []string{"draft"}}}}
	req := bridge.CreationPlanningRequest{AutomaticMode: true, Repair: &bridge.CreationRepairFeedback{NodeID: "visual", CandidateIDs: []string{"draft"}}}
	for _, name := range []string{"valid", "foreign", "other-node", "locked", "refs", "frame", "new"} {
		t.Run(name, func(t *testing.T) {
			proposal := copyAutomaticPlan(plan)
			proposal.Nodes[1].EditSourceAssetID = "draft"
			check := req
			if name == "foreign" {
				proposal.Nodes[1].EditSourceAssetID = "other"
			}
			if name == "other-node" {
				check.Repair = &bridge.CreationRepairFeedback{NodeID: "video", CandidateIDs: []string{"draft"}}
			}
			if name == "locked" {
				check.LockedNodeIDs = []string{"visual"}
			}
			if name == "refs" {
				proposal.Nodes[1].References = []bridge.CreativeReference{{AssetID: "identity", Role: "identity"}}
			}
			if name == "frame" {
				proposal.Nodes[1].AspectRatio = "9:16"
			}
			if name == "new" {
				proposal.Nodes[1].ID = "invented"
			}
			err := validateEditSources(doc, proposal, check)
			if (err == nil) != (name == "valid") {
				t.Fatal(name, err)
			}
		})
	}
	proposal := copyAutomaticPlan(plan)
	proposal.Nodes[1].EditSourceAssetID = "draft"
	if err := validateCreativePlan(proposal, map[string]bool{}); err == nil {
		t.Fatal("foreign source allowed")
	}
	proposal.Nodes[1].AssetID = "draft"
	if err := validateCreativePlan(proposal, map[string]bool{"draft": true}); err == nil {
		t.Fatal("draft adopted as output")
	}
}

func TestDraftEditRequiresSameAccountProjectAndNodeProvenance(t *testing.T) {
	_, h, _, _, row := setupAutomatic(t)
	run := models.CreationRun{ID: "origin", UserID: row.UserID, ProjectID: row.ID, ProjectNodeID: "visual"}
	asset := models.CreationAsset{ID: "draft", UserID: row.UserID, RunID: run.ID}
	if h.db.Create(&run).Error != nil || h.db.Create(&asset).Error != nil {
		t.Fatal("seed")
	}
	node := bridge.CreativeNode{ID: "visual", Kind: "image", EditSourceAssetID: "draft"}
	if err := h.validateDraftProvenance(row, node); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"account", "project", "node", "upload"} {
		changed, target := row, node
		switch name {
		case "account":
			changed.UserID = "other"
		case "project":
			changed.ID = "other"
		case "node":
			target.ID = "other"
		case "upload":
			target.EditSourceAssetID = "upload"
		}
		if h.validateDraftProvenance(changed, target) == nil {
			t.Fatal("foreign provenance allowed", name)
		}
	}
}

func TestDraftEditRejectsChangedUpstreamContextBeforeSubmission(t *testing.T) {
	_, h, _, _, row := setupAutomatic(t)
	doc, _ := projectDocument(row)
	original := creationJSON(doc)
	run := models.CreationRun{ID: "draft-origin", UserID: row.UserID, ProjectID: row.ID, ProjectNodeID: "visual", Snapshot: original}
	asset := models.CreationAsset{ID: "draft", UserID: row.UserID, RunID: run.ID}
	if h.db.Create(&run).Error != nil || h.db.Create(&asset).Error != nil {
		t.Fatal("seed")
	}
	for _, name := range []string{"same", "unrelated", "upstream-revision", "upstream-selection", "upstream-content", "references"} {
		t.Run(name, func(t *testing.T) {
			var current creativeDocument
			if err := json.Unmarshal([]byte(original), &current); err != nil {
				t.Fatal(err)
			}
			node := current.Plan.Nodes[1]
			node.EditSourceAssetID = "draft"
			node.Prompt = "Edit this draft"
			switch name {
			case "unrelated":
				current.Plan.Nodes[3].Prompt = "A different video"
			case "upstream-revision":
				s := current.States["brief"]
				s.Revision++
				current.States["brief"] = s
			case "upstream-selection":
				s := current.States["brief"]
				s.SelectedAssetID = "new-asset"
				current.States["brief"] = s
			case "upstream-content":
				current.Plan.Nodes[0].Content = "A different scene"
			case "references":
				node.References = []bridge.CreativeReference{{AssetID: "new-identity", Role: "identity"}}
			}
			err := h.validateDraftContext(row, current, node)
			if (err == nil) != (name == "same" || name == "unrelated") {
				t.Fatal(name, err)
			}
		})
	}
}

func TestDraftEditCannotChangeUpstreamInSameProposal(t *testing.T) {
	plan := creativeTestPlan()
	doc := creativeDocument{Plan: plan, States: map[string]creativeNodeState{"visual": {Candidates: []string{"draft"}}}}
	proposal := copyAutomaticPlan(plan)
	proposal.Nodes[1].EditSourceAssetID = "draft"
	proposal.Nodes[0].Content = "Switch to a desert"
	if validateEditSources(doc, proposal, bridge.CreationPlanningRequest{}) == nil {
		t.Fatal("stale draft accepted with new scene")
	}
}

func TestDraftEditMetadataStaysOutOfReferencePreviews(t *testing.T) {
	plan := creativeTestPlan()
	plan.Nodes[1].EditSourceAssetID = "rejected"
	doc := creativeDocument{Plan: plan, States: map[string]creativeNodeState{"visual": {SelectedAssetID: "edited"}}}
	ids, previews := planningAssetContext(doc, "visual", nil, []string{"edited"})
	if !reflect.DeepEqual(ids, []string{"edited", "rejected"}) || !reflect.DeepEqual(previews, []string{"edited"}) {
		t.Fatal(ids, previews)
	}
	for _, graph := range []creationGraph{
		{Nodes: []creationNode{{ID: "n", Kind: "image", Prompt: "edit", Count: 1, AspectRatio: "1:1", DurationSeconds: 5, ImageOperation: "edit"}}},
		{Nodes: []creationNode{{ID: "n", Kind: "image", Prompt: "edit", Count: 1, AspectRatio: "1:1", DurationSeconds: 5, ImageOperation: "edit", AssetIDs: []string{"a", "b"}}}},
	} {
		if validateCreationGraph(graph, true) == nil {
			t.Fatal("invalid draft input allowed")
		}
	}
}
