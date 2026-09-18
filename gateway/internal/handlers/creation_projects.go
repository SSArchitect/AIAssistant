package handlers

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"reflect"
	"strings"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"gorm.io/gorm"
)

type creationPlanner interface {
	PlanCreation(context.Context, bridge.CreationPlanningRequest) (*bridge.CreationPlanningResponse, error)
}
type creationProgressPlanner interface {
	PlanCreationWithProgress(context.Context, bridge.CreationPlanningRequest, func(bridge.CreationPlanningProgress)) (*bridge.CreationPlanningResponse, error)
}
type creativeNodeState struct {
	ApprovedBy       string            `json:"approved_by,omitempty"`
	Revision         int               `json:"revision"`
	ApprovedRevision int               `json:"approved_revision"`
	Candidates       []string          `json:"candidates"`
	SelectedAssetID  string            `json:"selected_asset_id"`
	RunID            string            `json:"run_id"`
	ApprovedInputs   map[string]string `json:"approved_inputs"`
}
type creativeDocument struct {
	Preferences *bridge.CreativePreferences      `json:"preferences,omitempty"`
	Automation  *creativeAutomation              `json:"automation,omitempty"`
	Planning    *bridge.CreativePlanningActivity `json:"planning,omitempty"`
	Plan        bridge.CreativePlan              `json:"plan"`
	States      map[string]creativeNodeState     `json:"states"`
	Messages    []bridge.CreativeMessage         `json:"messages"`
	AssetIDs    []string                         `json:"asset_ids"`
	TemplateID  string                           `json:"template_id"`
}

func projectDocument(row models.CreationProject) (creativeDocument, error) {
	var doc creativeDocument
	err := json.Unmarshal([]byte(row.Document), &doc)
	if doc.States == nil {
		doc.States = map[string]creativeNodeState{}
	}
	return doc, err
}
func emptyCreativeDocument() creativeDocument {
	return creativeDocument{Plan: bridge.CreativePlan{Nodes: []bridge.CreativeNode{}, Questions: []bridge.CreativeQuestion{}}, States: map[string]creativeNodeState{}, Messages: []bridge.CreativeMessage{}, AssetIDs: []string{}}
}
func creativeHash(value string) string {
	sum := sha256.Sum256([]byte(value))
	return hex.EncodeToString(sum[:])
}
func creativeNode(doc creativeDocument, id string) (bridge.CreativeNode, bool) {
	for _, node := range doc.Plan.Nodes {
		if node.ID == id {
			return node, true
		}
	}
	return bridge.CreativeNode{}, false
}
func creativeApproved(state creativeNodeState) bool {
	return state.Revision > 0 && state.ApprovedRevision == state.Revision
}

