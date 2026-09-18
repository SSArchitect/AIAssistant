package handlers

import (
	"errors"
	"fmt"
	"reflect"
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
)

func TestCreativePreferencesPersistAcrossPlanningFailureAndLegacyClients(t *testing.T) {
	r, h, _, token := setupCreation(t)
	row := seedCreativePlan(t, h, createTestProject(t, r, token))
	original, _ := projectDocument(row)
	fake := &fakeCreativePlanner{err: errors.New("provider unavailable"), called: make(chan bridge.CreationPlanningRequest, 3)}
	h.generator = fake
	chosen := &bridge.CreativePreferences{OutputKind: "video", AspectRatio: "9:16"}
	for i, input := range []*bridge.CreativePreferences{chosen, nil, {}} {
		body := map[string]interface{}{"revision": row.Revision, "message": "调整创作方案", "request_id": fmt.Sprintf("preferences-%d", i)}
		if input != nil {
			body["preferences"] = input
		}
		response := creationRequest(t, r, token, "POST", "/api/creation/projects/"+row.ID+"/messages", body)
		if response.Code != 202 {
			t.Fatal(response.Code, response.Body.String())
		}
		var req bridge.CreationPlanningRequest
		select {
		case req = <-fake.called:
		case <-time.After(3 * time.Second):
			t.Fatal("planner not called")
		}
		want := chosen
		if i == 2 {
			want = &bridge.CreativePreferences{}
		}
		if !reflect.DeepEqual(req.Preferences, want) || !reflect.DeepEqual(req.Messages[len(req.Messages)-1].Preferences, want) {
			t.Fatalf("planner lost preferences: %+v", req.Preferences)
		}
		deadline := time.Now().Add(3 * time.Second)
		for time.Now().Before(deadline) {
			row = readTestProject(t, h, row.ID)
			if !row.Planning {
				break
			}
			time.Sleep(time.Millisecond)
		}
		if row.Planning || row.Error == "" {
			t.Fatal("expected completed planning failure")
		}
		doc, _ := projectDocument(row)
		if !reflect.DeepEqual(doc.Preferences, want) || !reflect.DeepEqual(doc.Plan, original.Plan) || !reflect.DeepEqual(doc.States, original.States) {
			t.Fatal("failure lost preferences or changed existing canvas")
		}
		if i > 0 && !reflect.DeepEqual(doc.Messages[0].Preferences, chosen) {
			t.Fatal("historical preference snapshot was overwritten")
		}
	}
	other, _ := projectDocument(createTestProject(t, r, token))
	if other.Preferences != nil {
		t.Fatal("preferences leaked into a new project")
	}
}

func TestCreativePreferencesRejectInvalidValuesWithoutMutatingProject(t *testing.T) {
	r, h, _, token := setupCreation(t)
	row := createTestProject(t, r, token)
	for _, preferences := range []interface{}{
		map[string]string{"output_kind": "audio"}, map[string]string{"aspect_ratio": "4:3"}, map[string]interface{}{"output_kind": 1},
	} {
		response := creationRequest(t, r, token, "POST", "/api/creation/projects/"+row.ID+"/messages", map[string]interface{}{
			"revision": row.Revision, "message": "测试", "request_id": "invalid", "preferences": preferences,
		})
		if response.Code != 400 {
			t.Fatal(response.Code, response.Body.String())
		}
	}
	current := readTestProject(t, h, row.ID)
	if current.Revision != row.Revision || current.Document != row.Document || current.Planning {
		t.Fatal("invalid preferences changed project")
	}
}

func TestAutomaticCreationReceivesSavedPreferencesAndPreservesLocks(t *testing.T) {
	r, h, _, token := setupCreation(t)
	row := seedCreativePlan(t, h, createTestProject(t, r, token))
	doc, _ := projectDocument(row)
	doc.Preferences = &bridge.CreativePreferences{OutputKind: "image", AspectRatio: "1:1"}
	doc.Automation = &creativeAutomation{LockedNodeIDs: []string{"brief"}}
	for _, node := range []bridge.CreativeNode{{}, doc.Plan.Nodes[0]} {
		req, err := h.automaticRequest(row, doc, node, nil)
		if err != nil || !reflect.DeepEqual(req.Preferences, doc.Preferences) || !reflect.DeepEqual(req.LockedNodeIDs, []string{"brief"}) {
			t.Fatalf("automatic planning/review lost preferences or locks: %+v %v", req, err)
		}
	}
}
