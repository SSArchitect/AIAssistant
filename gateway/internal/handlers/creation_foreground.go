package handlers

import (
	"context"
	"errors"
	"github.com/aan/agent-assistant-gateway/internal/models"
)

// A foreground quality failure cannot be fixed by downloading the same accepted
// pixels again. Preserve that run, then repair the effective recipe normally.
func (h *CreationHandler) repairInvalidForeground(ctx context.Context, run models.CreationRun, request string) (bool, bool, error) {
	h.mu.Lock()
	row := models.CreationProject{ID: run.ProjectID}
	if !h.automaticCurrent(&row, request) {
		h.mu.Unlock()
		return true, true, nil
	}
	doc, err := projectDocument(row)
	if err != nil {
		h.mu.Unlock()
		return true, false, err
	}
	node, exists := creativeNode(doc, run.ProjectNodeID)
	if !exists || len(node.ImageLayout) != 1 || node.ImageLayout[0].CompositeMode != "foreground_v1" {
		h.mu.Unlock()
		return false, false, nil
	}
	state := doc.States[node.ID]
	if state.RunID != run.ID || state.Revision != run.NodeRevision {
		h.mu.Unlock()
		return true, false, errors.New("节点已变化，保留原生成任务，不应用过时的前景返工")
	}
	stop, err := h.repairAutomatic(ctx, row, doc, node, nil, "前景未通过完整性、底色分离或画幅边界校验，原任务及中间图已保留。请调整image_layout中真实主体描述、构图或有问题的参考，使完整人物与道具可分离并位于画幅内；不要只修改备用prompt、放宽原要求或重取同一不合格结果。", request, nil)
	return true, stop, err
}