// Apply only the proposal. Approval and generated asset IDs are never model-owned.
func applyCreativePlan(doc creativeDocument, plan bridge.CreativePlan) creativeDocument {
	old := doc
	doc.Plan = plan
	doc.States = map[string]creativeNodeState{}
	changed := map[string]bool{}
	for _, node := range plan.Nodes {
		before, exists := creativeNode(old, node.ID)
		state := old.States[node.ID]
		// Suggested edits are UI choices, not changes to the approved artifact.
		comparison := node
		before.RevisionSuggestions = nil
		comparison.RevisionSuggestions = nil
		changed[node.ID] = !exists || !reflect.DeepEqual(before, comparison)
		for _, dep := range node.DependsOn {
			changed[node.ID] = changed[node.ID] || changed[dep]
		}
		if changed[node.ID] {
			state = creativeNodeState{Revision: state.Revision + 1, Candidates: []string{}, SelectedAssetID: node.AssetID}
		}
		doc.States[node.ID] = state
	}
	return doc
}
func invalidateCreativeChildren(doc *creativeDocument, id string) {
	changed := map[string]bool{id: true}
	for _, node := range doc.Plan.Nodes {
		if node.ID == id {
			continue
		}
		for _, dep := range node.DependsOn {
			if changed[dep] {
				previous := doc.States[node.ID]
				doc.States[node.ID] = creativeNodeState{Revision: previous.Revision + 1, Candidates: []string{}, SelectedAssetID: node.AssetID}
				changed[node.ID] = true
				break
			}
		}
	}
}
func validateCreativePlan(plan bridge.CreativePlan, allowed map[string]bool) error {
	if strings.TrimSpace(plan.Title) == "" || len([]rune(plan.Title)) > 100 || len(plan.Nodes) > 20 || len(plan.Questions) > 2 {
		return errors.New("无效的创作方案")
	}
	seen := map[string]bridge.CreativeNode{}
	for _, node := range plan.Nodes {
		if node.ID == "" || len(node.ID) > 80 || node.Title == "" {
			return errors.New("无效的产物节点")
		}
		if len(node.RevisionSuggestions) > 12 {
			return errors.New("修改方向过多")
		}
		for _, suggestion := range node.RevisionSuggestions {
			if strings.TrimSpace(suggestion.Label) == "" || len([]rune(suggestion.Label)) > 40 || strings.TrimSpace(suggestion.Instruction) == "" || len([]rune(suggestion.Instruction)) > 500 {
				return errors.New("无效的修改方向")
			}
		}
		if _, ok := seen[node.ID]; ok {
			return errors.New("节点重复")
		}
		deps := map[string]bool{}
		for _, id := range node.DependsOn {
			if _, ok := seen[id]; !ok || deps[id] {
				return errors.New("节点依赖无效")
			}
			deps[id] = true
		}
		if node.AssetID != "" && !allowed[node.AssetID] {
			return errors.New("方案引用了未提供的资产")
		}
		refs := map[string]bool{}
		for _, ref := range node.References {
			if (ref.AssetID == "") == (ref.NodeID == "") {
				return errors.New("参考来源无效")
			}
			if ref.AssetID != "" && !allowed[ref.AssetID] {
				return errors.New("参考资产不属于此项目")
			}
			if ref.NodeID != "" && (!deps[ref.NodeID] || seen[ref.NodeID].Kind != "image") {
				return errors.New("参考必须依赖图片节点")
			}
			key := ref.AssetID + ":" + ref.NodeID
			if refs[key] {
				return errors.New("重复参考图")
			}
			refs[key] = true
			if ref.Role != "identity" && ref.Role != "style" && ref.Role != "first_frame" && ref.Role != "reference" {
				return errors.New("未知参考用途")
			}
			if ref.Role == "first_frame" && (node.Kind != "video" || len(node.References) != 1) {
				return errors.New("首帧必须单独使用")
			}
		}
		switch node.Kind {
		case "text":
			if strings.TrimSpace(node.Content) == "" || node.AssetID != "" || len(node.References) > 0 {
				return errors.New("无效的文本产物")
			}
		case "image", "video":
			media := creationNode{ID: node.ID, Kind: node.Kind, Prompt: node.Prompt, Count: node.Count, AspectRatio: node.AspectRatio, DurationSeconds: node.DurationSeconds, CharacterStyle: node.CharacterStyle}
			for i := range node.References {
				media.AssetIDs = append(media.AssetIDs, fmt.Sprint(i))
			}
			if err := validateCreationGraph(creationGraph{Nodes: []creationNode{media}}, node.AssetID == ""); err != nil {
				return err
			}
			if node.Count > 3 {
				return errors.New("每个图片节点最多三个候选")
			}
			if node.Kind == "video" {
				script := false
				for _, id := range node.DependsOn {
					script = script || (seen[id].Kind == "text" && seen[id].Purpose == "script")
				}
				if !script || len(node.Storyboard) == 0 || string(node.Storyboard) == "null" || node.AssetID != "" {
					return errors.New("视频需要分镜脚本与结构化生成方案")
				}
			} else if node.AssetID != "" && len(node.References) > 0 {
				return errors.New("已有素材不能混用生成引用")
			}
		default:
			return errors.New("未知节点类型")
		}
		seen[node.ID] = node
	}
	return nil
}

