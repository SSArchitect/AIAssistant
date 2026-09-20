package handlers

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"image"
	"image/color"
	"image/png"
	"reflect"
	"strings"
	"testing"
)

func shotPlanFixture() bridge.CreativePlan {
	script := bridge.CreativeNode{ID: "script", Kind: "text", Purpose: "script", Title: "script", Content: "A rabbit flies"}
	scene := bridge.CreativeNode{ID: "scene", Kind: "image", Purpose: "scene", Title: "scene", Prompt: "forest", Count: 1, AspectRatio: "16:9", DurationSeconds: 5}
	shot := bridge.CreativeNode{ID: "frame", Kind: "image", Purpose: "shot_reference", Title: "frame", Prompt: "rabbit in forest", Count: 1, AspectRatio: "16:9", DurationSeconds: 5, DependsOn: []string{"script", "scene"}, References: []bridge.CreativeReference{{AssetID: "rabbit", Role: "identity"}, {NodeID: "scene", Role: "environment"}}}
	video := bridge.CreativeNode{ID: "video", Kind: "video", Title: "video", Prompt: "motion", Count: 1, AspectRatio: "16:9", DurationSeconds: 5, ShotIDs: []string{"flight"}, Storyboard: json.RawMessage(`{"shots":[{"start_seconds":0}]}`), DependsOn: []string{"script", "scene", "frame"}, References: []bridge.CreativeReference{{NodeID: "scene", Role: "reference"}, {NodeID: "frame", Role: "reference", ShotIDs: []string{"flight"}}}}
	return bridge.CreativePlan{Title: "trip", Summary: "trip", Nodes: []bridge.CreativeNode{script, scene, shot, video}}
}

