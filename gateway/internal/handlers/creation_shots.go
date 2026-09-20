package handlers

import (
	"encoding/json"
	"fmt"
	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"regexp"
)

var creativeShotID = regexp.MustCompile(`^[a-zA-Z0-9_-]{1,80}$`)

func validateShotBindings(node bridge.CreativeNode, nodes map[string]bridge.CreativeNode) error {
	ids := map[string]bool{}
	if len(node.ShotIDs) > 0 {
		var board struct {
			Shots []json.RawMessage `json:"shots"`
		}
		if json.Unmarshal(node.Storyboard, &board) != nil || len(board.Shots) != len(node.ShotIDs) || len(node.ShotIDs) > 12 {
			return fmt.Errorf("镜头ID需与分镜逐一对应：%s", node.Title)
		}
		for _, id := range node.ShotIDs {
			if ids[id] || !creativeShotID.MatchString(id) {
				return fmt.Errorf("镜头ID重复或无效：%s", node.Title)
			}
			ids[id] = true
		}
	}
	bindings := 0
	for _, ref := range node.References {
		source, ok := nodes[ref.NodeID]
		shot := ok && source.Kind == "image" && source.Purpose == "shot_reference"
		if len(ref.ShotIDs) > 0 {
			if !shot || ref.Role != "reference" || len(ref.ShotIDs) > 12 || source.AspectRatio != node.AspectRatio {
				return fmt.Errorf("分镜图引用或画幅无效：%s", node.Title)
			}
			seen := map[string]bool{}
			for _, id := range ref.ShotIDs {
				if !ids[id] || seen[id] {
					return fmt.Errorf("分镜图绑定了未知或重复镜头：%s", node.Title)
				}
				seen[id] = true
			}
			bindings++
		} else if shot && len(ids) > 0 {
			return fmt.Errorf("分镜图缺少镜头绑定：%s", node.Title)
		}
	}
	if len(ids) > 0 && bindings == 0 {
		return fmt.Errorf("请先准备并绑定关键分镜图：%s", node.Title)
	}
	return nil
}