func (h *CreationHandler) registerProjects(group *gin.RouterGroup) {
	group.GET("/projects", h.Projects)
	group.POST("/projects", h.CreateProject)
	group.GET("/projects/:id", h.Project)
	group.PATCH("/projects/:id/layout", h.UpdateProjectLayout)
	group.POST("/projects/:id/messages", h.ProjectMessage)
	group.POST("/projects/:id/review", h.ReviewProject)
	group.POST("/projects/:id/generate", h.GenerateProjectNode)
	group.POST("/projects/:id/template", h.ProjectTemplate)
	group.GET("/projects/:id/versions", h.ProjectVersions)
	group.POST("/projects/:id/automatic", h.StartAutomaticCreation)
	group.POST("/projects/:id/automatic/stop", h.StopAutomaticCreation)
}
func (h *CreationHandler) loadProject(c *gin.Context) (models.CreationProject, creativeDocument, bool) {
	var row models.CreationProject
	if h.db.Where("id = ? AND user_id = ?", c.Param("id"), c.GetString("creation_user_id")).First(&row).Error != nil {
		creationError(c, 404, "创作项目不存在")
		return row, creativeDocument{}, false
	}
	doc, err := projectDocument(row)
	if err != nil {
		creationError(c, 500, "无法读取项目内容")
		return row, doc, false
	}
	return row, doc, true
}
func (h *CreationHandler) updateProject(row *models.CreationProject, doc creativeDocument, saveVersion bool) error {
	expected := row.Revision
	row.Revision++
	row.Document = creationJSON(doc)
	row.UpdatedAt = time.Now()
	return h.db.Transaction(func(tx *gorm.DB) error {
		result := tx.Model(&models.CreationProject{}).Where("id = ? AND user_id = ? AND revision = ?", row.ID, row.UserID, expected).Updates(map[string]interface{}{"name": row.Name, "revision": row.Revision, "document": row.Document, "planning": row.Planning, "planning_request_id": row.PlanningRequestID, "error": row.Error, "automatic_status": row.AutomaticStatus, "automatic_request_id": row.AutomaticRequestID, "updated_at": row.UpdatedAt})
		if result.Error != nil {
			return result.Error
		}
		if result.RowsAffected != 1 {
			return errors.New("项目已更新，请刷新后重试")
		}
		if saveVersion {
			return tx.Create(&models.CreationProjectVersion{ID: uuid.NewString(), UserID: row.UserID, ProjectID: row.ID, Revision: row.Revision, Plan: creationJSON(doc)}).Error
		}
		return nil
	})
}
func checkProjectRevision(c *gin.Context, row models.CreationProject, revision int) bool {
	if row.Planning || automaticActive(row.AutomaticStatus) {
		creationError(c, 409, "创作助手正在处理，请稍候或先停止一键生成")
		return false
	}
	if row.Revision != revision {
		creationError(c, 409, "项目已更新，请刷新后重试")
		return false
	}
	return true
}
func (h *CreationHandler) Projects(c *gin.Context) {
	var rows []models.CreationProject
	if err := h.db.Select("id", "name", "revision", "planning", "automatic_status", "error", "created_at", "updated_at").Where("user_id = ?", c.GetString("creation_user_id")).Order("updated_at DESC").Find(&rows).Error; err != nil {
		creationError(c, 500, "无法读取项目")
		return
	}
	c.JSON(200, gin.H{"projects": rows})
}
func (h *CreationHandler) Project(c *gin.Context) {
	row, _, ok := h.loadProject(c)
	if ok {
		c.JSON(200, gin.H{"project": row})
	}
}
func (h *CreationHandler) CreateProject(c *gin.Context) {
	var req struct {
		TemplateID string `json:"template_id"`
	}
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 16<<10)
	if c.ShouldBindJSON(&req) != nil {
		creationError(c, 400, "无效的项目请求")
		return
	}
	doc := emptyCreativeDocument()
	doc.TemplateID = req.TemplateID
	row := models.CreationProject{ID: uuid.NewString(), UserID: c.GetString("creation_user_id"), Name: "新的创作", Revision: 1}
	if req.TemplateID != "" && !strings.HasPrefix(req.TemplateID, "builtin-") {
		var template models.CreationDefinition
		if h.db.Where("id = ? AND user_id = ? AND kind LIKE ?", req.TemplateID, row.UserID, "%template").First(&template).Error != nil {
			creationError(c, 404, "模板不存在")
			return
		}
	}
	row.Document = creationJSON(doc)
	if err := h.db.Create(&row).Error; err != nil {
		creationError(c, 500, "创建项目失败")
		return
	}
	c.JSON(201, gin.H{"project": row})
}
func (h *CreationHandler) planningAssets(user string, ids []string) ([]bridge.PlanningAsset, error) {
	if len(ids) > 12 {
		return nil, errors.New("每个项目最多提供12个资产")
	}
	result := []bridge.PlanningAsset{}
	total := 0
	for _, id := range ids {
		item, err := h.assetItem(user, id)
		if err != nil {
			return nil, errors.New("资产不存在或已删除")
		}
		asset := bridge.PlanningAsset{ID: id, Name: item.Name, MimeType: item.MimeType}
		if strings.HasPrefix(item.MimeType, "image/") {
			asset.DataURL, err = h.imageInput(user, id)
			if err != nil {
				return nil, err
			}
			total += len(asset.DataURL)
			if total > 64<<20 {
				return nil, errors.New("本次图片素材合计过大，请使用较小的参考图")
			}
		}
		result = append(result, asset)
	}
	return result, nil
}
func (h *CreationHandler) planningTemplates(user string) ([]map[string]interface{}, error) {
	result := []map[string]interface{}{
		{"id": "builtin-story", "name": "角色短片", "kind": "workflow_template", "description": "简报→主视觉候选与分镜脚本→参考图审阅→多图参考视频；缺少场景时补主视觉"},
		{"id": "builtin-refine", "name": "原图→二次创作", "kind": "workflow_template", "description": "先生成原图，再用已确认的原图创作新图"},
		{"id": "builtin-product", "name": "产品摄影", "kind": "image_template", "description": "柔和棚拍光线与简洁背景"},
		{"id": "builtin-anime", "name": "原角色动漫化", "description": "保留输入图人物身份的转换模板；不用于新角色设计、场景或仅参考画风", "kind": "image_template", "character_style": "anime"},
		{"id": "builtin-chibi", "name": "原角色转Q版", "description": "保留输入图人物身份的转换模板；不用于新角色设计、场景或仅参考画风", "kind": "image_template", "character_style": "chibi"},
		{"id": "builtin-cinema", "name": "电影感运镜", "kind": "video_template", "description": "连贯动作、克制运镜、清楚的空间关系"},
	}
	var templates []models.CreationDefinition
	if err := h.db.Where("user_id = ? AND kind != ?", user, "workflow").Order("updated_at DESC").Limit(34).Find(&templates).Error; err != nil {
		return nil, err
	}
	for _, t := range templates {
		result = append(result, map[string]interface{}{"id": t.ID, "name": t.Name, "kind": t.Kind, "definition": json.RawMessage(t.Definition)})
	}
	return result, nil
}

