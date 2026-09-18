package handlers

import (
	"fmt"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
)

// Enforced on new planning and the automatic preflight, not while loading legacy
// canvases. Confirmed videos remain immutable; unfinished videos gain scene nodes.
func validateVideoScenes(plan bridge.CreativePlan, lockedIDs []string) error {
	locked := map[string]bool{}
	for _, id := range lockedIDs {
		locked[id] = true
	}
	nodes := map[string]bridge.CreativeNode{}
	for _, n := range plan.Nodes {
		nodes[n.ID] = n
	}
	owners := map[string]string{}
	for _, n := range plan.Nodes {
		if locked[n.ID] {
			continue
		}
		if n.Purpose == "scene" {
			if n.Kind != "image" || n.CharacterStyle != "" {
				return fmt.Errorf("场景节点不能套用人物转换模板：%s", n.Title)
			}
			for _, ref := range n.References {
				if ref.Role != "style" {
					return fmt.Errorf("场景节点只借用画风，不引用角色身份：%s", n.Title)
				}
			}
		}
		if n.Kind != "video" {
			continue
		}
		count := 0
		for _, ref := range n.References {
			scene, ok := nodes[ref.NodeID]
			if !ok || scene.Purpose != "scene" || scene.Kind != "image" || (ref.Role != "reference" && ref.Role != "first_frame") {
				continue
			}
			if scene.AspectRatio != n.AspectRatio {
				return fmt.Errorf("场景与视频画幅不一致：%s", n.Title)
			}
			if owner := owners[scene.ID]; owner != "" && owner != n.ID {
				return fmt.Errorf("每个视频需要独立场景节点：%s", n.Title)
			}
			owners[scene.ID] = n.ID
			count++
		}
		if count == 0 {
			return fmt.Errorf("视频缺少对应的场景节点，需先补齐场景再生成：%s", n.Title)
		}
	}
	return nil
}
