package handlers

import (
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/models"
)

func TestCreationPlanningCatalogueSupportsDozensAndPrioritizesCurrentNode(t *testing.T) {
	r, h, _, token := setupCreation(t)
	row := createTestProject(t, r, token)
	row = readTestProject(t, h, row.ID)
	doc := emptyCreativeDocument()
	doc.Plan.Title = "大项目"
	doc.Plan.Summary = "五十个场景"
	ids := []string{}
	for i := 0; i < 50; i++ {
		a := libraryUpload(t, r, token, row.ID, fmt.Sprintf("scene-%d.png", i))
		ids = append(ids, a.ID)
		n := bridge.CreativeNode{ID: fmt.Sprintf("scene-%d", i), Kind: "image", Purpose: "scene", Title: "环境", Prompt: "wide forest", Count: 1, AspectRatio: "16:9", DurationSeconds: 5}
		doc.Plan.Nodes = append(doc.Plan.Nodes, n)
		doc.States[n.ID] = creativeNodeState{Revision: 1, SelectedAssetID: a.ID}
	}
	doc.AssetIDs = []string{ids[0]}
	if err := h.updateProject(&row, doc, false); err != nil {
		t.Fatal(err)
	}
	// An unrelated old image cannot break a focused edit just because it cannot
	// be used as a fresh image input; metadata is enough for reference validation.
	var old models.CreationAsset
	h.db.First(&old, "id = ?", ids[1])
	h.db.Model(&models.DriveItem{}).Where("id = ?", old.DriveItemID).Update("encoding", "legacy")
	f := &fakeCreativePlanner{response: &bridge.CreationPlanningResponse{Reply: "已调整", Plan: doc.Plan}, wait: make(chan struct{}), called: make(chan bridge.CreationPlanningRequest, 1)}
	h.generator = f
	response := creationRequest(t, r, token, "POST", "/api/creation/projects/"+row.ID+"/messages", map[string]interface{}{"revision": row.Revision, "message": "只调整当前场景", "node_id": "scene-49", "request_id": "large-edit"})
	if response.Code != 202 {
		t.Fatal(response.Code, response.Body.String())
	}
	req := <-f.called
	if len(req.Assets) != 50 {
		t.Fatal("catalogue lost prior references", len(req.Assets))
	}
	previews := map[string]bool{}
	for _, a := range req.Assets {
		if a.DataURL != "" {
			previews[a.ID] = true
		}
	}
	if len(previews) != 1 || !previews[ids[49]] {
		t.Fatal("focused previews", previews)
	}
	close(f.wait)
	for deadline := time.Now().Add(time.Second); time.Now().Before(deadline); {
		row = readTestProject(t, h, row.ID)
		if !row.Planning {
			break
		}
		time.Sleep(time.Millisecond)
	}
	if row.Planning || row.Error != "" {
		t.Fatal("editing failed", row.Error)
	}
	if _, err := h.planningAssets("bob", ids, nil); err == nil {
		t.Fatal("foreign metadata leaked")
	}
}

func TestPlanningPreviewsBoundedAndAutomaticCandidatesComeFirst(t *testing.T) {
	r, h, _, token := setupCreation(t)
	row := createTestProject(t, r, token)
	row = readTestProject(t, h, row.ID)
	doc := emptyCreativeDocument()
	doc.Automation = &creativeAutomation{}
	for i := 0; i < 40; i++ {
		a := libraryUpload(t, r, token, row.ID, fmt.Sprintf("%d.png", i))
		doc.AssetIDs = append(doc.AssetIDs, a.ID)
	}
	candidate := libraryUpload(t, r, token, row.ID, "candidate.png")
	req, err := h.automaticRequest(row, doc, bridge.CreativeNode{ID: "target", Kind: "image"}, []string{candidate.ID})
	if err != nil {
		t.Fatal(err)
	}
	count := 0
	for _, a := range req.Assets {
		if a.DataURL != "" {
			count++
		}
	}
	if len(req.Assets) != 41 || count != 1 || req.Assets[0].ID != candidate.ID || req.Assets[0].DataURL == "" {
		t.Fatal("candidate preview missing or unbounded", count, len(req.Assets))
	}
	_, err = h.planningAssets("alice", append(doc.AssetIDs, "foreign"), nil)
	if err == nil || !strings.Contains(err.Error(), "资产") {
		t.Fatal("invalid catalogue accepted")
	}
}

func TestCreativeNodeCapacityAllowsMultiEpisodeScenesButRemainsBounded(t *testing.T) {
	p := bridge.CreativePlan{Title: "多场景", Summary: "six episodes"}
	g := creationGraph{}
	for i := 0; i < 64; i++ {
		id := fmt.Sprintf("n%d", i)
		p.Nodes = append(p.Nodes, bridge.CreativeNode{ID: id, Kind: "text", Title: id, Content: "脚本"})
		g.Nodes = append(g.Nodes, creationTestNode(id, "image"))
	}
	if err := validateCreativePlan(p, nil); err != nil {
		t.Fatal(err)
	}
	if err := validateCreationGraph(g, true); err != nil {
		t.Fatal(err)
	}
	p.Nodes = append(p.Nodes, bridge.CreativeNode{ID: "extra", Kind: "text", Title: "extra", Content: "x"})
	g.Nodes = append(g.Nodes, creationTestNode("extra", "image"))
	if validateCreativePlan(p, nil) == nil || validateCreationGraph(g, true) == nil {
		t.Fatal("node cap lost")
	}
}

func TestShotReviewPixelsAreLimitedToSelectedInputsAndCandidates(t *testing.T) {
	doc := emptyCreativeDocument()
	doc.AssetIDs = []string{"unrelated-rabbit", "old-sheet"}
	doc.Plan = bridge.CreativePlan{Nodes: []bridge.CreativeNode{
		{ID: "person", Kind: "image", AssetID: "target-person", References: []bridge.CreativeReference{{AssetID: "old-sheet", Role: "style"}}},
		{ID: "scene", Kind: "image", Purpose: "scene", AssetID: "target-scene"},
		{ID: "shot", Kind: "image", Purpose: "shot_reference", DependsOn: []string{"person", "scene"}, References: []bridge.CreativeReference{{NodeID: "person", Role: "identity"}, {NodeID: "scene", Role: "environment"}}},
	}}
	ids, previews := planningAssetContext(doc, "shot", nil, []string{"candidate"})
	if len(ids) != 5 || len(previews) != 3 {
		t.Fatal(ids, previews)
	}
	for _, id := range previews {
		if id == "unrelated-rabbit" || id == "old-sheet" {
			t.Fatal("unrelated identity leaked into review", previews)
		}
	}
}
