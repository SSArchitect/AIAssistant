package handlers

import (
	"encoding/json"
	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"reflect"
	"testing"
)

func TestCreationImageLayoutPersistsInSnapshotAndReachesMediaBridge(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
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
	n.ImageLayout = []bridge.ImagePlacement{{CenterXPercent: 25.5, CenterYPercent: 70, SubjectHeightPercent: 10, SubjectPrompt: "small rider"}}
	if err := validateCreativePlan(doc.Plan, map[string]bool{scene.ID: true, identity.ID: true}); err != nil {
		t.Fatal(err)
	}
	doc.AssetIDs = []string{scene.ID, identity.ID}
	if err := h.updateProject(&row, doc, false); err != nil {
		t.Fatal(err)
	}
	startAutomatic(t, r, h, token, row.ID, "region-layout")
	row = waitAutomatic(t, h, row.ID)
	after, _ := projectDocument(row)
	if row.AutomaticStatus != "completed" || len(f.requests) != 1 || !reflect.DeepEqual(f.requests[0].ImageLayout, n.ImageLayout) {
		t.Fatal(row.AutomaticStatus, f.requests, after.Automation.Steps)
	}
	if after.States["visual"].ApprovedBy != "agent" {
		t.Fatal("review was bypassed")
	}
	var run struct {
		Definition string
		Snapshot   string
	}
	if err := h.db.Table("creation_runs").Where("id = ?", after.States["visual"].RunID).Take(&run).Error; err != nil {
		t.Fatal(err)
	}
	var graph creationGraph
	var snapshot creativeDocument
	if json.Unmarshal([]byte(run.Definition), &graph) != nil || json.Unmarshal([]byte(run.Snapshot), &snapshot) != nil {
		t.Fatal("missing snapshot")
	}
	if !reflect.DeepEqual(graph.Nodes[0].ImageLayout, n.ImageLayout) || !reflect.DeepEqual(snapshot.Plan.Nodes[1].ImageLayout, n.ImageLayout) {
		t.Fatal("layout lost during freeze")
	}
	if len(f.requests[0].ImageReferences) != 2 || len(f.requests[0].InputImages) != 2 {
		t.Fatal("reference roles lost")
	}
	startAutomatic(t, r, h, token, row.ID, "region-completed")
	waitAutomatic(t, h, row.ID)
	if len(f.requests) != 1 {
		t.Fatal("completed job resubmitted")
	}
}

func TestCreationImageLayoutRejectsInvalidPlanAndRawGraph(t *testing.T) {
	for _, kind := range []string{"video", "text", "image"} {
		p := creativeTestPlan()
		n := &p.Nodes[1]
		n.Kind = kind
		n.ImageLayout = []bridge.ImagePlacement{{CenterXPercent: 0, CenterYPercent: 50, SubjectHeightPercent: 10, SubjectPrompt: "rider"}}
		if validateCreativePlan(p, nil) == nil {
			t.Fatal("invalid layout accepted", kind)
		}
	}
	graph := creationGraph{Nodes: []creationNode{{ID: "n", Kind: "image", ImagePurpose: "shot_reference", Prompt: "rider", Count: 1, AspectRatio: "9:16", DurationSeconds: 5, AssetIDs: []string{"a", "b"}, ImageReferences: []bridge.ImageReferenceContext{{Role: "environment"}, {Role: "identity"}}, ImageLayout: []bridge.ImagePlacement{{CenterXPercent: 0, CenterYPercent: 50, SubjectHeightPercent: 10, SubjectPrompt: "rider"}}}}}
	if validateCreationGraph(graph, true) == nil {
		t.Fatal("out-of-bounds raw graph accepted")
	}
}
