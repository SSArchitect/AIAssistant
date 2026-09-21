package handlers

import (
	"encoding/json"
	"errors"
	"reflect"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/models"
)

// Edit sources belong to the same node's draft history, not its identity inputs.
// Keep the original reference graph for independent acceptance review.
func validateEditSources(doc creativeDocument, plan bridge.CreativePlan, req bridge.CreationPlanningRequest) error {
	locked := map[string]bool{}
	for _, id := range req.LockedNodeIDs {
		locked[id] = true
	}
	for _, node := range plan.Nodes {
		if node.EditSourceAssetID == "" {
			continue
		}
		if req.Repair != nil && req.Repair.NodeID == node.ID && exhaustedEdits(req) {
			return errors.New("连续三次编辑仍未通过同一要求，请清空编辑来源并重新规划生成")
		}
		before, exists := creativeNode(doc, node.ID)
		if !exists || before.Kind != "image" || node.Kind != "image" {
			return errors.New("编辑草稿必须来自当前已有图片节点")
		}
		if creationJSON(before.References) != creationJSON(node.References) || !reflect.DeepEqual(before.DependsOn, node.DependsOn) || before.AspectRatio != node.AspectRatio {
			return errors.New("局部编辑不能同时改变原参考关系或画幅，请重新生成")
		}
		if !sameDraftAncestors(doc, creativeDocument{Plan: plan}, node, false) {
			return errors.New("局部编辑不能同时更换上游内容，请清空编辑来源后重新生成")
		}
		if before.EditSourceAssetID == node.EditSourceAssetID {
			continue
		}
		if locked[node.ID] {
			return errors.New("不能编辑已确认节点的草稿")
		}
		allowed := false
		if req.Repair != nil {
			if req.AutomaticMode && req.Repair.NodeID == node.ID {
				for _, id := range req.Repair.CandidateIDs {
					allowed = allowed || id == node.EditSourceAssetID
				}
			}
		} else {
			state := doc.States[node.ID]
			allowed = state.SelectedAssetID == node.EditSourceAssetID
			for _, id := range state.Candidates {
				allowed = allowed || id == node.EditSourceAssetID
			}
		}
		if !allowed {
			return errors.New("待修草稿必须是当前节点自己的候选")
		}
	}
	return nil
}

// A draft embeds its ancestor context even though the editor only receives one
// image. Check that context independently of the current graph's approval state.
func sameDraftAncestors(before, after creativeDocument, node bridge.CreativeNode, checkState bool) bool {
	pending := append([]string{}, node.DependsOn...)
	seen := map[string]bool{}
	for len(pending) > 0 {
		id := pending[len(pending)-1]
		pending = pending[:len(pending)-1]
		if seen[id] {
			continue
		}
		seen[id] = true
		old, oldOK := creativeNode(before, id)
		current, currentOK := creativeNode(after, id)
		old.RevisionSuggestions, current.RevisionSuggestions = nil, nil
		if !oldOK || !currentOK || !creativeNodesEqual(old, current) {
			return false
		}
		if checkState {
			a, b := before.States[id], after.States[id]
			if a.Revision != b.Revision || a.SelectedAssetID != b.SelectedAssetID {
				return false
			}
		}
		pending = append(pending, current.DependsOn...)
	}
	return true
}

func (h *CreationHandler) validateDraftContext(row models.CreationProject, doc creativeDocument, node bridge.CreativeNode) error {
	if node.EditSourceAssetID == "" {
		return nil
	}
	if err := h.validateDraftProvenance(row, node); err != nil {
		return err
	}
	var run models.CreationRun
	if err := h.db.Table("creation_runs AS r").Select("r.*").Joins("JOIN creation_assets AS a ON a.run_id = r.id AND a.user_id = r.user_id").
		Where("a.id = ? AND a.user_id = ? AND r.project_id = ? AND r.project_node_id = ?", node.EditSourceAssetID, row.UserID, row.ID, node.ID).Take(&run).Error; err != nil {
		return errors.New("无法核对待修草稿的原始上下文")
	}
	var source creativeDocument
	if json.Unmarshal([]byte(run.Snapshot), &source) != nil {
		return errors.New("待修草稿缺少原始上下文，请重新生成")
	}
	original, exists := creativeNode(source, node.ID)
	if !exists || creationJSON(original.References) != creationJSON(node.References) ||
		!reflect.DeepEqual(original.DependsOn, node.DependsOn) || original.AspectRatio != node.AspectRatio ||
		!sameDraftAncestors(source, doc, node, true) {
		return errors.New("待修草稿的上游内容或参考已变化，请清空编辑来源后重新规划生成")
	}
	return nil
}

func (h *CreationHandler) validateDraftProvenance(row models.CreationProject, node bridge.CreativeNode) error {
	if node.EditSourceAssetID == "" {
		return nil
	}
	var count int64
	err := h.db.Table("creation_assets AS a").Joins("JOIN creation_runs AS r ON r.id = a.run_id AND r.user_id = a.user_id").
		Where("a.id = ? AND a.user_id = ? AND r.project_id = ? AND r.project_node_id = ?", node.EditSourceAssetID, row.UserID, row.ID, node.ID).Count(&count).Error
	if err != nil || count != 1 {
		return errors.New("待修草稿的项目或节点来源不匹配")
	}
	return nil
}
