package handlers

import (
	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"testing"
)

func TestRegionRepairRejectsInactiveFieldChangesButAcceptsEffectiveRecipeChanges(t *testing.T) {
	old := creativeTestPlan()
	old.Nodes[1].ImageLayout = []bridge.ImagePlacement{{CenterXPercent: 32, CenterYPercent: 25, SubjectHeightPercent: 4, SubjectPrompt: "rear rabbit"}}
	repair := &bridge.CreationRepairFeedback{NodeID: "visual"}
	for _, kind := range []string{"none", "prompt", "title", "count", "local", "reference", "upstream", "switch"} {
		t.Run(kind, func(t *testing.T) {
			next := copyAutomaticPlan(old)
			switch kind {
			case "prompt":
				next.Nodes[1].Prompt = "long ears"
			case "title":
				next.Nodes[1].Title = "long ears"
			case "count":
				next.Nodes[1].Count = 3
			case "local":
				next.Nodes[1].ImageLayout[0].SubjectPrompt = "long white ears, rear rabbit"
			case "reference":
				next.Nodes[1].References = []bridge.CreativeReference{{AssetID: "another", Role: "identity"}}
			case "upstream":
				next.Nodes[0].Content = "new reference requirements"
			case "switch":
				next.Nodes[1].ImageLayout = nil
			}
			err := validateRegionRepair(old, next, repair)
			shouldFail := kind == "none" || kind == "prompt" || kind == "title" || kind == "count"
			if (err != nil) != shouldFail {
				t.Fatal(kind, err)
			}
		})
	}
	old.Nodes[1].ImageLayout = nil
	if validateRegionRepair(old, old, repair) != nil {
		t.Fatal("changed legacy full-frame resampling contract")
	}
}
