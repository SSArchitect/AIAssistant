package handlers

import (
	"encoding/json"
	"testing"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/models"
)

func TestCreativeLayoutPersistsSeparatelyFromContentAndApprovals(t *testing.T) {
	r, h, _, token := setupCreation(t)
	row := seedCreativePlan(t, h, createTestProject(t, r, token))
	row = reviewTestNode(t, r, h, token, row.ID, "brief", "")
	// Moving nodes while the director is working must not interfere with planning.
	h.db.Model(&row).Update("planning", true)
	path := "/api/creation/projects/" + row.ID + "/layout"
	for _, body := range []map[string]interface{}{
		{"positions": map[string]interface{}{"brief": map[string]float64{"x": 101.5, "y": 250}}},
		{"positions": map[string]interface{}{"script": map[string]float64{"x": 460, "y": 900}}},
	} {
		response := creationRequest(t, r, token, "PATCH", path, body)
		if response.Code != 200 {
			t.Fatal(response.Code, response.Body.String())
		}
	}
	updated := readTestProject(t, h, row.ID)
	if updated.Document != row.Document || updated.Revision != row.Revision || !updated.Planning {
		t.Fatal("layout modified content, reviews or planning")
	}
	var positions map[string]map[string]float64
	if err := json.Unmarshal([]byte(updated.CanvasLayout), &positions); err != nil {
		t.Fatal(err)
	}
	if positions["brief"]["x"] != 101.5 || positions["script"]["y"] != 900 || updated.LayoutRevision != 2 {
		t.Fatal(positions, updated.LayoutRevision)
	}
	var count int64
	h.db.Model(&models.CreationProjectVersion{}).Where("project_id = ?", row.ID).Count(&count)
	if count != 2 {
		t.Fatal("layout should not add creative history", count)
	}
	// Content updates must not overwrite independently saved layout.
	doc, _ := projectDocument(row)
	if err := h.updateProject(&row, doc, false); err != nil {
		t.Fatal(err)
	}
	if readTestProject(t, h, row.ID).CanvasLayout != updated.CanvasLayout {
		t.Fatal("content update lost positions")
	}
	response := creationRequest(t, r, token, "PATCH", path, map[string]interface{}{"reset": true})
	if response.Code != 200 || readTestProject(t, h, row.ID).CanvasLayout != "{}" {
		t.Fatal(response.Code, response.Body.String())
	}
}

func TestCreativeLayoutRejectsForeignProjectsAndInvalidCoordinates(t *testing.T) {
	r, h, _, token := setupCreation(t)
	row := seedCreativePlan(t, h, createTestProject(t, r, token))
	path := "/api/creation/projects/" + row.ID + "/layout"
	body := map[string]interface{}{"positions": map[string]interface{}{"brief": map[string]float64{"x": 1, "y": 2}}}
	bob, _ := createAccountSession("bob")
	if response := creationRequest(t, r, bob, "PATCH", path, body); response.Code != 404 {
		t.Fatal(response.Code)
	}
	if response := creationRequest(t, r, "", "PATCH", path, body); response.Code != 401 {
		t.Fatal(response.Code)
	}
	for _, value := range []map[string]interface{}{
		{}, {"positions": map[string]interface{}{"unknown": map[string]int{"x": 1, "y": 2}}},
		{"positions": map[string]interface{}{"brief": map[string]int{"x": -1, "y": 2}}},
		{"positions": map[string]interface{}{"brief": map[string]int{"x": 20001, "y": 2}}},
		{"positions": map[string]interface{}{"brief": map[string]int{"x": 1}}},
		{"positions": map[string]interface{}{"brief": nil}},
	} {
		if response := creationRequest(t, r, token, "PATCH", path, value); response.Code != 400 {
			t.Fatal(response.Code, response.Body.String())
		}
	}
	if readTestProject(t, h, row.ID).LayoutRevision != 0 {
		t.Fatal("invalid writes changed layout")
	}
}

func TestCreativeSuggestionRefreshDoesNotInvalidateApprovals(t *testing.T) {
	doc := applyCreativePlan(emptyCreativeDocument(), creativeTestPlan())
	for id, s := range doc.States {
		s.ApprovedRevision = s.Revision
		doc.States[id] = s
	}
	plan := creativeTestPlan()
	plan.Nodes[0].RevisionSuggestions = []bridge.CreativeRevisionSuggestion{{Label: "强化动机", Instruction: "让人物动机更清楚"}}
	updated := applyCreativePlan(doc, plan)
	for id, s := range updated.States {
		if !creativeApproved(s) || s.Revision != doc.States[id].Revision {
			t.Fatal("suggestion-only change invalidated", id)
		}
	}
	if len(updated.Plan.Nodes[0].RevisionSuggestions) != 1 {
		t.Fatal("lost suggestions")
	}
}
