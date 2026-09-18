package handlers

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/models"
)

type timeoutCreationGenerator struct {
	fakeCreationGenerator
	t *testing.T
}

func (f *timeoutCreationGenerator) CreateMedia(ctx context.Context, req bridge.CreationNodeRequest) (*bridge.CreationNodeResponse, error) {
	deadline, ok := ctx.Deadline()
	if !ok || time.Until(deadline) < 6*time.Hour {
		f.t.Error("worker would cut off the accepted-task budget")
	}
	if len(f.requests) == 0 {
		f.requests = append(f.requests, req)
		return nil, &bridge.CreationMediaError{Code: "media_wait_timeout", Message: "等待生成结果超时，继续原任务", ProviderTaskID: "original-task", Retryable: true}
	}
	return f.fakeCreationGenerator.CreateMedia(ctx, req)
}

func TestCreationVideoRetryKeepsOriginalTaskAndRejectsChangedSnapshot(t *testing.T) {
	for _, scenario := range []string{"resume", "changed", "terminal", "interrupted"} {
		t.Run(scenario, func(t *testing.T) {
			r, h, _, token := setupCreation(t)
			f := &timeoutCreationGenerator{t: t}
			h.generator = f
			row := seedCreativePlan(t, h, createTestProject(t, r, token))
			asset, err := h.saveAsset("alice", "scene.png", creationPNG, "image/png", "upload", "", "", "")
			if err != nil {
				t.Fatal(err)
			}
			doc, _ := projectDocument(row)
			doc.Plan.Nodes[1].AssetID = asset.ID
			doc.Plan.Nodes[1].Count = 1
			doc.States["visual"] = creativeNodeState{Revision: 2, SelectedAssetID: asset.ID}
			if err = h.updateProject(&row, doc, false); err != nil {
				t.Fatal(err)
			}
			for _, id := range []string{"brief", "visual", "script", "video"} {
				selected := ""
				if id == "visual" {
					selected = asset.ID
				}
				row = reviewTestNode(t, r, h, token, row.ID, id, selected)
			}
			generate := func(key string) models.CreationRun {
				current := readTestProject(t, h, row.ID)
				response := creationRequest(t, r, token, "POST", "/api/creation/projects/"+row.ID+"/generate", map[string]interface{}{"revision": current.Revision, "node_id": "video", "request_id": key})
				if response.Code != 202 {
					t.Fatal(response.Code, response.Body.String())
				}
				var body struct {
					Run models.CreationRun `json:"run"`
				}
				json.Unmarshal(response.Body.Bytes(), &body)
				return waitCreativeRun(t, h, body.Run.ID)
			}
			first := generate("first")
			if first.Status != "failed" || !strings.Contains(first.Error, "短片") || !strings.Contains(first.Error, "超时") {
				t.Fatal(first.Status, first.Error)
			}
			var progress []creationProgress
			json.Unmarshal([]byte(first.Progress), &progress)
			if !progress[0].Retryable || progress[0].ProviderTaskID != "original-task" {
				t.Fatal("resume metadata lost", progress)
			}
			switch scenario {
			case "changed":
				var graph creationGraph
				json.Unmarshal([]byte(first.Definition), &graph)
				graph.Nodes[0].Prompt = "different frozen film"
				h.db.Model(&first).Update("definition", creationJSON(graph))
			case "terminal":
				progress[0].Retryable = false
				h.db.Model(&first).Update("progress", creationJSON(progress))
			case "interrupted":
				h.db.Model(&first).Update("status", "interrupted")
			}
			second := generate("retry")
			same := scenario == "resume" || scenario == "interrupted"
			if second.Status != "completed" || (second.ID == first.ID) != same || (f.requests[0].IdempotencyKey == f.requests[1].IdempotencyKey) != same {
				t.Fatal("incorrect replay", scenario, first.ID, second.ID, f.requests)
			}
			if same && second.Snapshot != first.Snapshot {
				t.Fatal("original input snapshot changed")
			}
			current := readTestProject(t, h, row.ID)
			doc, _ = projectDocument(current)
			if len(doc.States["video"].Candidates) != 1 {
				t.Fatal("result not attached exactly once")
			}
		})
	}
}
