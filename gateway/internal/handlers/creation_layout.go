package handlers

import (
	"encoding/json"
	"math"
	"net/http"

	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
)

type creativePosition struct {
	X float64 `json:"x"`
	Y float64 `json:"y"`
}

// Layout is presentation state: it never changes content revisions, reviews or jobs.
func (h *CreationHandler) UpdateProjectLayout(c *gin.Context) {
	h.mu.Lock()
	defer h.mu.Unlock()
	row, doc, ok := h.loadProject(c)
	if !ok {
		return
	}
	var req struct {
		Reset     bool `json:"reset"`
		Positions map[string]*struct {
			X *float64 `json:"x"`
			Y *float64 `json:"y"`
		} `json:"positions"`
	}
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 32<<10)
	if c.ShouldBindJSON(&req) != nil || len(req.Positions) > 32 || (!req.Reset && len(req.Positions) == 0) || (req.Reset && len(req.Positions) > 0) {
		creationError(c, 400, "无效的画布布局")
		return
	}
	allowed := map[string]bool{}
	for _, node := range doc.Plan.Nodes {
		allowed[node.ID] = true
	}
	for _, id := range doc.AssetIDs {
		allowed["asset:"+id] = true
	}
	positions := map[string]creativePosition{}
	if !req.Reset {
		_ = json.Unmarshal([]byte(row.CanvasLayout), &positions)
		if positions == nil {
			positions = map[string]creativePosition{}
		}
		for id := range positions {
			if !allowed[id] {
				delete(positions, id)
			}
		}
	}
	for id, p := range req.Positions {
		if !allowed[id] || p == nil || p.X == nil || p.Y == nil {
			creationError(c, 400, "节点不存在或坐标不完整")
			return
		}
		for _, value := range []float64{*p.X, *p.Y} {
			if math.IsNaN(value) || math.IsInf(value, 0) || value < 0 || value > 20000 {
				creationError(c, 400, "节点坐标超出画布范围")
				return
			}
		}
		positions[id] = creativePosition{X: *p.X, Y: *p.Y}
	}
	layout := creationJSON(positions)
	version := row.LayoutRevision + 1
	if err := h.db.Model(&models.CreationProject{}).Where("id = ? AND user_id = ?", row.ID, row.UserID).Updates(map[string]interface{}{"canvas_layout": layout, "layout_revision": version}).Error; err != nil {
		creationError(c, 500, "画布位置保存失败")
		return
	}
	c.JSON(200, gin.H{"canvas_layout": layout, "layout_revision": version})
}
