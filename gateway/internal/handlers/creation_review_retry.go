package handlers

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/models"
)

func retryableCreationReview(err error) bool {
	if errors.Is(err, context.Canceled) {
		return false
	}
	var model *bridge.CreationPlanningError
	if errors.As(err, &model) {
		switch model.Code {
		case "provider_unavailable", "planning_timeout", "review_invalid_result",
			"review_evidence_quote_mismatch", "review_evidence_missing_findings",
			"review_evidence_unknown_source", "review_evidence_candidate_coverage",
			"review_evidence_criteria_unavailable", "review_evidence_region_surface_unavailable":
			return true
		}
		return false
	}
	var network net.Error
	return errors.Is(err, context.DeadlineExceeded) || errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF) || errors.As(err, &network)
}

// Re-review the same immutable input, never re-run media or apply partial
// decisions. Stop and revision checks also run after each backoff.
func (h *CreationHandler) reviewAutomaticWithRetry(ctx context.Context, row *models.CreationProject, request string, req bridge.CreationReviewRequest) (*bridge.CreationReviewResponse, error) {
	for attempt := 0; ; attempt++ {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		h.mu.Lock()
		latest := *row
		current := h.automaticCurrent(&latest, request)
		h.mu.Unlock()
		if !current {
			return nil, context.Canceled
		}
		if latest.Revision != row.Revision {
			return nil, errors.New("审阅期间方案发生变化，已保留最新内容")
		}
		callCtx, cancel := context.WithTimeout(ctx, 195*time.Second)
		result, err := h.generator.(creationReviewer).ReviewCreation(callCtx, req)
		cancel()
		if err == nil || ctx.Err() != nil || attempt >= 2 || !retryableCreationReview(err) {
			return result, err
		}
		h.mu.Lock()
		if !h.automaticCurrent(&latest, request) {
			h.mu.Unlock()
			return nil, context.Canceled
		}
		if latest.Revision != row.Revision {
			h.mu.Unlock()
			return nil, errors.New("审阅期间方案发生变化，已保留最新内容")
		}
		doc, readErr := projectDocument(latest)
		if readErr == nil {
			automaticStep(&doc, "review_retry", fmt.Sprintf("审阅暂未完成，正在自动重试（%d/2）；保留原候选与确认结果", attempt+1), req.NodeID)
			readErr = h.updateProject(&latest, doc, false)
			if readErr == nil {
				*row = latest
			}
		}
		h.mu.Unlock()
		if readErr != nil {
			return nil, readErr
		}
		wait := h.retryWait
		if wait == nil {
			wait = waitCreationRetry
		}
		if err = wait(ctx, time.Duration(2<<attempt)*time.Second); err != nil {
			return nil, err
		}
	}
}
