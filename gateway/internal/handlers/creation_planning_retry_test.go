package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
)

type retryTestPlanner struct {
	calls int
	call  func(context.Context, bridge.CreationPlanningRequest, int) (*bridge.CreationPlanningResponse, error)
}

type streamingRetryDirector struct {
	*fakeAutomaticDirector
	calls  int
	stream func(context.Context, bridge.CreationPlanningRequest, func(bridge.CreationPlanningProgress), int) (*bridge.CreationPlanningResponse, error)
}

func (p *streamingRetryDirector) PlanCreationWithProgress(ctx context.Context, req bridge.CreationPlanningRequest, report func(bridge.CreationPlanningProgress)) (*bridge.CreationPlanningResponse, error) {
	p.calls++
	return p.stream(ctx, req, report, p.calls)
}

func TestAutomaticStreamingPlanningProgressDoesNotInvalidateOwnResult(t *testing.T) {
	r, h, f, token, row := setupAutomatic(t)
	doc, _ := projectDocument(row)
	doc.Plan.Questions = []bridge.CreativeQuestion{{Question: "氛围", Options: []string{"温暖", "冷峻"}}}
	if err := h.updateProject(&row, doc, false); err != nil {
		t.Fatal(err)
	}
	p := &streamingRetryDirector{fakeAutomaticDirector: f, stream: func(_ context.Context, req bridge.CreationPlanningRequest, report func(bridge.CreationPlanningProgress), call int) (*bridge.CreationPlanningResponse, error) {
		report(bridge.CreationPlanningProgress{Stage: "oversized", Message: strings.Repeat("x", 301)})
		report(bridge.CreationPlanningProgress{Stage: "model", Message: "正在规划"})
		if call == 1 {
			return nil, io.ErrUnexpectedEOF
		}
		report(bridge.CreationPlanningProgress{Stage: "validate", Message: "正在校验"})
		plan := copyAutomaticPlan(req.CurrentPlan)
		plan.Questions = nil
		return &bridge.CreationPlanningResponse{Plan: plan, Reply: "完成"}, nil
	}}
	h.generator = p
	startAutomatic(t, r, h, token, row.ID, "streaming-retry")
	row = waitAutomatic(t, h, row.ID)
	doc, _ = projectDocument(row)
	if row.AutomaticStatus != "completed" || p.calls != 2 || len(f.requests) != 3 {
		t.Fatal(row.AutomaticStatus, p.calls, doc.Automation.Steps)
	}
	for _, step := range doc.Automation.Steps {
		if step.Stage == "oversized" {
			t.Fatal("oversized progress was persisted")
		}
	}
}

func TestPlanningTotalDeadlinePreventsFurtherCalls(t *testing.T) {
	h := &CreationHandler{retryWait: func(context.Context, time.Duration) error { t.Fatal("deadline was retried"); return nil }}
	ctx, cancel := context.WithTimeout(context.Background(), time.Millisecond)
	defer cancel()
	p := &retryTestPlanner{call: func(ctx context.Context, _ bridge.CreationPlanningRequest, _ int) (*bridge.CreationPlanningResponse, error) {
		<-ctx.Done()
		return nil, ctx.Err()
	}}
	_, err := h.planCreationWithRetry(ctx, p, bridge.CreationPlanningRequest{}, nil, nil, nil)
	if !errors.Is(err, context.DeadlineExceeded) || p.calls > 1 {
		t.Fatal(err, p.calls)
	}
}

func TestPlanningRetryPolicyPreservesInputsAndStopsAtFiveRetries(t *testing.T) {
	h := &CreationHandler{}
	waits := []time.Duration{}
	h.retryWait = func(_ context.Context, delay time.Duration) error { waits = append(waits, delay); return nil }
	request := bridge.CreationPlanningRequest{UserID: "alice", CurrentPlan: creativeTestPlan(), LockedNodeIDs: []string{"brief"},
		Messages: []bridge.CreativeMessage{{Role: "user", Content: "沿用已选方向"}}, Repair: &bridge.CreationRepairFeedback{NodeID: "visual", Attempt: 2}}
	before, _ := json.Marshal(request)
	var deadline time.Time
	var priorSeconds int
	planner := &retryTestPlanner{call: func(ctx context.Context, req bridge.CreationPlanningRequest, call int) (*bridge.CreationPlanningResponse, error) {
		currentDeadline, _ := ctx.Deadline()
		if call == 1 {
			deadline = currentDeadline
			if req.Recovery != nil {
				t.Error("unexpected recovery on first attempt")
			}
		} else {
			if currentDeadline != deadline || req.Recovery.Attempt != call-1 || req.Recovery.ErrorCode != "invalid_plan" || req.Recovery.MaxSeconds > 900 || req.Recovery.MaxSeconds <= 0 {
				t.Error("retry reset deadline or omitted recovery context", req.Recovery)
			}
			if priorSeconds > 0 && req.Recovery.MaxSeconds > priorSeconds {
				t.Error("time budget grew")
			}
			priorSeconds = req.Recovery.MaxSeconds
		}
		req.Recovery = nil
		encoded, _ := json.Marshal(req)
		if string(encoded) != string(before) {
			t.Error("retry changed original choices, locks or repair count")
		}
		return nil, &bridge.CreationPlanningError{Code: "invalid_plan", Message: "格式未通过"}
	}}
	var events []bridge.CreationPlanningProgress
	_, err := h.planCreationWithRetry(context.Background(), planner, request, func(e bridge.CreationPlanningProgress) { events = append(events, e) }, nil, nil)
	if err == nil || planner.calls != 6 || len(events) != 5 || !reflect.DeepEqual(waits, []time.Duration{time.Second, 2 * time.Second, 4 * time.Second, 8 * time.Second, 16 * time.Second}) {
		t.Fatal(planner.calls, waits, events, err)
	}
	after, _ := json.Marshal(request)
	if string(before) != string(after) {
		t.Fatal("input mutated")
	}
}

