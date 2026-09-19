package handlers

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"image"
	"image/color"
	"image/png"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
)

func libraryUpload(t *testing.T, r *gin.Engine, token, project, name string) models.CreationAsset {
	t.Helper()
	resp := creationRequest(t, r, token, "POST", "/api/creation/assets", map[string]string{"project_id": project, "name": name, "content": creationPNG, "mime_type": "image/png"})
	if resp.Code != 201 {
		t.Fatal(resp.Code, resp.Body.String())
	}
	var result struct{ Asset models.CreationAsset }
	json.Unmarshal(resp.Body.Bytes(), &result)
	return result.Asset
}
func TestCreationLibraryFoldersOwnershipPaginationAndLegacy(t *testing.T) {
	r, h, _, token := setupCreation(t)
	p := createTestProject(t, r, token)
	other := createTestProject(t, r, token)
	a := libraryUpload(t, r, token, p.ID, "scene.png")
	libraryUpload(t, r, token, p.ID, "scene-two.png")
	b := libraryUpload(t, r, token, other.ID, "other.png")
	legacy, _ := h.saveAsset("alice", "old.png", creationPNG, "image/png", "generated", "legacy-run", "n", "")
	h.db.Create(&models.CreationRun{ID: "legacy-run", UserID: "alice", ProjectID: p.ID, Status: "completed"})
	p = readTestProject(t, h, p.ID)
	doc, _ := projectDocument(p)
	upload, _ := h.saveAsset("alice", "role.png", creationPNG, "image/png", "upload", "", "", "")
	doc.AssetIDs = []string{upload.ID}
	if err := h.updateProject(&p, doc, false); err != nil {
		t.Fatal(err)
	}
	response := creationRequest(t, r, token, "GET", "/api/creation/asset-folders", nil)
	if response.Code != 200 || strings.Contains(response.Body.String(), creationPNG) || strings.Contains(response.Body.String(), "document") {
		t.Fatal(response.Body.String())
	}
	for _, id := range []string{a.ID, legacy.ID, upload.ID} {
		var record models.CreationAsset
		h.db.First(&record, "id = ?", id)
		if record.ProjectID != p.ID {
			t.Fatalf("not assigned: %+v", record)
		}
		item, _ := h.assetItem("alice", id)
		if item.ParentID != projectFolderID("alice", p.ID) {
			t.Fatal("file not in project folder")
		}
	}
	response = creationRequest(t, r, token, "GET", "/api/creation/assets?project_id="+p.ID+"&limit=1&offset=1&q=scene", nil)
	var page struct {
		Assets []creationAssetView
		Total  int
	}
	json.Unmarshal(response.Body.Bytes(), &page)
	if response.Code != 200 || page.Total != 2 || len(page.Assets) != 1 || strings.Contains(response.Body.String(), creationPNG) || strings.Contains(response.Body.String(), b.ID) {
		t.Fatal(response.Body.String())
	}
	response = creationRequest(t, r, token, "GET", "/api/creation/assets?project_id=&limit=48", nil)
	var unassigned struct {
		Assets []creationAssetView
		Total  int
	}
	json.Unmarshal(response.Body.Bytes(), &unassigned)
	if response.Code != 200 || unassigned.Total != 0 || len(unassigned.Assets) != 0 {
		t.Fatal("unassigned folder leaked project assets", response.Body.String())
	}
	response = creationRequest(t, r, token, "GET", "/api/creation/assets?ids="+a.ID+","+b.ID, nil)
	json.Unmarshal(response.Body.Bytes(), &page)
	if len(page.Assets) != 2 {
		t.Fatal(response.Body.String())
	}
	bob, _ := createAccountSession("bob")
	for _, path := range []string{"/api/creation/assets?project_id=" + p.ID, "/api/creation/assets/" + a.ID + "/thumbnail"} {
		if response := creationRequest(t, r, bob, "GET", path, nil); response.Code != 404 {
			t.Fatal(response.Code)
		}
	}
	response = creationRequest(t, r, bob, "POST", "/api/creation/assets", map[string]string{"project_id": p.ID, "name": "no.png", "content": creationPNG, "mime_type": "image/png"})
	if response.Code != 400 {
		t.Fatal(response.Code)
	}
	// New generated assets inherit the run's owner without a migration/reload.
	generated, err := h.saveAsset("alice", "new.png", creationPNG, "image/png", "generated", "legacy-run", "n", "")
	if err != nil || generated.ProjectID != p.ID {
		t.Fatal(generated, err)
	}
}
func TestCreationLibraryRenameDeletePreservesAssetsAndBlocksActiveWork(t *testing.T) {
	r, h, _, token := setupCreation(t)
	p := createTestProject(t, r, token)
	a := libraryUpload(t, r, token, p.ID, "role.png")
	bob, _ := createAccountSession("bob")
	response := creationRequest(t, r, bob, "PATCH", "/api/creation/projects/"+p.ID, map[string]interface{}{"name": "stolen", "revision": p.Revision})
	if response.Code != 404 {
		t.Fatal(response.Code)
	}
	for _, name := range []string{" ", strings.Repeat("名", 101)} {
		response = creationRequest(t, r, token, "PATCH", "/api/creation/projects/"+p.ID, map[string]interface{}{"name": name, "revision": p.Revision})
		if response.Code != 400 {
			t.Fatal(response.Code)
		}
	}
	response = creationRequest(t, r, token, "PATCH", "/api/creation/projects/"+p.ID, map[string]interface{}{"name": " 我的菌菇奇旅 ", "revision": p.Revision})
	if response.Code != 200 {
		t.Fatal(response.Body.String())
	}
	p = readTestProject(t, h, p.ID)
	if p.Name != "我的菌菇奇旅" || !p.NameLocked {
		t.Fatal(p.Name, p.NameLocked)
	}
	var folder models.DriveItem
	h.db.First(&folder, "id = ?", projectFolderID("alice", p.ID))
	if folder.Name != p.Name {
		t.Fatal(folder.Name)
	}
	path := "/api/creation/projects/" + p.ID + "?revision=" + strconv.Itoa(p.Revision)
	h.db.Create(&models.CreationRun{ID: "busy", UserID: "alice", ProjectID: p.ID, Status: "running"})
	response = creationRequest(t, r, token, "DELETE", path, nil)
	if response.Code != 409 {
		t.Fatal(response.Code)
	}
	h.db.Model(&models.CreationRun{}).Where("id = ?", "busy").Update("status", "completed")
	response = creationRequest(t, r, token, "DELETE", path, nil)
	if response.Code != 200 {
		t.Fatal(response.Body.String())
	}
	item, err := h.assetItem("alice", a.ID)
	root, _ := h.assetFolder("alice")
	if err != nil || item.ParentID != root.ID || item.Content != creationPNG {
		t.Fatal("asset lost", err)
	}
	var saved models.CreationAsset
	h.db.First(&saved, "id = ?", a.ID)
	if saved.ProjectID != "" {
		t.Fatal("not unassigned")
	}
	if response = creationRequest(t, r, token, "GET", "/api/creation/projects/"+p.ID, nil); response.Code != 404 {
		t.Fatal(response.Code)
	}
	var count int64
	h.db.Model(&models.CreationRun{}).Where("project_id = ?", p.ID).Count(&count)
	if count != 0 {
		t.Fatal("history not removed")
	}
}
func TestCreationLibraryDeleteAtomicOwnershipReferencesAndCandidates(t *testing.T) {
	r, h, _, token := setupCreation(t)
	p := createTestProject(t, r, token)
	a := libraryUpload(t, r, token, p.ID, "unused.png")
	b := libraryUpload(t, r, token, p.ID, "chosen.png")
	foreign, _ := h.saveAsset("bob", "private.png", creationPNG, "image/png", "upload", "", "", "")
	remove := func(ids ...string) *httptest.ResponseRecorder {
		return creationRequest(t, r, token, "POST", "/api/creation/assets/delete", map[string]interface{}{"ids": ids})
	}
	for _, ids := range [][]string{{a.ID, foreign.ID}, {a.ID, "missing"}} {
		if response := remove(ids...); response.Code != 404 {
			t.Fatal(response.Code)
		}
		if _, err := h.assetItem("alice", a.ID); err != nil {
			t.Fatal("partial deletion")
		}
	}
	if response := remove(a.ID, a.ID); response.Code != 400 {
		t.Fatal(response.Code)
	}
	p = readTestProject(t, h, p.ID)
	doc, _ := projectDocument(p)
	doc.States["visual"] = creativeNodeState{Revision: 1, SelectedAssetID: b.ID, Candidates: []string{a.ID, b.ID}}
	if err := h.updateProject(&p, doc, false); err != nil {
		t.Fatal(err)
	}
	if response := remove(a.ID, b.ID); response.Code != 409 {
		t.Fatal(response.Code)
	}
	h.db.Model(&p).Update("planning", true)
	if response := remove(a.ID); response.Code != 409 {
		t.Fatal(response.Code)
	}
	h.db.Model(&p).Update("planning", false)
	h.db.Create(&models.CreationThumbnail{DriveItemID: a.DriveItemID, Content: []byte("preview")})
	if response := remove(a.ID); response.Code != 200 {
		t.Fatal(response.Code, response.Body.String())
	}
	if _, err := h.assetItem("alice", a.ID); err == nil {
		t.Fatal("file retained")
	}
	if _, err := h.assetItem("alice", b.ID); err != nil {
		t.Fatal("selected file lost")
	}
	current := readTestProject(t, h, p.ID)
	doc, _ = projectDocument(current)
	if len(doc.States["visual"].Candidates) != 1 || doc.States["visual"].Candidates[0] != b.ID {
		t.Fatal("candidate not removed")
	}
	var count int64
	h.db.Model(&models.CreationThumbnail{}).Where("drive_item_id = ?", a.DriveItemID).Count(&count)
	if count != 0 {
		t.Fatal("thumbnail not deleted")
	}
}
func TestCreationLibraryThumbnailSmallCachedAuthorizedAndInvalidated(t *testing.T) {
	r, h, _, token := setupCreation(t)
	source := image.NewRGBA(image.Rect(0, 0, 1200, 800))
	source.Set(10, 10, color.RGBA{R: 255, A: 255})
	var buf bytes.Buffer
	png.Encode(&buf, source)
	a, err := h.saveAsset("alice", "large.png", base64.StdEncoding.EncodeToString(buf.Bytes()), "image/png", "upload", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	path := "/api/creation/assets/" + a.ID + "/thumbnail"
	response := creationRequest(t, r, token, "GET", path, nil)
	if response.Code != 200 || response.Header().Get("Content-Type") != "image/jpeg" {
		t.Fatal(response.Code, response.Body.String())
	}
	config, _, err := image.DecodeConfig(bytes.NewReader(response.Body.Bytes()))
	if err != nil || config.Width != 384 || config.Height != 256 {
		t.Fatal(config, err)
	}
	etag := response.Header().Get("ETag")
	req := httptest.NewRequest("GET", path, nil)
	req.Header.Set("X-Account-Session", token)
	req.Header.Set("If-None-Match", etag)
	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, req)
	if rec.Code != 304 {
		t.Fatal(rec.Code)
	}
	bob, _ := createAccountSession("bob")
	req.Header.Set("X-Account-Session", bob)
	rec = httptest.NewRecorder()
	r.ServeHTTP(rec, req)
	if rec.Code != 404 {
		t.Fatal("cache leaked", rec.Code)
	}
	// Updating the underlying Drive file invalidates the cached preview.
	h.db.Model(&models.DriveItem{}).Where("id = ?", a.DriveItemID).Update("content", "invalid")
	response = creationRequest(t, r, token, "GET", path, nil)
	if response.Code != 422 || response.Header().Get("ETag") == etag {
		t.Fatal(response.Code, "stale preview")
	}
}

