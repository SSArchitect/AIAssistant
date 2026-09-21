package handlers

import (
	"errors"
	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"reflect"
)

func validateRegionRepair(previous, proposed bridge.CreativePlan, repair *bridge.CreationRepairFeedback) error {
	if repair == nil {
		return nil
	}
	before, after := map[string]bridge.CreativeNode{}, map[string]bridge.CreativeNode{}
	for _, node := range previous.Nodes {
		before[node.ID] = node
	}
	for _, node := range proposed.Nodes {
		after[node.ID] = node
	}
	old, found := before[repair.NodeID]
	next, exists := after[repair.NodeID]
	if !found || !exists || len(old.ImageLayout) == 0 || len(next.ImageLayout) == 0 {
		return nil
	}
	if !reflect.DeepEqual(old.ImageLayout, next.ImageLayout) || !reflect.DeepEqual(old.References, next.References) || old.AspectRatio != next.AspectRatio || !reflect.DeepEqual(old.DependsOn, next.DependsOn) {
		return nil
	}
	pending := append([]string(nil), next.DependsOn...)
	seen := map[string]bool{}
	for len(pending) > 0 {
		id := pending[len(pending)-1]
		pending = pending[:len(pending)-1]
		if seen[id] {
			continue
		}
		seen[id] = true
		a, ok := before[id]
		b, exists := after[id]
		if !ok || !exists || !reflect.DeepEqual(a, b) {
			return nil
		}
		pending = append(pending, b.DependsOn...)
	}
	return errors.New("节点 " + next.ID + " 使用image_layout区域生成，本次有效执行内容未变；请修改subject_prompt、位置、比例或有效参考，普通prompt不会生效")
}
