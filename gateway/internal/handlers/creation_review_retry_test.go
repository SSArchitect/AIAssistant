package handlers

import (
	"context"
	"errors"
	"reflect"
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
)

type retryReviewDirector struct {
	*fakeAutomaticDirector
	failures int
	err      error
	attempts []bridge.CreationReviewRequest
}

func (f *retryReviewDirector) ReviewCreation(ctx context.Context, req bridge.CreationReviewRequest) (*bridge.CreationReviewResponse, error) {
	f.attempts = append(f.attempts, req)
	if req.NodeID == "visual" && f.failures > 0 {
		f.failures--
		return nil, f.err
	}
	return f.fakeAutomaticDirector.ReviewCreation(ctx, req)
}

func TestAutomaticReviewRetriesSameCandidatesWithoutGeneratingAgain(t *testing.T) {
	r, h, base, token, row := setupAutomatic(t)
	f := &retryReviewDirector{fakeAutomaticDirector: base, failures: 1, err: &bridge.CreationPlanningError{Code: "provider_unavailable", Message: "服务暂不可用"}}
	h.generator = f
	delays := []time.Duration{}
	h.retryWait = func(context.Context, time.Duration) error { delays = append(delays, 2*time.Second); return nil }
	startAutomatic(t, r, h, token, row.ID, "retry-review")
	row = waitAutomatic(t, h, row.ID)
	doc, _ := projectDocument(row)
	if row.AutomaticStatus != "completed" || len(base.requests) != 3 || len(delays) != 1 {
		t.Fatal(row.AutomaticStatus, len(base.requests), delays, doc.Automation.Steps)
	}
	reviews := []bridge.CreationReviewRequest{}
	for _, req := range f.attempts {
		if req.NodeID == "visual" {
			reviews = append(reviews, req)
		}
	}
	if len(reviews) != 2 || !reflect.DeepEqual(reviews[0], reviews[1]) {
		t.Fatal("retry changed candidates or approval context")
	}
	found := false
	for _, step := range doc.Automation.Steps {
		found = found || step.Stage == "review_retry"
	}
	if !found {
		t.Fatal("retry was invisible")
	}
}

func TestAutomaticReviewRetryLimitAndPermanentFailures(t *testing.T) {
	for _, tc := range []struct {
		code    string
		retries int
	}{
		{"planning_timeout", 2}, {"review_invalid_result", 2}, {"review_evidence_quote_mismatch", 2},
		{"provider_auth_failed", 0}, {"provider_rate_limited", 0}, {"plan_constraint_failed", 0}, {"unknown", 0},
	} {
		t.Run(tc.code, func(t *testing.T) {
			r, h, base, token, row := setupAutomatic(t)
			f := &retryReviewDirector{fakeAutomaticDirector: base, failures: 10, err: &bridge.CreationPlanningError{Code: tc.code, Message: "未完成"}}
			h.generator = f
			delays := []time.Duration{}
			h.retryWait = func(_ context.Context, d time.Duration) error { delays = append(delays, d); return nil }
			startAutomatic(t, r, h, token, row.ID, "bounded-review")
			row = waitAutomatic(t, h, row.ID)
			doc, _ := projectDocument(row)
			if row.AutomaticStatus != "failed" || len(delays) != tc.retries || len(base.requests) != 2 || creativeApproved(doc.States["visual"]) {
				t.Fatal(row.AutomaticStatus, delays, len(base.requests))
			}
			if tc.retries == 2 && !reflect.DeepEqual(delays, []time.Duration{2 * time.Second, 4 * time.Second}) {
				t.Fatal(delays)
			}
		})
	}
}

func TestAutomaticReviewStopDuringRetryKeepsCandidateAndDoesNotApprove(t *testing.T) {
	r, h, base, token, row := setupAutomatic(t)
	f := &retryReviewDirector{fakeAutomaticDirector: base, failures: 10, err: &bridge.CreationPlanningError{Code: "provider_unavailable", Message: "未完成"}}
	h.generator = f
	entered := make(chan struct{})
	h.retryWait = func(ctx context.Context, _ time.Duration) error { close(entered); <-ctx.Done(); return ctx.Err() }
	startAutomatic(t, r, h, token, row.ID, "stop-retry")
	<-entered
	resp := creationRequest(t, r, token, "POST", "/api/creation/projects/"+row.ID+"/automatic/stop", map[string]interface{}{})
	if resp.Code != 202 && resp.Code != 200 {
		t.Fatal(resp.Code)
	}
	row = waitAutomatic(t, h, row.ID)
	doc, _ := projectDocument(row)
	if row.AutomaticStatus != "cancelled" || len(base.requests) != 2 || len(doc.States["visual"].Candidates) != 2 || creativeApproved(doc.States["visual"]) {
		t.Fatal(row.AutomaticStatus, doc.States)
	}
}

func TestAutomaticReviewCancellationIsNeverRetryable(t *testing.T) {
	if retryableCreationReview(context.Canceled) || retryableCreationReview(errors.New("temporary secret")) {
		t.Fatal("unsafe retry")
	}
}

func TestAutomaticReviewRejectsRevisionChangeDuringBackoff(t *testing.T) {
	r, h, base, token, row := setupAutomatic(t)
	f := &retryReviewDirector{fakeAutomaticDirector: base, failures: 10, err: &bridge.CreationPlanningError{Code: "provider_unavailable", Message: "未完成"}}
	h.generator = f
	h.retryWait = func(context.Context, time.Duration) error {
		h.mu.Lock()
		defer h.mu.Unlock()
		current := readTestProject(t, h, row.ID)
		doc, _ := projectDocument(current)
		doc.Plan.Summary = "并发更新必须保留"
		return h.updateProject(&current, doc, true)
	}
	startAutomatic(t, r, h, token, row.ID, "revision-retry")
	row = waitAutomatic(t, h, row.ID)
	doc, _ := projectDocument(row)
	count := 0
	for _, req := range f.attempts {
		if req.NodeID == "visual" {
			count++
		}
	}
	if row.AutomaticStatus != "failed" || count != 1 || doc.Plan.Summary != "并发更新必须保留" || creativeApproved(doc.States["visual"]) {
		t.Fatal(row.AutomaticStatus, count, doc.States)
	}
}