func TestCreationLibraryImportMovesExistingOwnershipWithoutCopying(t *testing.T) {
	r, h, _, token := setupCreation(t)
	p := createTestProject(t, r, token)
	q := createTestProject(t, r, token)
	a := libraryUpload(t, r, token, p.ID, "ref.png")
	resp := creationRequest(t, r, token, "POST", "/api/creation/assets/import", map[string]string{"drive_item_id": a.DriveItemID, "project_id": q.ID})
	if resp.Code != 200 {
		t.Fatal(resp.Code, resp.Body.String())
	}
	var result struct{ Asset models.CreationAsset }
	json.Unmarshal(resp.Body.Bytes(), &result)
	if result.Asset.ID != a.ID || result.Asset.ProjectID != q.ID {
		t.Fatal(result.Asset)
	}
	file, err := h.assetItem("alice", a.ID)
	if err != nil || file.ParentID != projectFolderID("alice", q.ID) || file.Content != creationPNG {
		t.Fatal("import failed", err)
	}
	var n int64
	h.db.Model(&models.CreationAsset{}).Count(&n)
	if n != 1 {
		t.Fatal("duplicated file")
	}
}
func TestCreationLibraryManualNameSurvivesPlanning(t *testing.T) {
	r, h, _, token := setupCreation(t)
	p := createTestProject(t, r, token)
	resp := creationRequest(t, r, token, "PATCH", "/api/creation/projects/"+p.ID, map[string]interface{}{"name": "手动名称", "revision": p.Revision})
	if resp.Code != 200 {
		t.Fatal(resp.Body.String())
	}
	p = readTestProject(t, h, p.ID)
	p.Planning = true
	p.PlanningRequestID = "rename-plan"
	h.db.Save(&p)
	plan := creativeTestPlan()
	planner := &fakeCreativePlanner{response: &bridge.CreationPlanningResponse{Plan: plan, Reply: "ready"}}
	h.planProject(planner, p, bridge.CreationPlanningRequest{})
	current := readTestProject(t, h, p.ID)
	if current.Name != "手动名称" || current.Planning || current.Error != "" {
		t.Fatal(current.Name, current.Planning, current.Error)
	}
}
