package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"reflect"
	"strings"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/models"
)

// Repair may change the rejected node and unconfirmed descendants only. All other
// nodes, including decisions made earlier in this loop, remain locked.
func automaticRepairLocks(doc creativeDocument, nodeID string) []string {
	affected := map[string]bool{nodeID: true}
	locked := map[string]bool{}
	for _, id := range doc.Automation.LockedNodeIDs {
		locked[id] = true
	}
	for _, id := range lockedCreativeNodes(doc) {
		locked[id] = true
	}
	result := []string{}
	for _, node := range doc.Plan.Nodes {
		for _, dep := range node.DependsOn {
			affected[node.ID] = affected[node.ID] || affected[dep]
		}
		if locked[node.ID] || !affected[node.ID] {
			result = append(result, node.ID)
		}
	}
	return result
}

func validateAutomaticRepair(doc creativeDocument, plan bridge.CreativePlan, req bridge.CreationPlanningRequest) error {
	if err := validateRegionRepair(doc.Plan, plan, req.Repair); err != nil {
		return err
	}
	if err := validateEditSources(doc, plan, req); err != nil {
		return err
	}
	// New scene prerequisites are needed when review detects a missing location.
	// Keep the original delivery nodes in order and prohibit unrelated additions.
	original := map[string]bridge.CreativeNode{}
	affected := map[string]bool{req.Repair.NodeID: true}
	locked := map[string]bool{}
	for _, id := range req.LockedNodeIDs {
		locked[id] = true
	}
	for _, node := range doc.Plan.Nodes {
		original[node.ID] = node
		for _, dep := range node.DependsOn {
			affected[node.ID] = affected[node.ID] || affected[dep]
		}
	}
	linked := map[string]bool{}
	for i := len(plan.Nodes) - 1; i >= 0; i-- {
		node := plan.Nodes[i]
		if (affected[node.ID] && !locked[node.ID]) || linked[node.ID] {
			for _, ref := range node.References {
				if ref.NodeID != "" {
					linked[ref.NodeID] = true
				}
			}
		}
	}
	index := 0
	for _, node := range plan.Nodes {
		if _, exists := original[node.ID]; exists {
			if index >= len(doc.Plan.Nodes) || node.ID != doc.Plan.Nodes[index].ID || node.Kind != doc.Plan.Nodes[index].Kind {
				return errors.New("自动返工不能重排原有节点或改变产物类型")
			}
			index++
		} else if node.Kind != "image" || (node.Purpose != "scene" && node.Purpose != "shot_reference" && node.Purpose != "character") || node.Count != 1 || !linked[node.ID] {
			return errors.New("自动返工只能补充受影响视频实际引用的角色/场景/分镜图片，不能新增交付或无关节点")
		}
	}
	if index != len(doc.Plan.Nodes) {
		return errors.New("自动返工不能删除原有节点")
	}
	protected := doc
	activity := *doc.Automation
	activity.LockedNodeIDs = req.LockedNodeIDs
	protected.Automation = &activity
	// Python emits literal '<' in JSON while persisted Go JSON escapes it.
	// Compare storyboard values, then retain the exact original locked node so
	// transport formatting cannot invalidate its state during plan application.
	for _, id := range req.LockedNodeIDs {
		before, exists := creativeNode(doc, id)
		if !exists {
			continue
		}
		for i, after := range plan.Nodes {
			if after.ID != id {
				continue
			}
			var oldBoard, newBoard interface{}
			var oldErr, newErr error
			if len(before.Storyboard) > 0 {
				oldErr = json.Unmarshal(before.Storyboard, &oldBoard)
			}
			if len(after.Storyboard) > 0 {
				newErr = json.Unmarshal(after.Storyboard, &newBoard)
			}
			if oldErr == nil && newErr == nil && reflect.DeepEqual(oldBoard, newBoard) {
				after.Storyboard = before.Storyboard
				if reflect.DeepEqual(before, after) {
					plan.Nodes[i] = before
				}
			}
		}
	}
	if err := protectAutomaticPlan(protected, plan); err != nil {
		return err
	}
	rejected := map[string]bool{}
	for _, id := range req.Repair.CandidateIDs {
		rejected[id] = true
	}
	for _, node := range plan.Nodes {
		if rejected[node.AssetID] {
			return errors.New("自动返工不能采用已拒绝的候选图片")
		}
		for _, ref := range node.References {
			if rejected[ref.AssetID] {
				return errors.New("自动返工不能引用已拒绝的候选图片")
			}
		}
		if node.ID == req.Repair.NodeID && node.Kind == "image" && node.AssetID != "" {
			return errors.New("角色返工必须保留生图节点，不能直接绑定现有图片")
		}
	}
	return nil
}