func TestPlanningDoesNotRetryPermanentFailureOrCancelledWork(t *testing.T) {
	for _, code := range []string{"provider_config_missing", "provider_auth_failed", "provider_request_rejected", "model_image_unsupported", "provider_rate_limited", "execution_capacity_exceeded", "unknown"} {
		t.Run(code, func(t *testing.T) {
			h := &CreationHandler{retryWait: func(context.Context, time.Duration) error { t.Fatal("permanent failure retried"); return nil }}
			p := &retryTestPlanner{call: func(context.Context, bridge.CreationPlanningRequest, int) (*bridge.CreationPlanningResponse, error) {
				return nil, &bridge.CreationPlanningError{Code: code, Message: "需要处理"}
			}}
			_, err := h.planCreationWithRetry(context.Background(), p, bridge.CreationPlanningRequest{}, nil, nil, nil)
			if err == nil || p.calls != 1 {
				t.Fatal(err, p.calls)
			}
		})
	}
	for _, stale := range []bool{false, true} {
		h := &CreationHandler{}
		ctx, cancel := context.WithCancel(context.Background())
		current := true
		h.retryWait = func(context.Context, time.Duration) error {
			if stale {
				current = false
			} else {
				cancel()
			}
			return nil
		}
		p := &retryTestPlanner{call: func(context.Context, bridge.CreationPlanningRequest, int) (*bridge.CreationPlanningResponse, error) {
			return nil, io.ErrUnexpectedEOF
		}}
		_, err := h.planCreationWithRetry(ctx, p, bridge.CreationPlanningRequest{}, nil, func() bool { return current }, nil)
		cancel()
		if !errors.Is(err, context.Canceled) || p.calls != 1 {
			t.Fatal("cancelled or stale operation retried", err, p.calls)
		}
	}
}

func TestPlanningRejectsInvalidDraftThenRetriesWithoutCommittingIt(t *testing.T) {
	h := &CreationHandler{retryWait: func(context.Context, time.Duration) error { return nil }}
	p := &retryTestPlanner{call: func(_ context.Context, req bridge.CreationPlanningRequest, call int) (*bridge.CreationPlanningResponse, error) {
		plan := creativeTestPlan()
		if call == 1 {
			plan.Nodes[1].DependsOn = []string{"missing"}
		}
		if call == 2 && (req.Recovery == nil || req.Recovery.ErrorCode != "invalid_plan") {
			t.Error("validation failure did not reach planner")
		}
		return &bridge.CreationPlanningResponse{Plan: plan}, nil
	}}
	result, err := h.planCreationWithRetry(context.Background(), p, bridge.CreationPlanningRequest{}, nil, nil, nil)
	if err != nil || p.calls != 2 || result.Plan.Nodes[1].DependsOn[0] != "brief" {
		t.Fatal(result, err)
	}
}

