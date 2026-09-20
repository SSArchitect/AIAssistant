package handlers

import (
	"encoding/json"
	"reflect"
	"testing"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
)

func TestCreativeStoryboardFormattingKeepsCompletedVideoAndUnrelatedApprovals(t *testing.T) {
	plan := creativeTestPlan()
	plan.Nodes = append(plan.Nodes, bridge.CreativeNode{ID: "other_scene", Kind: "image", Prompt: "giant mushroom", DependsOn: []string{"script"}})
	doc := applyCreativePlan(emptyCreativeDocument(), plan)
	for id, state := range doc.States {
		state.ApprovedRevision = state.Revision
		state.ApprovedBy = "agent"
		state.SelectedAssetID = "original-" + id
		state.Candidates = []string{state.SelectedAssetID}
		state.RunID = "completed-" + id
		doc.States[id] = state
	}
	replacement := plan
	replacement.Nodes = append([]bridge.CreativeNode{}, plan.Nodes...)
	// The planner reserializes RawMessage: key order, whitespace and number
	// spelling change, while the already generated video has the same content.
	replacement.Nodes[3].Storyboard = json.RawMessage(`{
		"shots": [{"description": "Wind in bamboo", "start_seconds": 0.0}],
		"non_diegetic_music": "N/A", "overall_soundscape": "wind", "style": "ink"
	}`)
	replacement.Nodes[4].Prompt = "a concise giant mushroom landscape"
	updated := applyCreativePlan(doc, replacement)
	for _, id := range []string{"brief", "visual", "script", "video"} {
		if !reflect.DeepEqual(updated.States[id], doc.States[id]) {
			t.Fatalf("unrelated confirmed node %s lost its completed asset: %+v", id, updated.States[id])
		}
	}
	if creativeApproved(updated.States["other_scene"]) {
		t.Fatal("the actual image edit must still require review")
	}
}

func TestCreativeStoryboardMeaningfulChangeStillInvalidatesVideo(t *testing.T) {
	for _, replacement := range []string{
		`{"style":"watercolor","shots":[{"start_seconds":0,"description":"Wind in bamboo"}],"overall_soundscape":"wind","non_diegetic_music":"N/A"}`,
		`{"style":"ink","shots":[{"start_seconds":0,"description":"A new action"}],"overall_soundscape":"wind","non_diegetic_music":"N/A"}`,
		`invalid json`,
	} {
		doc := applyCreativePlan(emptyCreativeDocument(), creativeTestPlan())
		state := doc.States["video"]
		state.ApprovedRevision = state.Revision
		state.Candidates = []string{"old-video"}
		state.SelectedAssetID = "old-video"
		doc.States["video"] = state
		plan := creativeTestPlan()
		plan.Nodes[3].Storyboard = json.RawMessage(replacement)
		updated := applyCreativePlan(doc, plan)
		if creativeApproved(updated.States["video"]) || len(updated.States["video"].Candidates) != 0 {
			t.Fatal("a real or invalid storyboard edit retained stale approval")
		}
	}
}
