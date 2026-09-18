package handlers

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"reflect"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
)

type creationReviewer interface {
	ReviewCreation(context.Context, bridge.CreationReviewRequest) (*bridge.CreationReviewResponse, error)
}
type creativeAutomation struct {
	bridge.CreativePlanningActivity
	NodeID        string   `json:"node_id,omitempty"`
	LockedNodeIDs []string `json:"locked_node_ids"`
}

func automaticActive(status string) bool { return status == "running" || status == "stopping" }
func (h *CreationHandler) automaticBusy(user, except string) bool {
	var count int64
	err := h.db.Model(&models.CreationProject{}).Where("user_id = ? AND id != ? AND automatic_status IN ?", user, except, []string{"running", "stopping"}).Count(&count).Error
	return err != nil || count > 0
}
func lockedCreativeNodes(doc creativeDocument) []string {
	locked := map[string]bool{}
	for id, state := range doc.States {
		if creativeApproved(state) {
			locked[id] = true
		}
	}
	for i := len(doc.Plan.Nodes) - 1; i >= 0; i-- {
		n := doc.Plan.Nodes[i]
		if locked[n.ID] {
			for _, dep := range n.DependsOn {
				locked[dep] = true
			}
		}
	}
	result := []string{}
	for _, n := range doc.Plan.Nodes {
		if locked[n.ID] {
			result = append(result, n.ID)
		}
	}
	return result
}
func protectAutomaticPlan(doc creativeDocument, plan bridge.CreativePlan) error {
	proposed := doc
	proposed.Plan = plan
	for _, id := range doc.Automation.LockedNodeIDs {
		before, _ := creativeNode(doc, id)
		after, ok := creativeNode(proposed, id)
		if !ok || !reflect.DeepEqual(before, after) {
			return errors.New("自动方案试图改动已确认内容，已停止并保留原方案")
		}
	}
	return nil
}
func (h *CreationHandler) StartAutomaticCreation(c *gin.Context) {
	var req struct {
		Revision  int    `json:"revision"`
		RequestID string `json:"request_id"`
	}
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 16<<10)
	if c.ShouldBindJSON(&req) != nil || req.RequestID == "" || len(req.RequestID) > 100 {
		creationError(c, 400, "无效的一键生成请求")
		return
	}
	if _, ok := h.generator.(creationReviewer); !ok {
		creationError(c, 503, "自动审阅尚未连接")
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	row, doc, ok := h.loadProject(c)
	if !ok {
		return
	}
	if row.AutomaticRequestID == req.RequestID {
		c.JSON(200, gin.H{"project": row})
		return
	}
	for _, message := range doc.Messages {
		if message.Planning != nil && message.Planning.ID == req.RequestID {
			c.JSON(200, gin.H{"project": row})
			return
		}
	}
	if !checkProjectRevision(c, row, req.Revision) {
		return
	}
	if len(doc.Plan.Nodes) == 0 {
		creationError(c, 409, "先描述创作想法，形成画布后即可一键生成")
		return
	}
	var active int64
	if err := h.db.Model(&models.CreationRun{}).Where("user_id = ? AND status IN ?", row.UserID, []string{"queued", "running", "stopping"}).Count(&active).Error; err != nil {
		creationError(c, 500, "无法检查任务状态")
		return
	}
	if active > 0 || h.automaticBusy(row.UserID, row.ID) {
		creationError(c, 409, "已有生成任务正在运行，请等待完成或停止")
		return
	}
	row.AutomaticStatus = "running"
	row.AutomaticRequestID = req.RequestID
	row.Error = ""
	doc.Automation = &creativeAutomation{CreativePlanningActivity: bridge.CreativePlanningActivity{ID: req.RequestID, Status: "running", StartedAt: time.Now(), Steps: []bridge.CreativePlanningStep{}}, LockedNodeIDs: lockedCreativeNodes(doc)}
	doc.Messages = append(doc.Messages, bridge.CreativeMessage{Role: "user", Content: "一键生成：保留已确认内容，由创作助手确定其余节点并继续生成。"})
	automaticStep(&doc, "start", "已接手后续创作；保留已确认内容与已有产物", "")
	if err := h.updateProject(&row, doc, false); err != nil {
		creationError(c, 409, err)
		return
	}
	ctx, cancel := context.WithCancel(context.Background())
	if h.automaticCancels == nil {
		h.automaticCancels = map[string]context.CancelFunc{}
	}
	h.automaticCancels[req.RequestID] = cancel
	go h.executeAutomatic(ctx, row.ID, req.RequestID)
	c.JSON(202, gin.H{"project": row})
}
func automaticStep(doc *creativeDocument, stage, message, node string) {
	a := doc.Automation
	a.NodeID = node
	a.ElapsedMS = time.Since(a.StartedAt).Milliseconds()
	if len(a.Steps) < 100 {
		a.Steps = append(a.Steps, bridge.CreativePlanningStep{Stage: stage, Message: message, ElapsedMS: a.ElapsedMS})
	}
}
func (h *CreationHandler) StopAutomaticCreation(c *gin.Context) {
	h.mu.Lock()
	defer h.mu.Unlock()
	row, doc, ok := h.loadProject(c)
	if !ok {
		return
	}
	if !automaticActive(row.AutomaticStatus) {
		c.JSON(200, gin.H{"project": row})
		return
	}
	row.AutomaticStatus = "stopping"
	doc.Automation.Status = "stopping"
	automaticStep(&doc, "stopping", "正在停止；已提交的媒体会完成并保存，不再启动后续节点", doc.Automation.NodeID)
	if err := h.updateProject(&row, doc, false); err != nil {
		creationError(c, 409, err)
		return
	}
	if err := h.db.Model(&models.CreationRun{}).Where("project_id = ? AND user_id = ? AND status IN ?", row.ID, row.UserID, []string{"queued", "running"}).Updates(map[string]interface{}{"status": "stopping", "updated_at": time.Now()}).Error; err != nil {
		creationError(c, 500, "停止生成失败，请重试")
		return
	}
	if cancel := h.automaticCancels[row.AutomaticRequestID]; cancel != nil {
		cancel()
	}
	c.JSON(200, gin.H{"project": row})
}
func (h *CreationHandler) finishAutomatic(id, request, status, message string) {
	h.mu.Lock()
	defer h.mu.Unlock()
	var row models.CreationProject
	if h.db.Where("id = ? AND automatic_request_id = ?", id, request).First(&row).Error != nil || !automaticActive(row.AutomaticStatus) {
		return
	}
	doc, err := projectDocument(row)
	if err != nil || doc.Automation == nil {
		return
	}
	if row.AutomaticStatus == "stopping" {
		status = "cancelled"
		message = "一键生成已停止，已完成的产物和确认结果均已保留。"
	}
	row.AutomaticStatus = status
	doc.Automation.Status = status
	automaticStep(&doc, status, message, doc.Automation.NodeID)
	activity := doc.Automation.CreativePlanningActivity
	doc.Messages = append(doc.Messages, bridge.CreativeMessage{Role: "assistant", Content: message, Planning: &activity})
	_ = h.updateProject(&row, doc, true)
}
func (h *CreationHandler) executeAutomatic(ctx context.Context, id, request string) {
	defer func() {
		if recover() != nil {
			h.finishAutomatic(id, request, "failed", "自动创作遇到异常，已确认内容与产物保留，可继续或手动处理。")
		}
		h.mu.Lock()
		if cancel := h.automaticCancels[request]; cancel != nil {
			cancel()
			delete(h.automaticCancels, request)
		}
		h.mu.Unlock()
	}()
	for step := 0; step < 80; step++ {
		done, err := h.advanceAutomatic(ctx, id, request)
		if err != nil {
			h.finishAutomatic(id, request, "failed", err.Error())
			return
		}
		if done {
			h.finishAutomatic(id, request, "completed", "一键生成已完成，所有产物已归入画布和资产。")
			return
		}
	}
	h.finishAutomatic(id, request, "failed", "自动创作达到本轮步骤上限，已完成内容保留，请检查画布后继续。")
}
func (h *CreationHandler) automaticRequest(row models.CreationProject, doc creativeDocument, node bridge.CreativeNode, candidates []string) (bridge.CreationPlanningRequest, error) {
	ids := []string{}
	seen := map[string]bool{}
	add := func(id string) {
		if id != "" && !seen[id] {
			seen[id] = true
			ids = append(ids, id)
		}
	}
	if node.ID == "" {
		for _, id := range doc.AssetIDs {
			add(id)
		}
		for _, n := range doc.Plan.Nodes {
			add(doc.States[n.ID].SelectedAssetID)
		}
	}
	for _, ref := range node.References {
		id := ref.AssetID
		if ref.NodeID != "" {
			id = doc.States[ref.NodeID].SelectedAssetID
		}
		add(id)
	}
	for _, id := range candidates {
		add(id)
	}
	assets, err := h.planningAssets(row.UserID, ids)
	if err != nil {
		return bridge.CreationPlanningRequest{}, err
	}
	templates, err := h.planningTemplates(row.UserID)
	if err != nil {
		return bridge.CreationPlanningRequest{}, err
	}
	messages := append([]bridge.CreativeMessage{}, doc.Messages...)
	if len(messages) > 40 {
		messages = append(messages[:2:2], messages[len(messages)-38:]...)
	}
	for i := range messages {
		messages[i].Planning = nil
	}
	context := map[string]map[string]interface{}{}
	for id, state := range doc.States {
		context[id] = map[string]interface{}{"approved": creativeApproved(state), "selected_asset_id": state.SelectedAssetID}
	}
	return bridge.CreationPlanningRequest{ProjectID: row.ID, UserID: row.UserID, Messages: messages, CurrentPlan: doc.Plan, Assets: assets, Templates: templates, NodeContext: context, AutomaticMode: true, LockedNodeIDs: doc.Automation.LockedNodeIDs}, nil
}
func (h *CreationHandler) advanceAutomatic(ctx context.Context, id, request string) (bool, error) {
	h.mu.Lock()
	var row models.CreationProject
	if h.db.Where("id = ? AND automatic_request_id = ?", id, request).First(&row).Error != nil || !automaticActive(row.AutomaticStatus) {
		h.mu.Unlock()
		return true, nil
	}
	if ctx.Err() != nil || row.AutomaticStatus == "stopping" {
		h.mu.Unlock()
		return true, nil
	}
	doc, err := projectDocument(row)
	if err != nil {
		h.mu.Unlock()
		return false, errors.New("无法读取创作方案")
	}
	if len(doc.Plan.Questions) > 0 {
		planner, ok := h.generator.(creationPlanner)
		if !ok {
			h.mu.Unlock()
			return false, errors.New("创作规划尚未连接")
		}
		req, err := h.automaticRequest(row, doc, bridge.CreativeNode{}, nil)
		if err != nil {
			h.mu.Unlock()
			return false, err
		}
		automaticStep(&doc, "decide", "正在结合原始要求确定剩余创作方向", "")
		err = h.updateProject(&row, doc, false)
		h.mu.Unlock()
		if err != nil {
			return false, err
		}
		callCtx, cancel := context.WithTimeout(ctx, 915*time.Second)
		defer cancel()
		response, err := planner.PlanCreation(callCtx, req)
		h.mu.Lock()
		defer h.mu.Unlock()
		if !h.automaticCurrent(&row, request) {
			return true, nil
		}
		doc, _ = projectDocument(row)
		if err != nil || response == nil {
			return false, errors.New(creationFailureMessage(err, "未能确定剩余方向，原有内容保留，可稍后继续"))
		}
		allowed := map[string]bool{}
		for _, a := range req.Assets {
			if len(a.MimeType) >= 6 && a.MimeType[:6] == "image/" {
				allowed[a.ID] = true
			}
		}
		if err = validateCreativePlan(response.Plan, allowed); err != nil {
			return false, err
		}
		if err = protectAutomaticPlan(doc, response.Plan); err != nil {
			return false, err
		}
		if len(response.Plan.Questions) > 0 {
			return false, fmt.Errorf("需要补充信息：%s", response.Plan.Questions[0].Question)
		}
		doc = applyCreativePlan(doc, response.Plan)
		row.Name = response.Plan.Title
		automaticStep(&doc, "decided", response.Reply, "")
		_ = persistTokenUsageRecordDB(h.db, row.ID, row.UserID, 0, "creation_director", time.Now(), &bridge.ChatResponse{ModelUsed: response.ModelUsed, TokensUsed: response.TokensUsed, RunID: response.RunID, Runtime: "self"})
		return false, h.updateProject(&row, doc, true)
	}
	var node bridge.CreativeNode
	for _, n := range doc.Plan.Nodes {
		state := doc.States[n.ID]
		if n.Kind == "video" && state.RunID != "" {
			var run models.CreationRun
			if h.db.Where("id = ? AND user_id = ? AND node_revision = ? AND status = ?", state.RunID, row.UserID, state.Revision, "completed").First(&run).Error == nil && len(state.Candidates) > 0 {
				continue
			}
		}
		if creativeApproved(state) && n.Kind != "video" {
			continue
		}
		node = n
		break
	}
	if node.ID == "" {
		h.mu.Unlock()
		return true, nil
	}
	if err = creativeDependenciesReady(doc, node); err != nil {
		h.mu.Unlock()
		return false, err
	}
	state := doc.States[node.ID]
	if node.Kind == "video" && creativeApproved(state) {
		submission, err := h.prepareAutomaticRun(row, doc, node, request)
		h.mu.Unlock()
		if err != nil {
			return false, err
		}
		return h.runAutomaticMedia(submission)
	}
	candidates := []string{}
	if node.Kind == "image" {
		if state.SelectedAssetID != "" {
			candidates = []string{state.SelectedAssetID}
		} else if node.AssetID != "" {
			candidates = []string{node.AssetID}
		} else {
			candidates = append(candidates, state.Candidates...)
		}
	}
	req, err := h.automaticRequest(row, doc, node, candidates)
	if err != nil {
		h.mu.Unlock()
		return false, err
	}
	automaticStep(&doc, "review", "正在自动审阅「"+node.Title+"」", node.ID)
	err = h.updateProject(&row, doc, false)
	h.mu.Unlock()
	if err != nil {
		return false, err
	}
	callCtx, cancel := context.WithTimeout(ctx, 195*time.Second)
	defer cancel()
	expectedRevision := row.Revision
	response, err := h.generator.(creationReviewer).ReviewCreation(callCtx, bridge.CreationReviewRequest{CreationPlanningRequest: req, NodeID: node.ID, CandidateIDs: candidates})
	h.mu.Lock()
	if !h.automaticCurrent(&row, request) {
		h.mu.Unlock()
		return true, nil
	}
	doc, _ = projectDocument(row)
	if row.Revision != expectedRevision {
		h.mu.Unlock()
		return false, errors.New("审阅期间方案发生变化，已停止以保留最新内容")
	}
	for _, asset := range req.Assets {
		if asset.DataURL == "" {
			continue
		}
		current, readErr := h.imageInput(row.UserID, asset.ID)
		if readErr != nil || creativeHash(current) != creativeHash(asset.DataURL) {
			h.mu.Unlock()
			return false, errors.New("审阅期间参考图片发生变化，请检查后继续")
		}
	}
	if err != nil || response == nil {
		h.mu.Unlock()
		return false, errors.New(creationFailureMessage(err, "自动审阅未完成，已确认内容与生成结果保留，可稍后继续"))
	}
	if response.Decision == "blocked" {
		h.mu.Unlock()
		return false, fmt.Errorf("「%s」需要处理：%s", node.Title, response.Reason)
	}
	if response.Reason == "" || (response.Decision != "approve" && response.Decision != "select") {
		h.mu.Unlock()
		return false, errors.New("自动审阅返回无效决策，原有内容保留")
	}
	if len(candidates) > 0 {
		valid := false
		for _, id := range candidates {
			valid = valid || id == response.AssetID
		}
		if response.Decision != "select" || !valid {
			h.mu.Unlock()
			return false, errors.New("自动选图未能匹配已有候选，原有选择保留")
		}
	} else if response.Decision != "approve" || response.AssetID != "" {
		h.mu.Unlock()
		return false, errors.New("自动审阅不能引用其他资产")
	}
	_ = persistTokenUsageRecordDB(h.db, row.ID, row.UserID, 0, "creation_director", time.Now(), &bridge.ChatResponse{ModelUsed: response.ModelUsed, TokensUsed: response.TokensUsed, RunID: response.RunID, Runtime: "self"})
	automaticStep(&doc, "decision", "「"+node.Title+"」："+response.Reason, node.ID)
	if node.Kind == "image" && len(candidates) == 0 {
		submission, err := h.prepareAutomaticRun(row, doc, node, request)
		h.mu.Unlock()
		if err != nil {
			return false, err
		}
		return h.runAutomaticMedia(submission)
	}
	state = doc.States[node.ID]
	if response.Decision == "select" && state.SelectedAssetID != response.AssetID {
		state.SelectedAssetID = response.AssetID
		state.Revision++
		invalidateCreativeChildren(&doc, node.ID)
		doc.States[node.ID] = state
	}
	_, hashes, err := h.creativeInputs(row.UserID, doc, node)
	if err != nil {
		h.mu.Unlock()
		return false, err
	}
	state.ApprovedRevision = state.Revision
	state.ApprovedInputs = hashes
	state.ApprovedBy = "agent"
	doc.States[node.ID] = state
	err = h.updateProject(&row, doc, true)
	h.mu.Unlock()
	return false, err
}

// A stopped/replaced request cannot apply a late model response.
func (h *CreationHandler) automaticCurrent(row *models.CreationProject, request string) bool {
	return h.db.Where("id = ? AND automatic_request_id = ? AND automatic_status = ?", row.ID, request, "running").First(row).Error == nil
}
func (h *CreationHandler) prepareAutomaticRun(row models.CreationProject, doc creativeDocument, node bridge.CreativeNode, request string) (*creationSubmission, error) {
	automaticStep(&doc, "generate", "正在生成「"+node.Title+"」", node.ID)
	return h.prepareProjectRun(row, doc, node.ID, fmt.Sprintf("auto:%s:%s:%d", request, node.ID, doc.States[node.ID].Revision))
}
func (h *CreationHandler) runAutomaticMedia(submission *creationSubmission) (bool, error) {
	h.execute(submission.run, submission.graph, submission.progress)
	var run models.CreationRun
	if err := h.db.First(&run, "id = ?", submission.run.ID).Error; err != nil {
		return false, errors.New("无法读取生成结果，已完成资产保留")
	}
	if run.Status != "completed" {
		return false, errors.New("当前节点未完成，后续生成已停止；已有产物保留，可检查后继续")
	}
	return false, nil
}
