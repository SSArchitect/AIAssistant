package handlers

import (
	"context"
	"fmt"
	"testing"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/models"
)

func TestRepairHistoryRecordsActualOperationsAndReplansAfterThreeFailedEdits(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	repairs := 0
	f.reviewDecision = func(req bridge.CreationReviewRequest) *bridge.CreationReviewResponse {
		if req.NodeID != "visual" || repairs >= 4 {
			return nil
		}
		findings := []bridge.CreationReviewFinding{}
		for _, id := range req.CandidateIDs {
			findings = append(findings, bridge.CreationReviewFinding{CandidateID: id, Category: "scale", SourceID: "target", RequirementQuote: "占画高10%", Observation: "占25%"})
		}
		return &bridge.CreationReviewResponse{Decision: "revise", Reason: "主体过大", Findings: findings}
	}
	f.planHook = func(_ context.Context, req bridge.CreationPlanningRequest) (*bridge.CreationPlanningResponse, error) {
		repairs++
		feedback := req.Repair
		if feedback.Execution == nil || len(feedback.PreviousAttempts) != repairs-1 {
			t.Fatal("missing actual execution history", feedback)
		}
		expected := "edit"
		if repairs == 1 {
			expected = "generate"
		}
		if feedback.Execution.Operation != expected {
			t.Fatal("wrong operation", feedback.Execution)
		}
		p := copyAutomaticPlan(req.CurrentPlan)
		p.Nodes[1].Count = 1
		p.Nodes[1].EditSourceAssetID = feedback.CandidateIDs[0]
		p.Nodes[1].Prompt = fmt.Sprintf("Change size attempt %d", repairs)
		if exhaustedEdits(req) != (repairs == 4) {
			t.Fatal("wrong edit budget", repairs, feedback)
		}
		if repairs == 4 {
			if validateEditSources(creativeDocument{Plan: req.CurrentPlan}, p, req) == nil {
				t.Fatal("repeated failed edit allowed")
			}
			p.Nodes[1].EditSourceAssetID = ""
			p.Nodes[1].Prompt = "Generate a wide composition with small subject using original references"
		}
		return &bridge.CreationPlanningResponse{Reply: "重新规划并复审", Plan: p}, nil
	}
	startAutomatic(t, r, h, token, row.ID, "edit-budget")
	row = waitAutomatic(t, h, row.ID)
	doc, _ := projectDocument(row)
	if row.AutomaticStatus != "completed" || repairs != 4 || !creativeApproved(doc.States["visual"]) {
		t.Fatal(row.AutomaticStatus, repairs, doc.Automation.Steps)
	}
	for _, earlier := range doc.Automation.Repairs {
		if earlier.Execution == nil || len(earlier.PreviousAttempts) != 0 || len(earlier.PreviousFeedback) != 0 {
			t.Fatal("history missing or recursively nested", earlier)
		}
	}
	if len(f.requests) != 7 || f.requests[5].ImageOperation != "" {
		t.Fatal("did not switch back to generation", len(f.requests))
	}
}

func TestRepairExecutionBackfillsLegacyHistoryOnlyFromSameNodeSubmittedRun(t *testing.T) {
	_, h, _, _, row := setupAutomatic(t)
	graph := creationGraph{Nodes: []creationNode{{ID: "visual", Kind: "image", ImageOperation: "edit", AssetIDs: []string{"source"}}}}
	run := models.CreationRun{ID: "origin", UserID: row.UserID, ProjectID: row.ID, ProjectNodeID: "visual", Definition: creationJSON(graph)}
	asset := models.CreationAsset{ID: "draft", UserID: row.UserID, RunID: run.ID}
	if h.db.Create(&run).Error != nil || h.db.Create(&asset).Error != nil {
		t.Fatal("seed")
	}
	legacy := []bridge.CreationRepairFeedback{{NodeID: "visual", Attempt: 2, CandidateIDs: []string{"draft"}}}
	result := h.repairAttempts(row, "visual", legacy)
	if len(result) != 1 || result[0].Execution == nil || result[0].Execution.Operation != "edit" || result[0].Execution.EditSourceAssetID != "source" {
		t.Fatal(result)
	}
	if legacy[0].Execution != nil {
		t.Fatal("mutated persisted history")
	}
	for _, name := range []string{"account", "project", "node", "missing", "mixed", "definition"} {
		t.Run(name, func(t *testing.T) {
			owner, node, ids := row, "visual", []string{"draft"}
			switch name {
			case "account":
				owner.UserID = "other"
			case "project":
				owner.ID = "other"
			case "node":
				node = "other"
			case "missing":
				ids = []string{"unknown"}
			case "mixed":
				ids = append(ids, "unknown")
			case "definition":
				h.db.Model(&run).Update("definition", "{}")
			}
			if h.repairExecution(owner, node, ids) != nil {
				t.Fatal("unproven execution inferred", name)
			}
		})
	}
}

func TestEditBudgetRequiresConsecutiveProvenFailuresOfSameRequirement(t *testing.T) {
	for _, name := range []string{"valid", "nested-quote", "unknown", "only-two", "generation", "different-issue", "different-quote", "different-source", "different-lineage", "gap", "missing-findings", "manual", "locked"} {
		t.Run(name, func(t *testing.T) {
			attempts := []bridge.CreationRepairAttempt{}
			for i := 1; i <= 3; i++ {
				id := fmt.Sprintf("draft-%d", i)
				attempts = append(attempts, bridge.CreationRepairAttempt{Attempt: i, CandidateIDs: []string{id},
					Findings:  []bridge.CreationReviewFinding{{CandidateID: id, Category: "scale", SourceID: "target", RequirementQuote: "占画高10%"}},
					Execution: &bridge.CreationRepairExecution{Operation: "edit", EditSourceAssetID: fmt.Sprintf("draft-%d", i-1)}})
			}
			req := bridge.CreationPlanningRequest{AutomaticMode: true, CurrentPlan: creativeTestPlan(), Repair: &bridge.CreationRepairFeedback{
				NodeID: "visual", Attempt: 3, CandidateIDs: attempts[2].CandidateIDs, Findings: attempts[2].Findings, Execution: attempts[2].Execution, PreviousAttempts: attempts[:2]}}
			r := req.Repair
			switch name {
			case "nested-quote":
				r.PreviousAttempts[0].Findings[0].RequirementQuote = "整体占画高10%，脚踩飞剑。"
			case "unknown":
				r.PreviousAttempts[0].Execution = nil
			case "only-two":
				r.PreviousAttempts = r.PreviousAttempts[1:]
			case "generation":
				r.PreviousAttempts[0].Execution.Operation = "generate"
			case "different-issue":
				r.PreviousAttempts[0].Findings[0].Category = "environment"
			case "different-quote":
				r.PreviousAttempts[0].Findings[0].RequirementQuote = "树占画高90%"
			case "different-source":
				r.PreviousAttempts[0].Findings[0].SourceID = "other"
			case "different-lineage":
				r.Execution.EditSourceAssetID = "unknown"
			case "gap":
				r.PreviousAttempts[0].Attempt = 0
			case "missing-findings":
				r.PreviousAttempts[0].Findings = nil
			case "manual":
				req.AutomaticMode = false
			case "locked":
				req.LockedNodeIDs = []string{"visual"}
			}
			if exhaustedEdits(req) != (name == "valid" || name == "nested-quote") {
				t.Fatal(name)
			}
		})
	}
}
