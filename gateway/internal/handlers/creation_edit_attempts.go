package handlers

import (
	"encoding/json"
	"reflect"
	"strings"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/models"
)

// Read the immutable submitted operation, never infer it from today's plan.
// Legacy feedback is recoverable only while all candidate provenance exists.
func (h *CreationHandler) repairExecution(row models.CreationProject, nodeID string, candidates []string) *bridge.CreationRepairExecution {
	if len(candidates) == 0 {
		return nil
	}
	var result *bridge.CreationRepairExecution
	for _, id := range candidates {
		var run models.CreationRun
		if h.db.Table("creation_runs AS r").Select("r.*").Joins("JOIN creation_assets AS a ON a.run_id = r.id AND a.user_id = r.user_id").
			Where("a.id = ? AND a.user_id = ? AND r.project_id = ? AND r.project_node_id = ?", id, row.UserID, row.ID, nodeID).Take(&run).Error != nil {
			return nil
		}
		var graph creationGraph
		if json.Unmarshal([]byte(run.Definition), &graph) != nil || len(graph.Nodes) != 1 {
			return nil
		}
		node := graph.Nodes[0]
		if node.ID != nodeID || node.Kind != "image" {
			return nil
		}
		execution := &bridge.CreationRepairExecution{Operation: "generate"}
		switch node.ImageOperation {
		case "":
		case "edit":
			if len(node.AssetIDs) != 1 || node.AssetIDs[0] == "" {
				return nil
			}
			execution.Operation, execution.EditSourceAssetID = "edit", node.AssetIDs[0]
		default:
			return nil
		}
		if result != nil && !reflect.DeepEqual(result, execution) {
			return nil
		}
		result = execution
	}
	return result
}

func (h *CreationHandler) repairAttempts(row models.CreationProject, nodeID string, history []bridge.CreationRepairFeedback) []bridge.CreationRepairAttempt {
	result := []bridge.CreationRepairAttempt{}
	for _, earlier := range history {
		if earlier.NodeID != nodeID {
			continue
		}
		execution := earlier.Execution
		if execution == nil {
			execution = h.repairExecution(row, nodeID, earlier.CandidateIDs)
		}
		result = append(result, bridge.CreationRepairAttempt{Attempt: earlier.Attempt, CandidateIDs: earlier.CandidateIDs, Findings: earlier.Findings, Execution: execution})
	}
	if len(result) > 10 {
		result = result[len(result)-10:]
	}
	return result
}

// Defense in depth for a model response that ignores the operation budget.
// A different failed requirement or unknown legacy operation starts no chain.
func exhaustedEdits(req bridge.CreationPlanningRequest) bool {
	r := req.Repair
	if !req.AutomaticMode || r == nil || len(r.PreviousAttempts) < 2 {
		return false
	}
	for _, id := range req.LockedNodeIDs {
		if id == r.NodeID {
			return false
		}
	}
	node, exists := creativeNode(creativeDocument{Plan: req.CurrentPlan}, r.NodeID)
	if !exists || node.Kind != "image" {
		return false
	}
	chain := append([]bridge.CreationRepairAttempt{}, r.PreviousAttempts[len(r.PreviousAttempts)-2:]...)
	chain = append(chain, bridge.CreationRepairAttempt{Attempt: r.Attempt, CandidateIDs: r.CandidateIDs, Findings: r.Findings, Execution: r.Execution})
	type issue struct{ category, source, quote string }
	var common map[issue]bool
	for i, attempt := range chain {
		if attempt.Execution == nil || attempt.Execution.Operation != "edit" || attempt.Execution.EditSourceAssetID == "" || len(attempt.CandidateIDs) == 0 {
			return false
		}
		if i > 0 {
			linked := false
			for _, id := range chain[i-1].CandidateIDs {
				linked = linked || id == attempt.Execution.EditSourceAssetID
			}
			if !linked || attempt.Attempt != chain[i-1].Attempt+1 {
				return false
			}
		}
		candidates, reviewed := map[string]bool{}, map[string]bool{}
		for _, id := range attempt.CandidateIDs {
			candidates[id] = true
		}
		issues := map[issue]bool{}
		for _, finding := range attempt.Findings {
			reviewed[finding.CandidateID] = true
			issues[issue{finding.Category, finding.SourceID, finding.RequirementQuote}] = true
		}
		if !reflect.DeepEqual(candidates, reviewed) {
			return false
		}
		if common == nil {
			common = issues
		} else {
			next := map[issue]bool{}
			for old := range common {
				for current := range issues {
					if old.category == current.category && old.source == current.source && old.quote != "" && current.quote != "" &&
						(strings.Contains(old.quote, current.quote) || strings.Contains(current.quote, old.quote)) {
						if len(old.quote) < len(current.quote) {
							next[old] = true
						} else {
							next[current] = true
						}
					}
				}
			}
			common = next
		}
	}
	return len(common) > 0
}