func (h *CreationHandler) ProjectMessage(c *gin.Context) {
	var req struct {
		Preferences *bridge.CreativePreferences `json:"preferences"`
		Revision    int                         `json:"revision"`
		Message     string                      `json:"message"`
		NodeID      string                      `json:"node_id"`
		AssetIDs    []string                    `json:"asset_ids"`
		RequestID   string                      `json:"request_id"`
	}
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 32<<10)
	if c.ShouldBindJSON(&req) != nil || strings.TrimSpace(req.Message) == "" || len([]rune(req.Message)) > 8000 || req.RequestID == "" || len(req.RequestID) > 100 {
		creationError(c, 400, "请输入不超过8000字的创作想法")
		return
	}
	if p := req.Preferences; p != nil {
		if (p.OutputKind != "" && p.OutputKind != "image" && p.OutputKind != "video") || (p.AspectRatio != "" && p.AspectRatio != "1:1" && p.AspectRatio != "16:9" && p.AspectRatio != "9:16") {
			creationError(c, 400, "请选择支持的创作目标和画面比例")
			return
		}
	}
	planner, ok := h.generator.(creationPlanner)
	if !ok {
		creationError(c, 503, "创作助手尚未连接")
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	row, doc, ok := h.loadProject(c)
	if !ok {
		return
	}
	if row.PlanningRequestID == req.RequestID {
		c.JSON(200, gin.H{"project": row})
		return
	}
	if !checkProjectRevision(c, row, req.Revision) {
		return
	}
	if req.NodeID != "" {
		if _, exists := creativeNode(doc, req.NodeID); !exists {
			creationError(c, 400, "引用的节点不存在")
			return
		}
	}
	merged := append([]string{}, doc.AssetIDs...)
	for _, id := range req.AssetIDs {
		found := false
		for _, existing := range merged {
			found = found || existing == id
		}
		if !found {
			merged = append(merged, id)
		}
	}
	// Include selected generated candidates so the director can see the current visual.
	planningIDs := append([]string{}, merged...)
	for _, node := range doc.Plan.Nodes {
		selected := doc.States[node.ID].SelectedAssetID
		found := selected == ""
		for _, id := range planningIDs {
			found = found || id == selected
		}
		if !found {
			planningIDs = append(planningIDs, selected)
		}
	}
	assets, err := h.planningAssets(row.UserID, planningIDs)
	if err != nil {
		creationError(c, 400, err)
		return
	}
	templates, err := h.planningTemplates(row.UserID)
	if err != nil {
		creationError(c, 500, "无法读取模板")
		return
	}
	doc.AssetIDs = merged
	if req.Preferences != nil {
		doc.Preferences = req.Preferences
	}
	doc.Messages = append(doc.Messages, bridge.CreativeMessage{Role: "user", Content: strings.TrimSpace(req.Message), NodeID: req.NodeID, AssetIDs: req.AssetIDs, Preferences: doc.Preferences})
	if len(doc.Messages) > 80 {
		doc.Messages = append(doc.Messages[:2:2], doc.Messages[len(doc.Messages)-78:]...)
	}
	row.Planning = true
	doc.Planning = &bridge.CreativePlanningActivity{ID: req.RequestID, Status: "running", StartedAt: time.Now(), Steps: []bridge.CreativePlanningStep{{Stage: "received", Message: "已收到创作想法，正在连接创作助手"}}}
	row.PlanningRequestID = req.RequestID
	row.Error = ""
	if err = h.updateProject(&row, doc, false); err != nil {
		creationError(c, 409, err)
		return
	}
	planningReq := bridge.CreationPlanningRequest{Preferences: doc.Preferences, ProjectID: row.ID, UserID: row.UserID, Messages: append([]bridge.CreativeMessage{}, doc.Messages...), CurrentPlan: doc.Plan, Assets: assets, Templates: templates, PreferredTemplateID: doc.TemplateID}
	for i := range planningReq.Messages {
		planningReq.Messages[i].Planning = nil
	}
	planningReq.NodeContext = map[string]map[string]interface{}{}
	for id, state := range doc.States {
		planningReq.NodeContext[id] = map[string]interface{}{"revision": state.Revision, "approved": creativeApproved(state), "selected_asset_id": state.SelectedAssetID, "candidate_count": len(state.Candidates)}
	}
	go h.planProject(planner, row, planningReq)
	c.JSON(202, gin.H{"project": row})
}
func (h *CreationHandler) planProject(planner creationPlanner, submitted models.CreationProject, request bridge.CreationPlanningRequest) {
	// The Agent enforces an idle timeout and a 15-minute absolute ceiling.
	ctx, cancel := context.WithTimeout(context.Background(), 915*time.Second)
	defer cancel()
	var response *bridge.CreationPlanningResponse
	var err error
	if streaming, ok := planner.(creationProgressPlanner); ok {
		response, err = streaming.PlanCreationWithProgress(ctx, request, func(event bridge.CreationPlanningProgress) { h.recordPlanningProgress(submitted, event) })
	} else {
		response, err = planner.PlanCreation(ctx, request)
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	var row models.CreationProject
	if h.db.Where("id = ? AND user_id = ? AND planning_request_id = ? AND planning = ?", submitted.ID, submitted.UserID, submitted.PlanningRequestID, true).First(&row).Error != nil {
		return
	}
	doc, readErr := projectDocument(row)
	if readErr != nil {
		return
	}
	row.Planning = false
	allowed := map[string]bool{}
	for _, asset := range request.Assets {
		if strings.HasPrefix(asset.MimeType, "image/") {
			allowed[asset.ID] = true
		}
	}
	if err == nil && response != nil {
		err = validateCreativePlan(response.Plan, allowed)
	}
	if err != nil || response == nil {
		row.Error = "创作助手未能完成方案。原有内容已保留，请重试；也可检查默认对话模型配置。"
		var planningErr *bridge.CreationPlanningError
		if errors.As(err, &planningErr) {
			row.Error = planningErr.Message
		}
		finishPlanningActivity(&doc, "failed", row.Error)
		doc.Messages = append(doc.Messages, bridge.CreativeMessage{Role: "assistant", Content: row.Error, Planning: doc.Planning})
		doc.Planning = nil
		_ = h.updateProject(&row, doc, false)
		return
	}
	doc = applyCreativePlan(doc, response.Plan)
	finishPlanningActivity(&doc, "completed", "方案已整理完成，请查看回复与画布")
	doc.Messages = append(doc.Messages, bridge.CreativeMessage{Role: "assistant", Content: response.Reply, Planning: doc.Planning})
	doc.Planning = nil
	row.Name = response.Plan.Title
	row.Error = ""
	_ = h.updateProject(&row, doc, true)
	_ = persistTokenUsageRecordDB(h.db, row.ID, row.UserID, 0, "creation_director", time.Now(), &bridge.ChatResponse{ModelUsed: response.ModelUsed, TokensUsed: response.TokensUsed, RunID: response.RunID, Runtime: "self"})
}

func creativeDependenciesReady(doc creativeDocument, node bridge.CreativeNode) error {
	for _, id := range node.DependsOn {
		if !creativeApproved(doc.States[id]) {
			return errors.New("请先审阅并确认上游内容")
		}
	}
	return nil
}
func (h *CreationHandler) creativeInputs(user string, doc creativeDocument, node bridge.CreativeNode) ([]string, map[string]string, error) {
	ids := []string{}
	if node.AssetID != "" {
		ids = append(ids, node.AssetID)
	} else if node.Kind == "image" && doc.States[node.ID].SelectedAssetID != "" {
		ids = append(ids, doc.States[node.ID].SelectedAssetID)
	}
	if node.Kind == "video" || node.Kind == "image" && len(ids) == 0 {
		for _, ref := range node.References {
			id := ref.AssetID
			if ref.NodeID != "" {
				id = doc.States[ref.NodeID].SelectedAssetID
			}
			if id == "" {
				return nil, nil, errors.New("请先为参考节点选择一张图片")
			}
			ids = append(ids, id)
		}
	}
	hashes := map[string]string{}
	for _, id := range ids {
		data, err := h.imageInput(user, id)
		if err != nil {
			return nil, nil, err
		}
		hash := creativeHash(data)
		for _, existing := range hashes {
			if existing == hash {
				return nil, nil, errors.New("同一图片不能重复作为参考，请调整引用")
			}
		}
		hashes[id] = hash
	}
	return ids, hashes, nil
}
func (h *CreationHandler) ReviewProject(c *gin.Context) {
	var req struct {
		Revision int    `json:"revision"`
		NodeID   string `json:"node_id"`
		AssetID  string `json:"asset_id"`
	}
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 16<<10)
	if c.ShouldBindJSON(&req) != nil {
		creationError(c, 400, "无效的审阅操作")
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	row, doc, ok := h.loadProject(c)
	if !ok || !checkProjectRevision(c, row, req.Revision) {
		return
	}
	node, ok := creativeNode(doc, req.NodeID)
	if !ok {
		creationError(c, 404, "节点不存在")
		return
	}
	if err := creativeDependenciesReady(doc, node); err != nil {
		creationError(c, 409, err)
		return
	}
	state := doc.States[node.ID]
	if node.Kind == "image" {
		if req.AssetID == "" {
			req.AssetID = state.SelectedAssetID
		}
		valid := req.AssetID != "" && req.AssetID == node.AssetID
		for _, id := range state.Candidates {
			valid = valid || id == req.AssetID
		}
		if !valid {
			creationError(c, 400, "请选择此节点的一个图片候选")
			return
		}
		if state.SelectedAssetID != req.AssetID {
			state.SelectedAssetID = req.AssetID
			state.Revision++
			invalidateCreativeChildren(&doc, node.ID)
		}
		doc.States[node.ID] = state
	}
	_, hashes, err := h.creativeInputs(row.UserID, doc, node)
	if err != nil {
		creationError(c, 400, err)
		return
	}
	if !reflect.DeepEqual(state.ApprovedInputs, hashes) && state.ApprovedRevision > 0 {
		invalidateCreativeChildren(&doc, node.ID)
	}
	state.ApprovedRevision = state.Revision
	state.ApprovedBy = "user"
	state.ApprovedInputs = hashes
	doc.States[node.ID] = state
	if err = h.updateProject(&row, doc, true); err != nil {
		creationError(c, 409, err)
		return
	}
	c.JSON(200, gin.H{"project": row})
}
func (h *CreationHandler) GenerateProjectNode(c *gin.Context) {
	var req struct {
		Revision  int    `json:"revision"`
		NodeID    string `json:"node_id"`
		RequestID string `json:"request_id"`
	}
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 16<<10)
	if c.ShouldBindJSON(&req) != nil || req.RequestID == "" || len(req.RequestID) > 100 {
		creationError(c, 400, "无效的生成请求")
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	row, doc, ok := h.loadProject(c)
	if !ok {
		return
	}
	var existing models.CreationRun
	if h.db.Where("user_id = ? AND project_id = ? AND request_id = ?", row.UserID, row.ID, req.RequestID).First(&existing).Error == nil {
		if existing.ProjectNodeID != req.NodeID {
			creationError(c, 409, "生成请求标识已使用")
			return
		}
		c.JSON(200, gin.H{"project": row, "run": existing})
		return
	}
	if !checkProjectRevision(c, row, req.Revision) {
		return
	}
	submission, err := h.prepareProjectRun(row, doc, req.NodeID, req.RequestID)
	if err != nil {
		failure := err.(*creationSubmissionError)
		creationError(c, failure.status, failure.message)
		return
	}
	go h.execute(submission.run, submission.graph, submission.progress)
	c.JSON(202, gin.H{"project": submission.project, "run": submission.run})
}

type creationSubmissionError struct {
	status  int
	message string
}

func (e *creationSubmissionError) Error() string { return e.message }

type creationSubmission struct {
	project  models.CreationProject
	run      models.CreationRun
	graph    creationGraph
	progress []creationProgress
}

// Caller holds h.mu. Manual and automatic generation share every review, input-hash,
// concurrency, frozen-snapshot and transactional submission check.
func (h *CreationHandler) prepareProjectRun(row models.CreationProject, doc creativeDocument, nodeID, requestID string) (*creationSubmission, error) {
	node, ok := creativeNode(doc, nodeID)
	if !ok || node.Kind == "text" || node.AssetID != "" {
		return nil, &creationSubmissionError{400, fmt.Sprint("此节点不能生成媒体")}
	}
	if len(doc.Plan.Questions) > 0 {
		return nil, &creationSubmissionError{409, fmt.Sprint("请先回答创作助手的问题，确定方案后再生成")}
	}
	if err := creativeDependenciesReady(doc, node); err != nil {
		return nil, &creationSubmissionError{409, fmt.Sprint(err)}
	}
	if node.Kind == "video" && !creativeApproved(doc.States[node.ID]) {
		return nil, &creationSubmissionError{409, fmt.Sprint("请先确认脚本与参考关系，再提交视频")}
	}
	// Check only this node and its ancestors; independent branches do not block it.
	required := map[string]bool{node.ID: true}
	for i := len(doc.Plan.Nodes) - 1; i >= 0; i-- {
		current := doc.Plan.Nodes[i]
		if required[current.ID] {
			for _, dep := range current.DependsOn {
				required[dep] = true
			}
		}
	}
	for _, check := range doc.Plan.Nodes {
		if !required[check.ID] || !creativeApproved(doc.States[check.ID]) {
			continue
		}
		_, hashes, err := h.creativeInputs(row.UserID, doc, check)
		if err != nil || !reflect.DeepEqual(hashes, doc.States[check.ID].ApprovedInputs) {
			return nil, &creationSubmissionError{409, fmt.Sprint("参考资产已变更或删除，请重新审阅确认")}
		}
	}
	// Generate uses references, not the previously selected output when regenerating an image.
	inputDoc := doc
	inputDoc.States = map[string]creativeNodeState{}
	for id, state := range doc.States {
		inputDoc.States[id] = state
	}
	sourceState := inputDoc.States[node.ID]
	sourceState.SelectedAssetID = ""
	inputDoc.States[node.ID] = sourceState
	ids, hashes, err := h.creativeInputs(row.UserID, inputDoc, node)
	if err != nil {
		return nil, &creationSubmissionError{400, fmt.Sprint(err)}
	}
	var active int64
	if err = h.db.Model(&models.CreationRun{}).Where("user_id = ? AND status IN ?", row.UserID, []string{"queued", "running", "stopping"}).Count(&active).Error; err != nil {
		return nil, &creationSubmissionError{500, fmt.Sprint("无法检查生成任务")}
	}
	if active > 0 || h.automaticBusy(row.UserID, row.ID) {
		return nil, &creationSubmissionError{409, fmt.Sprint("已有生成任务在运行，请等待完成或停止")}
	}
	mode := ""
	if node.Kind == "video" {
		mode = "text_to_video"
		if len(node.References) > 0 {
			mode = "reference_to_video"
			if node.References[0].Role == "first_frame" {
				mode = "image_to_video"
			}
		}
	}
	imageReferences := []bridge.ImageReferenceContext{}
	if node.Kind == "image" {
		for _, ref := range node.References {
			imageReferences = append(imageReferences, bridge.ImageReferenceContext{Role: ref.Role, Note: ref.Note})
		}
	}
	graph := creationGraph{Nodes: []creationNode{{ID: node.ID, Kind: node.Kind, Name: node.Title, Prompt: node.Prompt, Count: node.Count, AspectRatio: node.AspectRatio, DurationSeconds: node.DurationSeconds, CharacterStyle: node.CharacterStyle, Inputs: []string{}, AssetIDs: ids, ImageReferences: imageReferences, InputHashes: hashes, VideoMode: mode, Storyboard: node.Storyboard}}}
	if err = validateCreationGraph(graph, true); err != nil {
		return nil, &creationSubmissionError{400, fmt.Sprint(err)}
	}
	state := doc.States[node.ID]
	run := models.CreationRun{ID: uuid.NewString(), UserID: row.UserID, Name: row.Name + " · " + node.Title, Status: "queued", Definition: creationJSON(graph), ProjectID: row.ID, ProjectRevision: row.Revision, ProjectNodeID: node.ID, NodeRevision: state.Revision, RequestID: requestID, Snapshot: creationJSON(doc)}
	progress := []creationProgress{{NodeID: node.ID, Status: "pending", AssetIDs: []string{}}}
	run.Progress = creationJSON(progress)
	state.RunID = run.ID
	doc.States[node.ID] = state
	err = h.db.Transaction(func(tx *gorm.DB) error {
		if err := tx.Create(&run).Error; err != nil {
			return err
		}
		result := tx.Model(&models.CreationProject{}).Where("id = ? AND revision = ?", row.ID, row.Revision).Updates(map[string]interface{}{"revision": row.Revision + 1, "document": creationJSON(doc), "updated_at": time.Now()})
		if result.Error != nil {
			return result.Error
		}
		if result.RowsAffected != 1 {
			return errors.New("项目已更新")
		}
		return nil
	})
	if err != nil {
		return nil, &creationSubmissionError{500, fmt.Sprint("提交生成失败")}
	}
	row.Revision++
	row.Document = creationJSON(doc)
	return &creationSubmission{row, run, graph, progress}, nil
}

func (h *CreationHandler) finishProjectRun(run models.CreationRun, progress []creationProgress) {
	if run.ProjectID == "" {
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	var row models.CreationProject
	if h.db.Where("id = ? AND user_id = ?", run.ProjectID, run.UserID).First(&row).Error != nil {
		return
	}
	doc, err := projectDocument(row)
	if err != nil {
		return
	}
	state, ok := doc.States[run.ProjectNodeID]
	if !ok || state.Revision != run.NodeRevision || state.RunID != run.ID {
		return
	} // Changed plans never adopt an older render.
	changed := false
	for _, p := range progress {
		for _, id := range p.AssetIDs {
			state.Candidates = append(state.Candidates, id)
			changed = true
		}
	}
	if !changed {
		return
	}
	state.SelectedAssetID = ""
	if node, _ := creativeNode(doc, run.ProjectNodeID); node.Kind != "video" {
		state.ApprovedRevision = 0
		state.ApprovedInputs = nil
		state.ApprovedBy = ""
	}
	if len(state.Candidates) == 1 {
		state.SelectedAssetID = state.Candidates[0]
	}
	doc.States[run.ProjectNodeID] = state
	invalidateCreativeChildren(&doc, run.ProjectNodeID)
	_ = h.updateProject(&row, doc, false)
}
func (h *CreationHandler) ProjectVersions(c *gin.Context) {
	row, _, ok := h.loadProject(c)
	if !ok {
		return
	}
	var versions []models.CreationProjectVersion
	if err := h.db.Where("project_id = ? AND user_id = ?", row.ID, row.UserID).Order("revision DESC").Limit(30).Find(&versions).Error; err != nil {
		creationError(c, 500, "无法读取历史方案")
		return
	}
	c.JSON(200, gin.H{"versions": versions})
}
func (h *CreationHandler) ProjectTemplate(c *gin.Context) {
	h.mu.Lock()
	defer h.mu.Unlock()
	row, doc, ok := h.loadProject(c)
	if !ok {
		return
	}
	if row.Planning || len(doc.Plan.Nodes) == 0 {
		creationError(c, 409, "请等待创作方案完成后保存模板")
		return
	}
	plan := doc.Plan
	for i := range plan.Nodes {
		node := &plan.Nodes[i]
		node.AssetID = ""
		refs := []bridge.CreativeReference{}
		for _, ref := range node.References {
			if ref.NodeID != "" {
				refs = append(refs, ref)
			} else {
				node.Content += "\n复用时补充素材：" + ref.Note
			}
		}
		node.References = refs
	}
	plan.Questions = []bridge.CreativeQuestion{}
	definition := models.CreationDefinition{ID: uuid.NewString(), UserID: row.UserID, Kind: "project_template", Name: row.Name + " · 创作模板", Definition: creationJSON(plan)}
	if err := h.db.Create(&definition).Error; err != nil {
		creationError(c, 500, "保存模板失败")
		return
	}
	c.JSON(201, gin.H{"definition": definition})
}

func finishPlanningActivity(doc *creativeDocument, status, message string) {
	if doc.Planning == nil {
		return
	}
	doc.Planning.Status = status
	doc.Planning.ElapsedMS = time.Since(doc.Planning.StartedAt).Milliseconds()
	doc.Planning.Steps = append(doc.Planning.Steps, bridge.CreativePlanningStep{Stage: status, Message: message, ElapsedMS: doc.Planning.ElapsedMS})
}

func (h *CreationHandler) recordPlanningProgress(submitted models.CreationProject, event bridge.CreationPlanningProgress) {
	if event.Stage == "" || len(event.Stage) > 40 || event.Message == "" || len([]rune(event.Message)) > 300 {
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	var row models.CreationProject
	if h.db.Where("id = ? AND user_id = ? AND planning_request_id = ? AND planning = ?", submitted.ID, submitted.UserID, submitted.PlanningRequestID, true).First(&row).Error != nil {
		return
	}
	doc, err := projectDocument(row)
	if err != nil || doc.Planning == nil {
		return
	}
	activity := doc.Planning
	elapsed := time.Since(activity.StartedAt).Milliseconds()
	if len(activity.Steps) > 0 && activity.Steps[len(activity.Steps)-1].Stage == event.Stage {
		if elapsed-activity.ElapsedMS < 900 {
			return
		}
	} else if len(activity.Steps) < 24 {
		activity.Steps = append(activity.Steps, bridge.CreativePlanningStep{Stage: event.Stage, Message: event.Message, ElapsedMS: elapsed})
	}
	activity.ElapsedMS = elapsed
	if event.OutputChars > 0 {
		activity.OutputChars = event.OutputChars
	}
	_ = h.updateProject(&row, doc, false)
}