func TestAutomaticDecisionAndRepairRecoverWithoutRestartOrExtraImageBudget(t *testing.T) {
	for _, repairing := range []bool{false, true} {
		t.Run(fmtBool(repairing), func(t *testing.T) {
			r, h, f, token, row := setupAutomatic(t)
			doc, _ := projectDocument(row)
			if !repairing {
				doc.Plan.Questions = []bridge.CreativeQuestion{{Question: "氛围", Options: []string{"温暖", "冷峻"}}}
				if err := h.updateProject(&row, doc, false); err != nil {
					t.Fatal(err)
				}
			}
			calls, reviews := 0, 0
			f.reviewDecision = func(req bridge.CreationReviewRequest) *bridge.CreationReviewResponse {
				if repairing && req.NodeID == "visual" {
					reviews++
					if reviews == 1 {
						return &bridge.CreationReviewResponse{Decision: "revise", Reason: "调整构图"}
					}
				}
				return nil
			}
			f.planHook = func(_ context.Context, req bridge.CreationPlanningRequest) (*bridge.CreationPlanningResponse, error) {
				calls++
				if repairing && req.Repair.Attempt != 1 {
					t.Error("planner retry consumed an image repair")
				}
				if calls < 3 {
					return nil, &bridge.CreationPlanningError{Code: "planning_timeout", Message: "超时"}
				}
				p := copyAutomaticPlan(req.CurrentPlan)
				p.Questions = nil
				return &bridge.CreationPlanningResponse{Plan: p, Reply: "继续"}, nil
			}
			startAutomatic(t, r, h, token, row.ID, "retry-automatic")
			row = waitAutomatic(t, h, row.ID)
			doc, _ = projectDocument(row)
			wantMedia := 3
			if repairing {
				wantMedia = 5
			}
			if row.AutomaticStatus != "completed" || calls != 3 || len(f.requests) != wantMedia {
				t.Fatal(row.AutomaticStatus, calls, len(f.requests), doc.Automation.Steps)
			}
			if repairing && doc.Automation.ImageReviews["visual"].Retries != 1 {
				t.Fatal("image budget grew")
			}
			count := 0
			for _, step := range doc.Automation.Steps {
				if step.Stage == "planning_retry" {
					count++
				}
			}
			if count != 2 {
				t.Fatal("automatic retries not visible", doc.Automation.Steps)
			}
		})
	}
}

func fmtBool(value bool) string {
	if value {
		return "repair"
	}
	return "decide"
}

func TestPlanningRetryProgressKeepsLatestAttemptWithoutExposingErrors(t *testing.T) {
	r, h, _, token := setupCreation(t)
	row := createTestProject(t, r, token)
	row = readTestProject(t, h, row.ID)
	doc, _ := projectDocument(row)
	row.Planning, row.PlanningRequestID = true, "exhausted"
	doc.Planning = &bridge.CreativePlanningActivity{ID: "exhausted", Status: "running", StartedAt: time.Now()}
	if err := h.updateProject(&row, doc, false); err != nil {
		t.Fatal(err)
	}
	p := &retryTestPlanner{call: func(context.Context, bridge.CreationPlanningRequest, int) (*bridge.CreationPlanningResponse, error) {
		return nil, io.ErrUnexpectedEOF
	}}
	h.planProject(p, row, bridge.CreationPlanningRequest{})
	row = readTestProject(t, h, row.ID)
	doc, _ = projectDocument(row)
	steps := doc.Messages[0].Planning.Steps
	if p.calls != 6 || len(steps) != 6 || !strings.Contains(steps[4].Message, "5/5") || doc.Messages[0].Planning.Status != "failed" {
		t.Fatal(p.calls, steps)
	}
}

func (p *retryTestPlanner) PlanCreation(ctx context.Context, req bridge.CreationPlanningRequest) (*bridge.CreationPlanningResponse, error) {
	p.calls++
	return p.call(ctx, req, p.calls)
}

func TestPlanningAutomaticallyRecoversBrokenConnectionInSameActivity(t *testing.T) {
	r, h, _, token := setupCreation(t)
	row := seedCreativePlan(t, h, createTestProject(t, r, token))
	doc, _ := projectDocument(row)
	row.Planning, row.PlanningRequestID = true, "retry-plan"
	doc.Planning = &bridge.CreativePlanningActivity{ID: row.PlanningRequestID, Status: "running", StartedAt: time.Now()}
	doc.Messages = []bridge.CreativeMessage{{Role: "user", Content: "沿用已选画幅继续规划"}}
	if err := h.updateProject(&row, doc, false); err != nil {
		t.Fatal(err)
	}
	h.retryWait = func(context.Context, time.Duration) error { return nil }
	planner := &retryTestPlanner{call: func(ctx context.Context, req bridge.CreationPlanningRequest, call int) (*bridge.CreationPlanningResponse, error) {
		if call == 1 {
			return nil, io.ErrUnexpectedEOF
		}
		return &bridge.CreationPlanningResponse{Plan: creativeTestPlan(), Reply: "已完成规划"}, nil
	}}
	h.planProject(planner, row, bridge.CreationPlanningRequest{ProjectID: row.ID, UserID: row.UserID, CurrentPlan: doc.Plan, Messages: doc.Messages})
	row = readTestProject(t, h, row.ID)
	doc, _ = projectDocument(row)
	if planner.calls != 2 || row.Planning || row.Error != "" || len(doc.Messages) != 2 || doc.Messages[1].Planning.Status != "completed" {
		t.Fatalf("recoverable planning failure still required user intervention: calls=%d error=%s messages=%+v", planner.calls, row.Error, doc.Messages)
	}
	if len(doc.Messages[1].Planning.Steps) < 2 || doc.Messages[1].Planning.Steps[0].Stage != "planning_retry" {
		t.Fatal("retry was not visible within the original activity")
	}
}
