package handlers

import (
	"encoding/json"
	"reflect"
	"testing"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
)

func repairHistoryDocument() creativeDocument {
	plan := bridge.CreativePlan{Title: "测试", Nodes: []bridge.CreativeNode{
		{ID: "scene", Kind: "image", Prompt: "原场景", Content: "原场景要求"},
		{ID: "shot", Kind: "image", Prompt: "原分镜", DependsOn: []string{"scene"}},
		{ID: "independent", Kind: "image", Prompt: "独立分镜"},
		{ID: "removed", Kind: "image", Prompt: "将删除的分镜"},
	}}
	doc := applyCreativePlan(emptyCreativeDocument(), plan)
	doc.Automation = &creativeAutomation{RepairCounts: map[string]int{}, Repairs: []bridge.CreationRepairFeedback{}}
	for _, node := range plan.Nodes {
		doc.Automation.RepairCounts[node.ID] = 3
		doc.Automation.Repairs = append(doc.Automation.Repairs, bridge.CreationRepairFeedback{NodeID: node.ID, Reason: "旧要求的失败反馈", Attempt: 3})
	}
	return doc
}

func TestUserPlanEditClearsChangedAndDownstreamHistoryButKeepsIndependentHistory(t *testing.T) {
	doc := repairHistoryDocument()
	plan := copyAutomaticPlan(doc.Plan)
	plan.Nodes = plan.Nodes[:3]
	plan.Nodes[0].Content = "用户新的场景要求"
	updated := applyCreativePlan(doc, plan)
	if !reflect.DeepEqual(updated.Automation.RepairCounts, map[string]int{"independent": 3}) || len(updated.Automation.Repairs) != 1 || updated.Automation.Repairs[0].NodeID != "independent" {
		t.Fatal("user edit kept stale feedback or removed unrelated feedback", updated.Automation)
	}
	if len(doc.Automation.RepairCounts) != 4 || len(doc.Automation.Repairs) != 4 {
		t.Fatal("editing the proposal mutated its previous snapshot")
	}
	data, err := json.Marshal(updated)
	if err != nil {
		t.Fatal(err)
	}
	var restored creativeDocument
	if err := json.Unmarshal(data, &restored); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(restored.Automation.RepairCounts, updated.Automation.RepairCounts) {
		t.Fatal("history filtering did not survive persistence")
	}
}

func TestAutomaticRepairRetainsHistoryAcrossExecutionChanges(t *testing.T) {
	doc := repairHistoryDocument()
	plan := copyAutomaticPlan(doc.Plan)
	plan.Nodes[0].Prompt = "新的执行策略，不改变创作目标"
	updated := applyAutomaticRepair(doc, plan)
	if !reflect.DeepEqual(updated.Automation.RepairCounts, doc.Automation.RepairCounts) || !reflect.DeepEqual(updated.Automation.Repairs, doc.Automation.Repairs) {
		t.Fatal("automatic repair erased its own previous failures")
	}
	if updated.States["scene"].Revision <= doc.States["scene"].Revision || updated.States["shot"].Revision <= doc.States["shot"].Revision {
		t.Fatal("fixture did not exercise invalidated execution state")
	}
}

func TestSuggestionOnlyUpdatePreservesRepairHistory(t *testing.T) {
	doc := repairHistoryDocument()
	plan := copyAutomaticPlan(doc.Plan)
	plan.Nodes[0].RevisionSuggestions = []bridge.CreativeRevisionSuggestion{{Label: "更远", Instruction: "使用更远的机位"}}
	updated := applyCreativePlan(doc, plan)
	if !reflect.DeepEqual(updated.Automation.RepairCounts, doc.Automation.RepairCounts) || !reflect.DeepEqual(updated.Automation.Repairs, doc.Automation.Repairs) {
		t.Fatal("changing optional UI suggestions erased useful history")
	}
}

func TestUserCandidateReviewClearsOnlyObsoleteRepairHistory(t *testing.T) {
	for _, switchCandidate := range []bool{false, true} {
		name := "same candidate"
		if switchCandidate {
			name = "new candidate"
		}
		t.Run(name, func(t *testing.T) {
			r, h, _, token := setupCreation(t)
			row := seedCreativePlan(t, h, createTestProject(t, r, token))
			row = reviewTestNode(t, r, h, token, row.ID, "brief", "")
			a, err := h.saveAsset("alice", "a.png", creationPNG, "image/png", "generated", "old-run", "visual", "")
			if err != nil {
				t.Fatal(err)
			}
			b, err := h.saveAsset("alice", "b.png", creationPNG, "image/png", "generated", "old-run", "visual", "")
			if err != nil {
				t.Fatal(err)
			}
			doc, _ := projectDocument(row)
			state := doc.States["visual"]
			state.Candidates = []string{a.ID, b.ID}
			doc.States["visual"] = state
			if err := h.updateProject(&row, doc, false); err != nil {
				t.Fatal(err)
			}
			row = reviewTestNode(t, r, h, token, row.ID, "visual", a.ID)
			doc, _ = projectDocument(row)
			doc.Automation = &creativeAutomation{RepairCounts: map[string]int{"visual": 1, "video": 2, "script": 3}}
			for _, id := range []string{"visual", "video", "script"} {
				doc.Automation.Repairs = append(doc.Automation.Repairs, bridge.CreationRepairFeedback{NodeID: id, Reason: "旧候选反馈"})
			}
			if err := h.updateProject(&row, doc, false); err != nil {
				t.Fatal(err)
			}
			selected := a.ID
			want := map[string]int{"video": 2, "script": 3}
			if switchCandidate {
				selected = b.ID
				delete(want, "video")
			}
			row = reviewTestNode(t, r, h, token, row.ID, "visual", selected)
			doc, _ = projectDocument(row)
			if !reflect.DeepEqual(doc.Automation.RepairCounts, want) || len(doc.Automation.Repairs) != len(want) {
				t.Fatal("candidate review discarded independent history or retained obsolete feedback", doc.Automation)
			}
			for _, repair := range doc.Automation.Repairs {
				if want[repair.NodeID] == 0 {
					t.Fatal("obsolete review feedback survived", repair.NodeID)
				}
			}
		})
	}
}
