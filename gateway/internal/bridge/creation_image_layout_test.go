package bridge

import (
	"context"
	"encoding/json"
	"math"
	"net/http"
	"net/http/httptest"
	"reflect"
	"testing"
	"time"
)

func TestImageLayoutBoundaryAndForwarding(t *testing.T) {
	layout := []ImagePlacement{{CenterXPercent: 25.5, CenterYPercent: 82.6, SubjectHeightPercent: 10, SubjectPrompt: "rear rider", CompositeMode: "foreground_v1"}}
	refs := []ImageReferenceContext{{Role: "environment"}, {Role: "identity"}}
	if err := ValidateImageLayout(layout, "9:16", "image", "shot_reference", refs, "", false); err != nil {
		t.Fatal(err)
	}
	for _, change := range []func(*ImagePlacement){func(p *ImagePlacement) { p.CompositeMode = "unknown" }, func(p *ImagePlacement) { p.CenterXPercent = 0 }, func(p *ImagePlacement) { p.SubjectHeightPercent = math.NaN() }, func(p *ImagePlacement) { p.SubjectPrompt = " " }, func(p *ImagePlacement) { p.SubjectHeightPercent = 26 }} {
		bad := append([]ImagePlacement(nil), layout...)
		change(&bad[0])
		if ValidateImageLayout(bad, "9:16", "image", "shot_reference", refs, "", false) == nil {
			t.Fatal("invalid layout accepted")
		}
	}
	var got CreationNodeRequest
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if err := json.NewDecoder(r.Body).Decode(&got); err != nil {
			t.Error(err)
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"content":"aW1hZ2U=","mime_type":"image/png","provider_task_id":"original"}`))
	}))
	defer server.Close()
	client := NewAgentClient(server.URL, time.Second)
	_, err := client.CreateMedia(context.Background(), CreationNodeRequest{Kind: "image", ImageLayout: layout, ImageReferences: refs, ResumeTaskID: "original", IdempotencyKey: "original-key"})
	if err != nil || !reflect.DeepEqual(got.ImageLayout, layout) || got.ResumeTaskID != "original" {
		t.Fatal(got, err)
	}
}

func TestLegacyCreativeNodeLayoutRoundTripPreservesLockedEquality(t *testing.T) {
	var old, current CreativeNode
	if err := json.Unmarshal([]byte(`{"id":"locked","kind":"image"}`), &old); err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal([]byte(`{"id":"locked","kind":"image","image_layout":[]}`), &current); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(old, current) {
		t.Fatal("new empty field invalidates approved node")
	}
}
