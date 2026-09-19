package handlers

import (
	"fmt"
	"math"
	"sort"

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
		if err := validateSceneIntervals(n, nodes); err != nil {
			return err
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
			count++
		}
		if count == 0 {
			return fmt.Errorf("视频缺少对应的场景节点，需先补齐场景再生成：%s", n.Title)
		}
	}
	return nil
}

// Time ranges also allow an uninterrupted flying shot to pass through several
// environments. Single-scene legacy clips retain an implicit full-clip range.
func validateSceneIntervals(node bridge.CreativeNode, nodes map[string]bridge.CreativeNode) error {
	scenes, bound := 0, 0
	intervals := []bridge.CreativeSceneInterval{}
	for _, ref := range node.References {
		source, ok := nodes[ref.NodeID]
		scene := node.Kind == "video" && ok && source.Kind == "image" && source.Purpose == "scene" && (ref.Role == "reference" || ref.Role == "first_frame")
		if scene {
			scenes++
		}
		if len(ref.SceneIntervals) == 0 {
			continue
		}
		if !scene || ref.Role != "reference" || len(ref.SceneIntervals) > 12 {
			return fmt.Errorf("场景时段只能绑定视频的场景reference：%s", node.Title)
		}
		bound++
		intervals = append(intervals, ref.SceneIntervals...)
	}
	if scenes <= 1 && bound == 0 {
		return nil
	}
	if scenes != bound {
		return fmt.Errorf("多场景视频需逐图填写场景时段：%s", node.Title)
	}
	sort.Slice(intervals, func(i, j int) bool { return intervals[i].StartSeconds < intervals[j].StartSeconds })
	cursor := 0.0
	for _, span := range intervals {
		start, end := span.StartSeconds, span.EndSeconds
		if math.IsNaN(start) || math.IsInf(start, 0) || math.IsNaN(end) || math.IsInf(end, 0) || math.Abs(start-cursor) > 0.000001 || end <= start || end > float64(node.DurationSeconds) || math.Abs(start*1000-math.Round(start*1000)) > 0.000001 || math.Abs(end*1000-math.Round(end*1000)) > 0.000001 {
			return fmt.Errorf("场景时段必须从0秒起连续覆盖视频，不能空缺、重叠或越界：%s", node.Title)
		}
		cursor = end
	}
	if cursor != float64(node.DurationSeconds) {
		return fmt.Errorf("场景时段必须覆盖到视频结束：%s", node.Title)
	}
	return nil
}
