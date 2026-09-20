package handlers

import (
	"errors"
	"strings"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
)

const maxCreativeNodes = 64
const maxPlanningAssets = 1024
const maxPlanningPreviews = 12

// Keep ownership/reference metadata for the full canvas, but send pixels only
// for the current task. Generated assets are not a project attachment quota.
func planningAssetContext(doc creativeDocument, focus string, explicit, candidates []string) ([]string, []string) {
	ids, previews := []string{}, []string{}
	known, viewed := map[string]bool{}, map[string]bool{}
	add := func(id string, preview bool) {
		if id == "" {
			return
		}
		if !known[id] {
			known[id] = true
			ids = append(ids, id)
		}
		if preview && !viewed[id] {
			viewed[id] = true
			previews = append(previews, id)
		}
	}
	for _, id := range candidates {
		add(id, true)
	}
	for _, id := range explicit {
		add(id, true)
	}
	visited := map[string]bool{}
	var visit func(string)
	visit = func(id string) {
		if visited[id] {
			return
		}
		visited[id] = true
		node, ok := creativeNode(doc, id)
		if !ok {
			return
		}
		add(doc.States[id].SelectedAssetID, true)
		add(node.AssetID, true)
		if id != focus && node.Kind == "image" && (node.AssetID != "" || doc.States[id].SelectedAssetID != "") {
			return
		}
		for _, ref := range node.References {
			add(ref.AssetID, true)
			if ref.NodeID != "" {
				visit(ref.NodeID)
			}
		}
		for _, dep := range node.DependsOn {
			visit(dep)
		}
	}
	if focus != "" {
		visit(focus)
	}
	for _, id := range doc.AssetIDs {
		add(id, focus == "")
	}
	for _, node := range doc.Plan.Nodes {
		add(doc.States[node.ID].SelectedAssetID, focus == "")
		add(node.AssetID, focus == "")
		for _, ref := range node.References {
			add(ref.AssetID, focus == "")
		}
	}
	return ids, previews
}

func (h *CreationHandler) planningAssets(user string, ids, previewIDs []string) ([]bridge.PlanningAsset, error) {
	unique, seen := []string{}, map[string]bool{}
	for _, id := range ids {
		if id != "" && !seen[id] {
			seen[id] = true
			unique = append(unique, id)
		}
	}
	if len(unique) > maxPlanningAssets {
		return nil, errors.New("本轮参考目录过大，请缩小本次规划范围")
	}
	result := []bridge.PlanningAsset{}
	if len(unique) == 0 {
		return result, nil
	}
	var rows []bridge.PlanningAsset
	err := h.db.Table("creation_assets").Select("creation_assets.id, drive_items.name, drive_items.mime_type").
		Joins("JOIN drive_items ON drive_items.id = creation_assets.drive_item_id AND drive_items.user_id = creation_assets.user_id").
		Where("creation_assets.user_id = ? AND creation_assets.id IN ?", user, unique).Find(&rows).Error
	if err != nil {
		return nil, err
	}
	byID := map[string]bridge.PlanningAsset{}
	for _, row := range rows {
		byID[row.ID] = row
	}
	if len(byID) != len(unique) {
		return nil, errors.New("资产不存在或已删除")
	}
	total, count := 0, 0
	for _, id := range previewIDs {
		asset, ok := byID[id]
		if !ok || asset.DataURL != "" || !strings.HasPrefix(asset.MimeType, "image/") {
			continue
		}
		if count >= maxPlanningPreviews {
			break
		}
		asset.DataURL, err = h.imageInput(user, id)
		if err != nil {
			return nil, err
		}
		total += len(asset.DataURL)
		if total > 64<<20 {
			return nil, errors.New("本轮参考图片合计过大，请使用较小的参考图")
		}
		byID[id] = asset
		count++
	}
	for _, id := range unique {
		result = append(result, byID[id])
	}
	return result, nil
}
