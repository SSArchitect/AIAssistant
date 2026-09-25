package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"strings"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/models"
)

const maxCreationPlanningRetries = 5

// Retry the read-only planning operation, never the media submission. Every
// entry point shares this policy and the original total deadline.
func planningRetryCode(err error) string {
	if errors.Is(err, context.Canceled) {
		return ""
	}
	var planning *bridge.CreationPlanningError
	if errors.As(err, &planning) {
		switch planning.Code {
		case "provider_unavailable", "planning_timeout", "planning_output_truncated", "invalid_plan",
			"plan_constraint_failed", "execution_compaction_failed", "video_reference_failed", "planning_no_progress", "planning_failed":
			return planning.Code
		}
		return ""
	}
	var transport net.Error
	if errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF) || errors.As(err, &transport) {
		return "provider_unavailable"
	}
	var syntax *json.SyntaxError
	var shape *json.UnmarshalTypeError
	if errors.As(err, &syntax) || errors.As(err, &shape) {
		return "invalid_plan"
	}
	return ""
}

func validatePlanningResponse(response *bridge.CreationPlanningResponse, req bridge.CreationPlanningRequest) error {
	if response == nil {
		return errors.New("创作规划结果为空")
	}
	allowed := map[string]bool{}
	for _, asset := range req.Assets {
		if strings.HasPrefix(asset.MimeType, "image/") {
			allowed[asset.ID] = true
		}
	}
	if err := validateCreativePlan(response.Plan, allowed); err != nil {
		return err
	}
	if req.RequireVideoScenes {
		return validateVideoScenes(response.Plan, req.LockedNodeIDs)
	}
	return nil
}

func (h *CreationHandler) planCreationWithRetry(ctx context.Context, planner creationPlanner, req bridge.CreationPlanningRequest,
	progress func(bridge.CreationPlanningProgress), current func() bool, validate func(*bridge.CreationPlanningResponse) error,
) (*bridge.CreationPlanningResponse, error) {
	ctx, cancel := context.WithTimeout(ctx, 915*time.Second)
	defer cancel()
	wait := h.retryWait
	if wait == nil {
		wait = waitCreationRetry
	}
	for attempt := 0; ; attempt++ {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		if current != nil && !current() {
			return nil, context.Canceled
		}
		var result *bridge.CreationPlanningResponse
		var err error
		if streaming, ok := planner.(creationProgressPlanner); ok {
			result, err = streaming.PlanCreationWithProgress(ctx, req, progress)
		} else {
			result, err = planner.PlanCreation(ctx, req)
		}
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		if current != nil && !current() {
			return nil, context.Canceled
		}
		if err == nil {
			err = validatePlanningResponse(result, req)
			if err == nil && validate != nil {
				err = validate(result)
			}
			if err == nil {
				return result, nil
			}
			err = &bridge.CreationPlanningError{Code: "invalid_plan", Message: "规划节点校验未通过，原有内容已保留"}
		}
		code := planningRetryCode(err)
		if code == "" || attempt >= maxCreationPlanningRetries {
			return nil, err
		}
		if progress != nil {
			progress(bridge.CreationPlanningProgress{Stage: "planning_retry", Message: fmt.Sprintf("规划暂未完成，正在自动重试（%d/%d）；保留原要求、已选方向与已确认内容", attempt+1, maxCreationPlanningRetries)})
		}
		if err = wait(ctx, time.Duration(1<<attempt)*time.Second); err != nil {
			return nil, err
		}
		deadline, _ := ctx.Deadline()
		seconds := int(time.Until(deadline).Seconds())
		if seconds <= 0 {
			return nil, context.DeadlineExceeded
		}
		if seconds > 900 {
			seconds = 900
		}
		req.Recovery = &bridge.CreativePlanningRecovery{Attempt: attempt + 1, ErrorCode: code, MaxSeconds: seconds}
	}
}

func (h *CreationHandler) planningRequestCurrent(submitted models.CreationProject) bool {
	var count int64
	return h.db.Model(&models.CreationProject{}).Where("id = ? AND user_id = ? AND planning_request_id = ? AND planning = ?",
		submitted.ID, submitted.UserID, submitted.PlanningRequestID, true).Count(&count).Error == nil && count == 1
}

func (h *CreationHandler) automaticPlanningCurrent(row models.CreationProject, request string) bool {
	var count int64
	return h.db.Model(&models.CreationProject{}).Where("id = ? AND user_id = ? AND automatic_request_id = ? AND automatic_status = ? AND revision = ?",
		row.ID, row.UserID, request, "running", row.Revision).Count(&count).Error == nil && count == 1
}

// Progress advances the persisted revision too. Update our expected version so
// our own milestones do not look like an external edit when the result arrives.
func (h *CreationHandler) recordAutomaticPlanningProgress(row *models.CreationProject, request, node string, event bridge.CreationPlanningProgress) {
	if event.Stage == "" || len(event.Stage) > 40 || event.Message == "" || len([]rune(event.Message)) > 300 {
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	if !h.automaticPlanningCurrent(*row, request) {
		return
	}
	doc, err := projectDocument(*row)
	if err != nil || doc.Automation == nil {
		return
	}
	automaticStep(&doc, event.Stage, event.Message, node)
	_ = h.updateProject(row, doc, false)
}
