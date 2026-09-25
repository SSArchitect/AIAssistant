package handlers

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
)

const creationPNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aH9sAAAAASUVORK5CYII="

type fakeCreationGenerator struct {
	requests     []bridge.CreationNodeRequest
	failAt       int
	hook         func()
	imageContent func(bridge.CreationNodeRequest) string
}

func (f *fakeCreationGenerator) CreateMedia(_ context.Context, req bridge.CreationNodeRequest) (*bridge.CreationNodeResponse, error) {
	f.requests = append(f.requests, req)
	if f.hook != nil {
		f.hook()
	}
	if f.failAt > 0 && len(f.requests) == f.failAt {
		return nil, errors.New("provider failed SECRET")
	}
	content := creationPNG
	mime := "image/png"
	if req.Kind == "image" && f.imageContent != nil {
		content = f.imageContent(req)
	}
	if req.Kind == "video" {
		content = base64.StdEncoding.EncodeToString([]byte{0, 0, 0, 24, 'f', 't', 'y', 'p', 'i', 's', 'o', 'm', 0, 0, 0, 0, 'i', 's', 'o', 'm', 'm', 'p', '4', '2'})
		mime = "video/mp4"
	}
	return &bridge.CreationNodeResponse{Content: content, MimeType: mime, ProviderTaskID: "provider"}, nil
}
func creationTestNode(id, kind string) creationNode {
	return creationNode{ID: id, Kind: kind, Name: id, Prompt: "test", Count: 1, AspectRatio: "16:9", DurationSeconds: 5, Inputs: []string{}, AssetIDs: []string{}}
}
func setupCreation(t *testing.T) (*gin.Engine, *CreationHandler, *fakeCreationGenerator, string) {
	t.Helper()
	setupDriveTest(t)
	f := &fakeCreationGenerator{}
	h := NewCreationHandler(f)
	// Unit tests use a virtual backoff; individual cancellation/delay tests
	// override this hook rather than spending wall time between fake responses.
	h.retryWait = func(ctx context.Context, _ time.Duration) error { return ctx.Err() }
	r := gin.New()
	h.Register(r.Group("/api"))
	token, err := createAccountSession("alice")
	if err != nil {
		t.Fatal(err)
	}
	return r, h, f, token
}
func creationRequest(t *testing.T, r *gin.Engine, token, method, path string, body interface{}) *httptest.ResponseRecorder {
	t.Helper()
	data, _ := json.Marshal(body)
	req := httptest.NewRequest(method, path, bytes.NewReader(data))
	req.Header.Set("Content-Type", "application/json")
	if token != "" {
		req.Header.Set("X-Account-Session", token)
	}
	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, req)
	return rec
}
func definitionBody(kind string, graph creationGraph) map[string]interface{} {
	return map[string]interface{}{"name": "test", "kind": kind, "graph": graph}
}
func TestCreationGraphValidatesReferencesAndCounts(t *testing.T) {
	a, b := creationTestNode("a", "image"), creationTestNode("b", "video")
	a.Count = 3
	b.Inputs = []string{"a"}
	if err := validateCreationGraph(creationGraph{[]creationNode{a, b}}, true); err != nil {
		t.Fatal(err)
	}
	cases := []struct {
		name  string
		nodes []creationNode
	}{
		{"empty", nil}, {"forward", []creationNode{b, a}}, {"duplicate", []creationNode{a, a}},
		{"too many image inputs", []creationNode{a, func() creationNode { n := b; n.Kind = "image"; n.AssetIDs = []string{"extra"}; return n }()}},
		{"blank prompt", []creationNode{func() creationNode { n := a; n.Prompt = " "; return n }()}},
		{"bad count", []creationNode{func() creationNode { n := a; n.Count = 10; return n }()}},
		{"video as input", []creationNode{creationTestNode("a", "video"), b}},
		{"missing style input", []creationNode{func() creationNode { n := a; n.CharacterStyle = "anime"; return n }()}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if validateCreationGraph(creationGraph{tc.nodes}, true) == nil {
				t.Fatal("expected failure")
			}
		})
	}
}
func TestCreationDefinitionsRequireSessionScopeAndCopyTemplates(t *testing.T) {
	r, _, _, token := setupCreation(t)
	graph := creationGraph{[]creationNode{creationTestNode("a", "image")}}
	if response := creationRequest(t, r, "", "GET", "/api/creation/definitions?user_id=alice", nil); response.Code != 401 {
		t.Fatal(response.Code)
	}
	response := creationRequest(t, r, token, "POST", "/api/creation/definitions?user_id=bob", definitionBody("workflow", graph))
	if response.Code != 200 {
		t.Fatal(response.Body.String())
	}
	var saved struct {
		Definition models.CreationDefinition `json:"definition"`
	}
	json.Unmarshal(response.Body.Bytes(), &saved)
	var stored models.CreationDefinition
	database.DB.First(&stored, "id = ?", saved.Definition.ID)
	if stored.UserID != "alice" {
		t.Fatal(stored.UserID)
	}
	response = creationRequest(t, r, token, "PUT", "/api/creation/definitions/"+stored.ID, definitionBody("workflow", graph))
	if response.Code != 200 {
		t.Fatal("owner update failed", response.Body.String())
	}
	bob, _ := createAccountSession("bob")
	for _, method := range []string{"PUT", "DELETE"} {
		response = creationRequest(t, r, bob, method, "/api/creation/definitions/"+stored.ID, definitionBody("workflow", graph))
		if response.Code != 404 {
			t.Fatal(response.Code)
		}
	}
	response = creationRequest(t, r, bob, "POST", "/api/creation/runs", map[string]string{"workflow_id": stored.ID})
	if response.Code != 404 {
		t.Fatal(response.Code)
	}
	graph.Nodes[0].AssetIDs = []string{"private-source"}
	response = creationRequest(t, r, token, "POST", "/api/creation/definitions", definitionBody("workflow_template", graph))
	if response.Code != 200 || strings.Contains(response.Body.String(), "private-source") {
		t.Fatal(response.Body.String())
	}
	response = creationRequest(t, r, token, "POST", "/api/creation/definitions", definitionBody("video_template", graph))
	if response.Code != 400 {
		t.Fatal(response.Code)
	}
}
func TestCreationAssetsPersistInDriveAndRespectOwnership(t *testing.T) {
	r, h, _, token := setupCreation(t)
	response := creationRequest(t, r, token, "POST", "/api/creation/assets", map[string]string{"name": "photo.png", "mime_type": "image/png", "content": creationPNG})
	if response.Code != 201 {
		t.Fatal(response.Body.String())
	}
	var saved struct {
		Asset models.CreationAsset `json:"asset"`
	}
	json.Unmarshal(response.Body.Bytes(), &saved)
	item, err := h.assetItem("alice", saved.Asset.ID)
	if err != nil || item.Encoding != "base64" || item.Content != creationPNG {
		t.Fatalf("%+v %v", item, err)
	}
	folder, err := h.assetFolder("alice")
	if err != nil || item.ParentID != folder.ID || folder.Name != "资产" {
		t.Fatal("wrong folder")
	}
	response = creationRequest(t, r, token, "GET", "/api/creation/assets", nil)
	if response.Code != 200 || !strings.Contains(response.Body.String(), "photo.png") || strings.Contains(response.Body.String(), creationPNG) {
		t.Fatal(response.Body.String())
	}
	bob, _ := createAccountSession("bob")
	if response = creationRequest(t, r, bob, "GET", "/api/creation/assets/"+saved.Asset.ID+"/content", nil); response.Code != 404 {
		t.Fatal(response.Code)
	}
	req := httptest.NewRequest("GET", "/api/creation/assets/"+saved.Asset.ID+"/content?account_session="+token, nil)
	req.Header.Set("Range", "bytes=0-7")
	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, req)
	if rec.Code != 206 || rec.Body.Len() != 8 {
		t.Fatalf("range failed: %d %s", rec.Code, rec.Body.String())
	}
	for _, body := range []map[string]string{{"mime_type": "video/mp4", "content": creationPNG}, {"mime_type": "image/png", "content": "bad"}, {"mime_type": "image/svg+xml", "content": base64.StdEncoding.EncodeToString([]byte("<svg/>"))}} {
		if response = creationRequest(t, r, token, "POST", "/api/creation/assets", body); response.Code != 400 {
			t.Fatal(response.Code)
		}
	}
	database.DB.Delete(&models.DriveItem{}, "id = ?", item.ID)
	response = creationRequest(t, r, token, "GET", "/api/creation/assets", nil)
	if strings.Contains(response.Body.String(), "photo.png") {
		t.Fatal("deleted file remains")
	}
}
func TestCreationImportsExistingDriveMediaWithoutCopyingBytes(t *testing.T) {
	r, h, _, token := setupCreation(t)
	item := models.DriveItem{ID: "existing", UserID: "alice", Type: "file", Name: "existing.png", MimeType: "image/png", Encoding: "base64", Content: creationPNG}
	if err := database.DB.Create(&item).Error; err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 2; i++ {
		response := creationRequest(t, r, token, "POST", "/api/creation/assets/import", map[string]string{"drive_item_id": item.ID})
		if response.Code != 200 {
			t.Fatal(response.Body.String())
		}
	}
	var count int64
	database.DB.Model(&models.CreationAsset{}).Count(&count)
	if count != 1 {
		t.Fatal(count)
	}
	database.DB.First(&item, "id = ?", item.ID)
	folder, _ := h.assetFolder("alice")
	if item.ParentID != folder.ID {
		t.Fatal("not moved")
	}
	bob, _ := createAccountSession("bob")
	if response := creationRequest(t, r, bob, "POST", "/api/creation/assets/import", map[string]string{"drive_item_id": item.ID}); response.Code != 404 {
		t.Fatal(response.Code)
	}
	nested := models.DriveItem{ID: "nested", UserID: "alice", ParentID: folder.ID, Type: "folder", Name: "nested"}
	database.DB.Create(&nested)
	another := item
	another.ID = "in-folder"
	another.ParentID = nested.ID
	database.DB.Create(&another)
	response := creationRequest(t, r, token, "GET", "/api/creation/assets", nil)
	if response.Code != 200 {
		t.Fatal(response.Body.String())
	}
	database.DB.Model(&models.CreationAsset{}).Count(&count)
	if count != 2 {
		t.Fatal("nested media not indexed", count)
	}
}
func executeCreationTest(t *testing.T, h *CreationHandler, graph creationGraph) models.CreationRun {
	t.Helper()
	progress := make([]creationProgress, len(graph.Nodes))
	for i, n := range graph.Nodes {
		progress[i] = creationProgress{NodeID: n.ID, Status: "pending", AssetIDs: []string{}}
	}
	run := models.CreationRun{ID: fmt.Sprintf("run-%s", t.Name()), UserID: "alice", Name: "test", Status: "queued", Definition: creationJSON(graph), Progress: creationJSON(progress)}
	if err := database.DB.Create(&run).Error; err != nil {
		t.Fatal(err)
	}
	h.execute(run, graph, progress)
	database.DB.First(&run, "id = ?", run.ID)
	return run
}
func TestCreationRunsManyImagesIntoVideoAndImageIntoImage(t *testing.T) {
	_, h, f, _ := setupCreation(t)
	a, b := creationTestNode("a", "image"), creationTestNode("b", "video")
	a.Count = 3
	b.Inputs = []string{"a"}
	run := executeCreationTest(t, h, creationGraph{[]creationNode{a, b}})
	if run.Status != "completed" || len(f.requests) != 4 || len(f.requests[3].InputImages) != 3 {
		t.Fatalf("%+v requests=%+v", run, f.requests)
	}
	if f.requests[0].IdempotencyKey == f.requests[1].IdempotencyKey {
		t.Fatal("reused key")
	}
	var assets []models.CreationAsset
	database.DB.Where("run_id = ?", run.ID).Find(&assets)
	if len(assets) != 4 {
		t.Fatal(len(assets))
	}
	var progress []creationProgress
	json.Unmarshal([]byte(run.Progress), &progress)
	if len(progress[0].AssetIDs) != 3 || progress[1].Status != "completed" {
		t.Fatal(run.Progress)
	}
	t.Run("image-to-image", func(t *testing.T) {
		a.Count = 1
		b.Kind = "image"
		f.requests = nil
		run := executeCreationTest(t, h, creationGraph{[]creationNode{a, b}})
		if run.Status != "completed" || len(f.requests[1].InputImages) != 1 {
			t.Fatal(run.Status)
		}
	})
}
func TestCreationFailureStopsDownstreamAndKeepsPartialOutputs(t *testing.T) {
	_, h, f, _ := setupCreation(t)
	f.failAt = 2
	a, b := creationTestNode("a", "image"), creationTestNode("b", "video")
	a.Count = 3
	b.Inputs = []string{"a"}
	run := executeCreationTest(t, h, creationGraph{[]creationNode{a, b}})
	if run.Status != "failed" || len(f.requests) != 2 || strings.Contains(run.Error, "SECRET") {
		t.Fatal(run)
	}
	var progress []creationProgress
	json.Unmarshal([]byte(run.Progress), &progress)
	if len(progress[0].AssetIDs) != 1 || progress[0].Status != "failed" || progress[1].Status != "skipped" {
		t.Fatal(run.Progress)
	}
}
func TestCreationStopArchivesInflightOutputAndPreventsNextSubmission(t *testing.T) {
	_, h, f, _ := setupCreation(t)
	f.hook = func() {
		database.DB.Model(&models.CreationRun{}).Where("user_id = ?", "alice").Update("status", "stopping")
	}
	a := creationTestNode("a", "image")
	a.Count = 3
	run := executeCreationTest(t, h, creationGraph{[]creationNode{a}})
	if run.Status != "cancelled" || len(f.requests) != 1 {
		t.Fatal(run)
	}
	var assets int64
	database.DB.Model(&models.CreationAsset{}).Count(&assets)
	if assets != 1 {
		t.Fatal(assets)
	}
}
func TestCreationRunRejectsInvalidAssetsAndDuplicateActiveRuns(t *testing.T) {
	r, h, _, token := setupCreation(t)
	n := creationTestNode("a", "image")
	n.AssetIDs = []string{"foreign"}
	row := models.CreationDefinition{ID: "flow", UserID: "alice", Kind: "workflow", Name: "test", Definition: creationJSON(creationGraph{[]creationNode{n}})}
	database.DB.Create(&row)
	response := creationRequest(t, r, token, "POST", "/api/creation/runs", map[string]string{"workflow_id": "flow"})
	if response.Code != 400 {
		t.Fatal(response.Body.String())
	}
	n.AssetIDs = nil
	database.DB.Model(&row).Update("definition", creationJSON(creationGraph{[]creationNode{n}}))
	run := models.CreationRun{ID: "active", UserID: "alice", Status: "stopping"}
	database.DB.Create(&run)
	response = creationRequest(t, r, token, "POST", "/api/creation/runs", map[string]string{"workflow_id": "flow"})
	if response.Code != 409 {
		t.Fatal(response.Body.String())
	}
	if err := h.Recover(); err != nil {
		t.Fatal(err)
	}
	database.DB.First(&run, "id = ?", run.ID)
	if run.Status != "interrupted" {
		t.Fatal(run.Status)
	}
}
func TestCreationRunFailsIfDriveInputWasDeleted(t *testing.T) {
	_, h, f, _ := setupCreation(t)
	a := creationTestNode("a", "image")
	a.AssetIDs = []string{"gone"}
	run := executeCreationTest(t, h, creationGraph{[]creationNode{a}})
	if run.Status != "failed" || len(f.requests) != 0 {
		t.Fatal(run.Status)
	}
}
func TestCreationRunListIsAccountScoped(t *testing.T) {
	r, _, _, token := setupCreation(t)
	database.DB.Create(&models.CreationRun{ID: "a", UserID: "alice", Name: "Alice"})
	database.DB.Create(&models.CreationRun{ID: "b", UserID: "bob", Name: "Secret"})
	response := creationRequest(t, r, token, "GET", "/api/creation/runs?user_id=bob", nil)
	if response.Code != 200 || strings.Contains(response.Body.String(), "Secret") || !strings.Contains(response.Body.String(), "Alice") {
		t.Fatal(response.Body.String())
	}
}

