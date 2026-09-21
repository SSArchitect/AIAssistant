package handlers

import (
	"context"
	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"testing"
)

func TestInvalidForegroundReturnsToPlannerInsteadOfReplayingSameFailedTask(t *testing.T) {
	r, h, base, token, row := setupAutomatic(t)
	scene, err := h.saveAsset(row.UserID, "scene.png", creationPNG, "image/png", "upload", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	identity, err := h.saveAsset(row.UserID, "identity.png", "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEElEQVR4nGP8zwACTGCSAQANHQEDgslx/wAAAABJRU5ErkJggg==", "image/png", "upload", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	doc, _ := projectDocument(row)
	doc.Plan.Nodes = doc.Plan.Nodes[:2]
	n := &doc.Plan.Nodes[1]
	n.Purpose = "shot_reference"
	n.Count = 1
	n.References = []bridge.CreativeReference{{AssetID: scene.ID, Role: "environment"}, {AssetID: identity.ID, Role: "identity"}}
	n.ImageLayout = []bridge.ImagePlacement{{CenterXPercent: 32, CenterYPercent: 18, SubjectHeightPercent: 4, SubjectPrompt: "rear rider", CompositeMode: "foreground_v1"}}
	doc.AssetIDs = []string{scene.ID, identity.ID}
	if err = h.updateProject(&row, doc, false); err != nil {
		t.Fatal(err)
	}
	f := &recoveringDirector{base, 1, &bridge.CreationMediaError{Code: "media_invalid_output", Message: "foreground incomplete", ProviderTaskID: "saved-final-task"}}
	h.generator = f
	repairs := 0
	base.planHook = func(_ context.Context, req bridge.CreationPlanningRequest) (*bridge.CreationPlanningResponse, error) {
		repairs++
		if req.Repair == nil || req.Repair.NodeID != "visual" || len(req.Repair.CandidateIDs) != 0 {
			t.Fatal("missing validation repair", req.Repair)
		}
		p := copyAutomaticPlan(req.CurrentPlan)
		p.Nodes[1].ImageLayout[0].SubjectPrompt = "rear rider with compact complete sword"
		return &bridge.CreationPlanningResponse{Plan: p, Reply: "complete subject"}, nil
	}
	startAutomatic(t, r, h, token, row.ID, "foreground-repair")
	row = waitAutomatic(t, h, row.ID)
	after, _ := projectDocument(row)
	if row.AutomaticStatus != "completed" || repairs != 1 || len(f.requests) != 2 {
		t.Fatal(row.AutomaticStatus, repairs, len(f.requests), after.Automation.Steps)
	}
	if f.requests[0].IdempotencyKey == f.requests[1].IdempotencyKey || f.requests[1].ResumeTaskID != "" {
		t.Fatal("replayed invalid pixels", f.requests)
	}
	if after.States["visual"].ApprovedBy != "agent" || after.Plan.Nodes[1].Content != n.Content {
		t.Fatal("review bypassed or requirement changed")
	}
}

func TestInvalidOrdinaryImageDoesNotEnterForegroundRepair(t *testing.T) {
	r, h, base, token, row := setupAutomatic(t)
	f := &recoveringDirector{base, 1, &bridge.CreationMediaError{Code: "media_invalid_output", Message: "invalid media"}}
	h.generator = f
	repairs := 0
	base.planHook = func(context.Context, bridge.CreationPlanningRequest) (*bridge.CreationPlanningResponse, error) {
		repairs++
		return nil, nil
	}
	startAutomatic(t, r, h, token, row.ID, "ordinary-invalid")
	row = waitAutomatic(t, h, row.ID)
	if row.AutomaticStatus != "failed" || repairs != 0 || len(f.requests) != 1 {
		t.Fatal(row.AutomaticStatus, repairs, len(f.requests))
	}
}
