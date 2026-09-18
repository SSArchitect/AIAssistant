package handlers

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"image"
	"image/color"
	"image/png"
	"reflect"
	"testing"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
)

func TestCreationScenesRequireEnvironmentInsteadOfCharacterOrStyle(t *testing.T) {
	for _, change := range []string{"valid", "character", "style", "template", "ratio", "shared", "locked"} {
		t.Run(change, func(t *testing.T) {
			p := creativeTestPlan()
			locked := []string{}
			switch change {
			case "character":
				p.Nodes[1].Purpose = "shot_reference"
			case "style":
				p.Nodes[3].References[0].Role = "style"
			case "template":
				p.Nodes[1].CharacterStyle = "chibi"
			case "ratio":
				p.Nodes[1].AspectRatio = "9:16"
			case "shared":
				n := p.Nodes[3]
				n.ID = "second-video"
				p.Nodes = append(p.Nodes, n)
			case "locked":
				p.Nodes[1].Purpose = "key_visual"
				locked = []string{"video"}
			}
			err := validateVideoScenes(p, locked)
			if (err == nil) != (change == "valid" || change == "locked") {
				t.Fatalf("unexpected scene validation: %v", err)
			}
		})
	}
}

func TestScenePreflightPreservesConfirmedStoryboardAcrossJSONEncoding(t *testing.T) {
	doc := applyCreativePlan(emptyCreativeDocument(), creativeTestPlan())
	doc.Automation = &creativeAutomation{LockedNodeIDs: []string{"video"}}
	doc.Plan.Nodes[3].Storyboard = json.RawMessage(`{"style":"\u003cPicture 1\u003e"}`)
	p := copyAutomaticPlan(doc.Plan)
	p.Nodes[3].Storyboard = json.RawMessage(`{ "style": "<Picture 1>" }`)
	if err := protectAutomaticPlan(doc, p); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(p.Nodes[3], doc.Plan.Nodes[3]) {
		t.Fatal("confirmed storyboard bytes changed")
	}
	p.Nodes[3].Storyboard = json.RawMessage(`{"style":"different scene"}`)
	if err := protectAutomaticPlan(doc, p); err == nil {
		t.Fatal("real confirmed edit accepted")
	}
}

func TestAutomaticAddsMissingScenesBeforeAnyGenerationAndPreservesConfirmedNodes(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	f.imageContent = func(req bridge.CreationNodeRequest) string {
		if req.ImagePurpose != "scene" {
			return creationPNG
		}
		picture := image.NewRGBA(image.Rect(0, 0, 1, 1))
		picture.Set(0, 0, color.RGBA{R: 180, G: 80, B: 20, A: 255})
		var out bytes.Buffer
		if err := png.Encode(&out, picture); err != nil {
			t.Fatal(err)
		}
		return base64.StdEncoding.EncodeToString(out.Bytes())
	}
	doc, _ := projectDocument(row)
	doc.Plan.Nodes[1].Purpose = "key_visual"
	if err := h.updateProject(&row, doc, false); err != nil {
		t.Fatal(err)
	}
	row = reviewTestNode(t, r, h, token, row.ID, "brief", "")
	before, _ := projectDocument(row)
	planned := 0
	f.planHook = func(_ context.Context, req bridge.CreationPlanningRequest) (*bridge.CreationPlanningResponse, error) {
		planned++
		if !req.RequireVideoScenes || req.Repair != nil || len(f.requests) != 0 {
			t.Fatal("scene preflight was skipped")
		}
		p := copyAutomaticPlan(req.CurrentPlan)
		scene := p.Nodes[1]
		scene.ID = "video_scene"
		scene.Title = "竹林场景"
		scene.Purpose = "scene"
		scene.Count = 1
		video := p.Nodes[3]
		video.DependsOn = append(video.DependsOn, scene.ID)
		video.References = append(video.References, bridge.CreativeReference{NodeID: scene.ID, Role: "reference", Note: "本段竹林环境"})
		p.Nodes = append(p.Nodes[:3], scene, video)
		return &bridge.CreationPlanningResponse{Plan: p, Reply: "已补充场景"}, nil
	}
	startAutomatic(t, r, h, token, row.ID, "prepare-scenes")
	row = waitAutomatic(t, h, row.ID)
	after, _ := projectDocument(row)
	if planned != 1 || row.AutomaticStatus != "completed" || len(f.requests) != 4 {
		t.Fatal("scene not generated before video", planned, row.AutomaticStatus, after.Automation.Steps)
	}
	if f.requests[2].ImagePurpose != "scene" || f.requests[3].Kind != "video" || len(f.requests[3].InputImages) != 2 {
		t.Fatal("video did not receive generated scene", f.requests)
	}
	if !reflect.DeepEqual(before.States["brief"], after.States["brief"]) {
		t.Fatal("confirmed brief changed")
	}
}

func TestAutomaticRejectsSceneLessPlanBeforeGeneration(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	doc, _ := projectDocument(row)
	doc.Plan.Nodes[1].Purpose = "key_visual"
	if err := h.updateProject(&row, doc, false); err != nil {
		t.Fatal(err)
	}
	f.planHook = func(_ context.Context, req bridge.CreationPlanningRequest) (*bridge.CreationPlanningResponse, error) {
		return &bridge.CreationPlanningResponse{Plan: req.CurrentPlan}, nil
	}
	startAutomatic(t, r, h, token, row.ID, "missing-scene")
	row = waitAutomatic(t, h, row.ID)
	if row.AutomaticStatus != "failed" || len(f.requests) != 0 {
		t.Fatal("unprepared video executed")
	}
}
