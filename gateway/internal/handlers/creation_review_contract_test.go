package handlers

import (
	"encoding/json"
	"reflect"
	"testing"
)

func TestReviewContractSurvivesRepairPersistenceButUserEditResetsIt(t *testing.T) {
	doc := applyCreativePlan(emptyCreativeDocument(), creativeTestPlan())
	node := doc.Plan.Nodes[1]
	node.Content, node.Prompt = "侧面御剑", "剑与服装沿用人设图"
	doc.Plan.Nodes[1] = node
	captureReviewContract(&doc, node)
	original := doc.ReviewContracts[node.ID]
	for i := 0; i < 3; i++ {
		plan := copyAutomaticPlan(doc.Plan)
		plan.Nodes[1].Content, plan.Nodes[1].Prompt = "两只脚必须可见", "禁止护手"
		doc = applyAutomaticRepair(doc, plan)
		data, _ := json.Marshal(doc)
		var restored creativeDocument
		if err := json.Unmarshal(data, &restored); err != nil {
			t.Fatal(err)
		}
		doc = restored
		captureReviewContract(&doc, doc.Plan.Nodes[1])
		if !reflect.DeepEqual(doc.ReviewContracts[node.ID], original) || doc.Plan.Nodes[1].Content != "侧面御剑" || doc.Plan.Nodes[1].Prompt != "禁止护手" {
			t.Fatal("execution change moved acceptance criteria", doc.ReviewContracts)
		}
	}
	plan := copyAutomaticPlan(doc.Plan)
	plan.Nodes[1].Content = "用户改为正面御剑"
	doc = applyCreativePlan(doc, plan)
	if _, ok := doc.ReviewContracts[node.ID]; ok {
		t.Fatal("user edit retained obsolete requirement")
	}
	captureReviewContract(&doc, doc.Plan.Nodes[1])
	if doc.ReviewContracts[node.ID].Content != "用户改为正面御剑" {
		t.Fatal("user edit was ignored")
	}
}

func TestReviewContractResetsOnUserUpstreamEditButNotUnrelatedChange(t *testing.T) {
	doc := applyCreativePlan(emptyCreativeDocument(), creativeTestPlan())
	node := doc.Plan.Nodes[1]
	captureReviewContract(&doc, node)
	plan := copyAutomaticPlan(doc.Plan)
	plan.Nodes[3].Prompt = "new video only"
	doc = applyCreativePlan(doc, plan)
	if _, ok := doc.ReviewContracts[node.ID]; !ok {
		t.Fatal("unrelated video edit erased image contract")
	}
	plan = copyAutomaticPlan(doc.Plan)
	plan.Nodes[0].Content = "new brief"
	doc = applyCreativePlan(doc, plan)
	if _, ok := doc.ReviewContracts[node.ID]; ok {
		t.Fatal("upstream user edit retained stale contract")
	}
}