func TestCreationStartRunFreezesDefinitionAndCompletesInBackground(t *testing.T) {
	r, h, f, token := setupCreation(t)
	entered, release := make(chan struct{}), make(chan struct{})
	f.hook = func() { close(entered); <-release }
	n := creationTestNode("a", "image")
	row := models.CreationDefinition{ID: "flow", UserID: "alice", Kind: "workflow", Name: "original", Definition: creationJSON(creationGraph{[]creationNode{n}})}
	database.DB.Create(&row)
	response := creationRequest(t, r, token, "POST", "/api/creation/runs", map[string]string{"workflow_id": "flow"})
	if response.Code != 202 {
		t.Fatal(response.Body.String())
	}
	<-entered
	duplicate := creationRequest(t, r, token, "POST", "/api/creation/runs", map[string]string{"workflow_id": "flow"})
	if duplicate.Code != 409 {
		t.Error(duplicate.Body.String())
	}
	database.DB.Model(&row).Update("name", "edited while running")
	close(release)
	var result struct {
		Run models.CreationRun `json:"run"`
	}
	json.Unmarshal(response.Body.Bytes(), &result)
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		var run models.CreationRun
		h.db.First(&run, "id = ?", result.Run.ID)
		if run.Status == "completed" {
			if run.Name != "original" {
				t.Fatal("run snapshot changed")
			}
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatal("background run did not complete")
}