func TestCreationThreeReferenceInputsAndShotBindings(t *testing.T) {
	p := shotPlanFixture()
	if err := validateCreativePlan(p, map[string]bool{"rabbit": true}); err != nil {
		t.Fatal(err)
	}
	p.Nodes[2].References = append(p.Nodes[2].References, bridge.CreativeReference{AssetID: "prop", Role: "reference"})
	if err := validateCreativePlan(p, map[string]bool{"rabbit": true, "prop": true}); err != nil {
		t.Fatal(err)
	}
	p.Nodes[2].References = append(p.Nodes[2].References, bridge.CreativeReference{AssetID: "fourth", Role: "identity"})
	if err := validateCreativePlan(p, map[string]bool{"rabbit": true, "prop": true, "fourth": true}); err == nil {
		t.Fatal("accepted fourth image")
	}
}
func TestCreationRejectsWrongShotAndEnvironmentBindings(t *testing.T) {
	for _, scenario := range []string{"unknown", "missing", "identity", "aspect", "environment"} {
		t.Run(scenario, func(t *testing.T) {
			p := shotPlanFixture()
			switch scenario {
			case "unknown":
				p.Nodes[3].References[1].ShotIDs = []string{"other"}
			case "missing":
				p.Nodes[3].References[1].ShotIDs = nil
			case "identity":
				p.Nodes[3].References[1].Role = "identity"
			case "aspect":
				p.Nodes[2].AspectRatio = "9:16"
			case "environment":
				p.Nodes[1].Purpose = "character"
			}
			if err := validateCreativePlan(p, map[string]bool{"rabbit": true}); err == nil {
				t.Fatal("invalid binding accepted")
			}
		})
	}
}
func TestCreationShotInputOrderAcrossGateway(t *testing.T) {
	r, h, f, token := setupCreation(t)
	a, err := h.saveAsset("alice", "rabbit.png", creationPNG, "image/png", "upload", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	b, err := h.saveAsset("alice", "forest.png", creationPNG, "image/png", "upload", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	// The references carry ordered responsibilities through the Gateway bridge.
	node := creationTestNode("frame", "image")
	node.ImagePurpose = "shot_reference"
	node.AssetIDs = []string{a.ID, b.ID}
	node.ImageReferences = []bridge.ImageReferenceContext{{Role: "identity", Note: "rabbit"}, {Role: "environment", Note: "forest"}}
	saved := creationRequest(t, r, token, "POST", "/api/creation/definitions", definitionBody("workflow", creationGraph{Nodes: []creationNode{node}}))
	if saved.Code != 200 {
		t.Fatal(saved.Code, saved.Body.String())
	}
	var definition struct {
		Definition struct {
			ID string `json:"id"`
		} `json:"definition"`
	}
	json.Unmarshal(saved.Body.Bytes(), &definition)
	response := creationRequest(t, r, token, "POST", "/api/creation/runs", map[string]string{"workflow_id": definition.Definition.ID})
	if response.Code != 202 {
		t.Fatal(response.Code, response.Body.String())
	}
	var body struct {
		Run struct {
			ID string `json:"id"`
		} `json:"run"`
	}
	json.Unmarshal(response.Body.Bytes(), &body)
	run := waitCreativeRun(t, h, body.Run.ID)
	if run.Status != "completed" || len(f.requests) != 1 || len(f.requests[0].InputImages) != 2 || f.requests[0].ImageReferences[1].Role != "environment" || !strings.Contains(f.requests[0].IdempotencyKey, run.ID) {
		t.Fatal(run.Status, f.requests)
	}
}

func TestAutomaticCreationCharacterSceneShotVideoChain(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	doc, _ := projectDocument(row)
	p := shotPlanFixture()
	p.Nodes[0].Count = 1
	p.Nodes[0].AspectRatio = "16:9"
	p.Nodes[0].DurationSeconds = 5
	character, err := h.saveAsset("alice", "rabbit.png", creationPNG, "image/png", "upload", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	p.Nodes[2].References[0].AssetID = character.ID
	p.Nodes[3].References = append([]bridge.CreativeReference{{AssetID: character.ID, Role: "identity"}}, p.Nodes[3].References...)
	doc.Plan = p
	doc.AssetIDs = []string{character.ID}
	doc.States = map[string]creativeNodeState{}
	for _, n := range p.Nodes {
		doc.States[n.ID] = creativeNodeState{Revision: 1}
	}
	if err = h.updateProject(&row, doc, false); err != nil {
		t.Fatal(err)
	}
	row = reviewTestNode(t, r, h, token, row.ID, "script", "")
	before, _ := projectDocument(row)
	f.imageContent = func(req bridge.CreationNodeRequest) string {
		pixel := image.NewRGBA(image.Rect(0, 0, 1, 1))
		c := color.RGBA{G: 100, A: 255}
		if req.ImagePurpose == "shot_reference" {
			c = color.RGBA{R: 160, A: 255}
		}
		pixel.Set(0, 0, c)
		var out bytes.Buffer
		if err := png.Encode(&out, pixel); err != nil {
			t.Fatal(err)
		}
		return base64.StdEncoding.EncodeToString(out.Bytes())
	}
	startAutomatic(t, r, h, token, row.ID, "shot-chain")
	row = waitAutomatic(t, h, row.ID)
	after, _ := projectDocument(row)
	if row.AutomaticStatus != "completed" || len(f.requests) != 3 {
		t.Fatal(row.AutomaticStatus, after.Automation.Steps, len(f.requests))
	}
	if f.requests[0].ImagePurpose != "scene" || len(f.requests[0].InputImages) != 0 {
		t.Fatal("scene was polluted")
	}
	shot, video := f.requests[1], f.requests[2]
	if shot.ImagePurpose != "shot_reference" || len(shot.InputImages) != 2 || shot.ImageReferences[0].Role != "identity" || shot.ImageReferences[1].Role != "environment" {
		t.Fatal("shot responsibilities lost")
	}
	if video.Kind != "video" || video.VideoMode != "reference_to_video" || len(video.InputImages) != 3 || video.InputImages[0] != shot.InputImages[0] || video.InputImages[1] != shot.InputImages[1] || video.InputImages[2] == video.InputImages[1] {
		t.Fatal("three image kinds not passed separately")
	}
	if !reflect.DeepEqual(before.States["script"], after.States["script"]) {
		t.Fatal("user approval overwritten")
	}
	startAutomatic(t, r, h, token, row.ID, "shot-chain-again")
	waitAutomatic(t, h, row.ID)
	if len(f.requests) != 3 {
		t.Fatal("completed media regenerated")
	}
}