// Caller holds h.mu; this method always releases it. Planning runs outside the
// mutex so stop requests remain responsive and late responses can be discarded.
func (h *CreationHandler) repairAutomatic(ctx context.Context, row models.CreationProject, doc creativeDocument, node bridge.CreativeNode, candidates []string, reason, request string, findings []bridge.CreationReviewFinding) (bool, error) {
	if node.Kind == "image" {
		history := imageReviewHistory(&doc, node.ID, candidates)
		if history.Retries >= maxAutomaticImageRetries {
			// The final generation can fail foreground validation before producing
			// candidates. Finish that pending round and select from earlier output.
			history.PendingGeneration = false
			err := h.updateProject(&row, doc, false)
			h.mu.Unlock()
			return false, err
		}
		history.Retries++
	}
	planner, ok := h.generator.(creationPlanner)
	if !ok {
		h.mu.Unlock()
		return false, errors.New("自动返工尚未连接创作规划")
	}
	req, err := h.automaticRequest(row, doc, node, candidates)
	if err != nil {
		h.mu.Unlock()
		return false, err
	}
	req.LockedNodeIDs = automaticRepairLocks(doc, node.ID)
	req.RequireVideoScenes = true
	for _, id := range req.LockedNodeIDs {
		if id == node.ID {
			h.mu.Unlock()
			return false, errors.New("需要修正的节点已确认，请先解除确认后继续")
		}
	}
	if doc.Automation.RepairCounts == nil {
		doc.Automation.RepairCounts = map[string]int{}
	}
	feedback := bridge.CreationRepairFeedback{NodeID: node.ID, Reason: reason, CandidateIDs: append([]string{}, candidates...), Attempt: doc.Automation.RepairCounts[node.ID] + 1, PreviousFeedback: []string{}}
	feedback.Findings = findings
	feedback.Execution = h.repairExecution(row, node.ID, candidates)
	feedback.PreviousAttempts = h.repairAttempts(row, node.ID, doc.Automation.Repairs)
	for _, earlier := range doc.Automation.Repairs {
		if earlier.NodeID == node.ID {
			feedback.PreviousFeedback = append(feedback.PreviousFeedback, earlier.Reason)
		}
	}
	if len(feedback.PreviousFeedback) > 10 {
		feedback.PreviousFeedback = feedback.PreviousFeedback[len(feedback.PreviousFeedback)-10:]
	}
	req.Repair = &feedback
	doc.Automation.RepairCounts[node.ID] = feedback.Attempt
	// The request includes recent feedback; persisted history does not nest it.
	history := feedback
	history.PreviousFeedback = nil
	history.PreviousAttempts = nil
	doc.Automation.Repairs = append(doc.Automation.Repairs, history)
	if len(doc.Automation.Repairs) > 20 {
		doc.Automation.Repairs = doc.Automation.Repairs[len(doc.Automation.Repairs)-20:]
	}
	automaticStep(&doc, "revise", fmt.Sprintf("「%s」第%d次返工：%s", node.Title, feedback.Attempt, reason), node.ID)
	err = h.updateProject(&row, doc, false)
	expectedRevision := row.Revision
	h.mu.Unlock()
	if err != nil {
		return false, err
	}
	callCtx, cancel := context.WithTimeout(ctx, 915*time.Second)
	defer cancel()
	response, err := h.planCreationWithRetry(callCtx, planner, req,
		func(event bridge.CreationPlanningProgress) {
			h.recordAutomaticPlanningProgress(&row, request, node.ID, event)
		},
		func() bool { return h.automaticPlanningCurrent(row, request) },
		func(response *bridge.CreationPlanningResponse) error {
			return validateAutomaticRepair(doc, response.Plan, req)
		})
	expectedRevision = row.Revision
	h.mu.Lock()
	defer h.mu.Unlock()
	if !h.automaticCurrent(&row, request) || ctx.Err() != nil {
		return true, nil
	}
	doc, readErr := projectDocument(row)
	if readErr != nil {
		return false, errors.New("无法读取返工方案")
	}
	if row.Revision != expectedRevision {
		return false, errors.New("返工期间方案发生变化，已保留最新内容")
	}
	for _, asset := range req.Assets {
		if asset.DataURL == "" {
			continue
		}
		current, readErr := h.imageInput(row.UserID, asset.ID)
		if readErr != nil || creativeHash(current) != creativeHash(asset.DataURL) {
			return false, errors.New("返工期间参考图片发生变化，请检查后继续")
		}
	}
	if err != nil || response == nil {
		return false, errors.New(creationFailureMessage(err, "自动返工暂未完成，原有内容和候选图片已保留，可继续一键生成"))
	}
	_ = persistTokenUsageRecordDB(h.db, row.ID, row.UserID, 0, "creation_director", time.Now(), &bridge.ChatResponse{ModelUsed: response.ModelUsed, TokensUsed: response.TokensUsed, RunID: response.RunID, Runtime: "self"})
	allowed := map[string]bool{}
	for _, asset := range req.Assets {
		if strings.HasPrefix(asset.MimeType, "image/") {
			allowed[asset.ID] = true
		}
	}
	if err = validateCreativePlan(response.Plan, allowed); err != nil {
		return false, err
	}
	if err = validateAutomaticRepair(doc, response.Plan, req); err != nil {
		return false, err
	}
	if len(response.Plan.Questions) > 0 {
		return false, fmt.Errorf("返工需要补充不可替代的信息：%s", response.Plan.Questions[0].Question)
	}
	before := doc.States[node.ID]
	originalStates := doc.States
	// A targeted repair cannot rename the project or rewrite its overall brief.
	plan := doc.Plan
	plan.Nodes = response.Plan.Nodes
	doc = applyAutomaticRepair(doc, plan)
	if doc.States[node.ID].Revision == before.Revision {
		// Even unchanged design text requires fresh candidates after rejection. A new
		// revision also supplies a fresh submission key, without deleting old assets.
		doc.States[node.ID] = creativeNodeState{Revision: before.Revision + 1, Candidates: []string{}}
		invalidateCreativeChildren(&doc, node.ID)
	}
	if node.Kind == "image" {
		// This revision is our own repair, not a new user request.
		doc.Automation.ImageReviews[node.ID].PendingGeneration = true
	}
	syncAutomaticImageReviewRevisions(&doc)
	// Locked selections must survive both direct edits and dependency invalidation.
	for _, id := range req.LockedNodeIDs {
		if !reflect.DeepEqual(doc.States[id], originalStates[id]) {
			return false, errors.New("自动返工不能使已保留节点的确认失效")
		}
	}
	automaticStep(&doc, "revised", "已调整「"+node.Title+"」，继续生成与审阅", node.ID)
	return false, h.updateProject(&row, doc, true)
}
