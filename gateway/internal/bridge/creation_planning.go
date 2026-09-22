package bridge

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

type CreativeSceneInterval struct {
	StartSeconds float64 `json:"start_seconds"`
	EndSeconds   float64 `json:"end_seconds"`
}
type CreativeReference struct {
	ShotIDs        []string                `json:"shot_ids,omitempty"`
	SceneIntervals []CreativeSceneInterval `json:"scene_intervals,omitempty"`
	NodeID         string                  `json:"node_id"`
	AssetID        string                  `json:"asset_id"`
	Role           string                  `json:"role"`
	Note           string                  `json:"note"`
}

// Omitted and empty optional bindings have the same semantics. Normalize on
// decode so old approved references are not invalidated by a model round-trip.
func (r *CreativeReference) UnmarshalJSON(data []byte) error {
	type wire CreativeReference
	var value wire
	if err := json.Unmarshal(data, &value); err != nil {
		return err
	}
	if len(value.SceneIntervals) == 0 {
		value.SceneIntervals = nil
	}
	if len(value.ShotIDs) == 0 {
		value.ShotIDs = nil
	}
	*r = CreativeReference(value)
	return nil
}

type CreativeRevisionSuggestion struct {
	Label       string `json:"label"`
	Instruction string `json:"instruction"`
}
type CreativeNode struct {
	ImageLayout         []ImagePlacement             `json:"image_layout,omitempty"`
	EditSourceAssetID   string                       `json:"edit_source_asset_id,omitempty"`
	ShotIDs             []string                     `json:"shot_ids,omitempty"`
	ID                  string                       `json:"id"`
	Kind                string                       `json:"kind"`
	Title               string                       `json:"title"`
	Purpose             string                       `json:"purpose"`
	Content             string                       `json:"content"`
	Prompt              string                       `json:"prompt"`
	Storyboard          json.RawMessage              `json:"storyboard,omitempty"`
	AssetID             string                       `json:"asset_id"`
	DependsOn           []string                     `json:"depends_on"`
	References          []CreativeReference          `json:"references"`
	AspectRatio         string                       `json:"aspect_ratio"`
	DurationSeconds     int                          `json:"duration_seconds"`
	Count               int                          `json:"count"`
	CharacterStyle      string                       `json:"character_style"`
	TemplateID          string                       `json:"template_id"`
	RevisionSuggestions []CreativeRevisionSuggestion `json:"revision_suggestions,omitempty"`
}

func (n *CreativeNode) UnmarshalJSON(data []byte) error {
	type wire CreativeNode
	var value wire
	if err := json.Unmarshal(data, &value); err != nil {
		return err
	}
	if len(value.ImageLayout) == 0 {
		value.ImageLayout = nil
	}
	if len(value.ShotIDs) == 0 {
		value.ShotIDs = nil
	}
	// Saved Go plans omit empty suggestions; Python sends []. Both mean no
	// suggestions and must not invalidate unrelated nodes locked during repair.
	if len(value.RevisionSuggestions) == 0 {
		value.RevisionSuggestions = nil
	}
	*n = CreativeNode(value)
	return nil
}

type CreativeQuestion struct {
	Question string   `json:"question"`
	Options  []string `json:"options"`
}
type CreativePlan struct {
	Title              string             `json:"title"`
	Summary            string             `json:"summary"`
	WorkflowTemplateID string             `json:"workflow_template_id"`
	Nodes              []CreativeNode     `json:"nodes"`
	Questions          []CreativeQuestion `json:"questions"`
}
type CreativeMessage struct {
	Preferences *CreativePreferences      `json:"preferences,omitempty"`
	Planning    *CreativePlanningActivity `json:"planning,omitempty"`
	Role        string                    `json:"role"`
	Content     string                    `json:"content"`
	NodeID      string                    `json:"node_id,omitempty"`
	AssetIDs    []string                  `json:"asset_ids,omitempty"`
}
type CreativePreferences struct {
	OutputKind  string `json:"output_kind"`
	AspectRatio string `json:"aspect_ratio"`
}
type PlanningAsset struct {
	ID       string `json:"id"`
	Name     string `json:"name"`
	MimeType string `json:"mime_type"`
	DataURL  string `json:"data_url,omitempty"`
}
type CreationRepairFeedback struct {
	Execution        *CreationRepairExecution `json:"execution,omitempty"`
	PreviousAttempts []CreationRepairAttempt  `json:"previous_attempts,omitempty"`
	Findings         []CreationReviewFinding  `json:"findings,omitempty"`
	NodeID           string                   `json:"node_id"`
	Reason           string                   `json:"reason"`
	CandidateIDs     []string                 `json:"candidate_ids"`
	Attempt          int                      `json:"attempt"`
	PreviousFeedback []string                 `json:"previous_feedback"`
}
type CreationRepairExecution struct {
	Operation         string `json:"operation"`
	EditSourceAssetID string `json:"edit_source_asset_id,omitempty"`
}
type CreationRepairAttempt struct {
	Attempt      int                      `json:"attempt"`
	CandidateIDs []string                 `json:"candidate_ids"`
	Findings     []CreationReviewFinding  `json:"findings,omitempty"`
	Execution    *CreationRepairExecution `json:"execution,omitempty"`
}
type CreationPlanningRequest struct {
	RequireShotReferences bool                              `json:"require_shot_references,omitempty"`
	RequireVideoScenes    bool                              `json:"require_video_scenes,omitempty"`
	Repair                *CreationRepairFeedback           `json:"repair,omitempty"`
	Preferences           *CreativePreferences              `json:"preferences,omitempty"`
	AutomaticMode         bool                              `json:"automatic_mode,omitempty"`
	LockedNodeIDs         []string                          `json:"locked_node_ids,omitempty"`
	ProjectID             string                            `json:"project_id"`
	UserID                string                            `json:"user_id"`
	Messages              []CreativeMessage                 `json:"messages"`
	CurrentPlan           CreativePlan                      `json:"current_plan"`
	Assets                []PlanningAsset                   `json:"assets"`
	Templates             []map[string]interface{}          `json:"templates"`
	PreferredTemplateID   string                            `json:"preferred_template_id"`
	NodeContext           map[string]map[string]interface{} `json:"node_context"`
}
type CreationPlanningResponse struct {
	Reply      string         `json:"reply"`
	Plan       CreativePlan   `json:"plan"`
	ModelUsed  string         `json:"model_used"`
	TokensUsed map[string]int `json:"tokens_used"`
	RunID      string         `json:"run_id"`
}

func (c *AgentClient) PlanCreation(ctx context.Context, req CreationPlanningRequest) (*CreationPlanningResponse, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, err
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/agent/creation/plan", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	request.Header.Set("Content-Type", "application/json")
	client := &http.Client{Transport: c.httpClient.Transport}
	response, err := client.Do(request)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, creationResponseError(response.Body, "创作助手暂时无法完成规划，原有内容已保留，请重试")
	}
	var result CreationPlanningResponse
	err = json.NewDecoder(io.LimitReader(response.Body, 512<<10)).Decode(&result)
	return &result, err
}

// Only operational milestones cross this boundary, never model reasoning or raw JSON.
type CreationPlanningProgress struct {
	Stage       string `json:"stage"`
	Message     string `json:"message"`
	OutputChars int    `json:"output_chars,omitempty"`
}

func (c *AgentClient) PlanCreationWithProgress(ctx context.Context, req CreationPlanningRequest, progress func(CreationPlanningProgress)) (*CreationPlanningResponse, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, err
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/agent/creation/plan/stream", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	request.Header.Set("Content-Type", "application/json")
	response, err := (&http.Client{Transport: c.httpClient.Transport}).Do(request)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("创作规划服务返回 %d", response.StatusCode)
	}
	decoder := json.NewDecoder(io.LimitReader(response.Body, 4<<20))
	for {
		var event struct {
			Type string `json:"type"`
			Code string `json:"code"`
			CreationPlanningProgress
			Result *CreationPlanningResponse `json:"result"`
		}
		if err := decoder.Decode(&event); err != nil {
			return nil, fmt.Errorf("创作规划连接中断: %w", err)
		}
		switch event.Type {
		case "progress":
			if progress != nil {
				progress(event.CreationPlanningProgress)
			}
		case "result":
			if event.Result == nil {
				return nil, fmt.Errorf("创作规划结果为空")
			}
			return event.Result, nil
		case "error":
			return nil, &CreationPlanningError{Code: event.Code, Message: creationSafeMessage(event.Code, event.Message, "创作助手暂时无法完成规划，原有内容已保留，请重试")}
		}
	}
}

func creationSafeMessage(code, legacy, fallback string) string {
	// Codes select fixed public text; upstream payloads never become UI errors.
	safeMessages := map[string]string{
		"provider_config_missing":        "创作模型配置未就绪，请检查模型配置或稍后重试；原有内容已保留",
		"model_image_unsupported":        "当前规划模型不支持图片输入，请配置支持图片理解的模型后重试；素材已保留",
		"provider_auth_failed":           "规划模型鉴权或访问权限异常，请检查模型服务配置；原有内容已保留",
		"provider_rate_limited":          "规划模型调用额度不足或请求过于频繁，请检查额度或稍后重试；原有内容已保留",
		"provider_request_rejected":      "规划模型拒绝了本次请求，请检查所选模型的输入能力与配置；原有内容已保留",
		"provider_unavailable":           "暂时无法连接规划模型服务，请稍后重试；原有内容已保留",
		"planning_timeout":               "创作规划等待超时，原有内容已保留，请重试",
		"planning_output_truncated":      "模型未完整返回创作方案，原有内容已保留；请分段规划后继续",
		"invalid_plan":                   "创作方案格式校验失败，原有内容已保留，请补充要求或重试",
		"review_invalid_result":          "审阅回复格式未通过校验，原有内容与候选保留，可继续审阅",
		"review_evidence_quote_mismatch": "审阅引用与原要求不一致，原有内容与候选保留，可继续审阅",
		"plan_constraint_failed":         "节点内容、依赖或引用未通过校验，原有内容已保留，请调整相应节点",
		"execution_capacity_exceeded":    "这段视频必须保留的原文超出单次生成容量，需要缩短或拆分；你的选择与原方案已保留",
		"execution_compaction_failed":    "视频执行稿自动整理未完成，已保留你的选择与原方案。请重试这次规划，无需重新选择创作方向",
		"video_reference_failed":         "视频参考图绑定自动整理未完成，已保留你的选择与原方案。请重试这次规划，无需重新选择创作方向",
	}
	if message, ok := safeMessages[code]; ok {
		return message
	}
	if legacy == safeMessages["invalid_plan"] || legacy == safeMessages["planning_timeout"] {
		return legacy
	}
	return fallback
}

func creationResponseError(body io.Reader, fallback string) error {
	var response struct {
		Detail struct {
			Code string `json:"code"`
		} `json:"detail"`
	}
	if json.NewDecoder(io.LimitReader(body, 64<<10)).Decode(&response) != nil {
		return &CreationPlanningError{Message: fallback}
	}
	return &CreationPlanningError{Code: response.Detail.Code, Message: creationSafeMessage(response.Detail.Code, "", fallback)}
}

type CreationPlanningError struct{ Code, Message string }

func (e *CreationPlanningError) Error() string { return e.Message }

type CreativePlanningStep struct {
	Stage     string `json:"stage"`
	Message   string `json:"message"`
	ElapsedMS int64  `json:"elapsed_ms"`
}
type CreativePlanningActivity struct {
	ID          string                 `json:"id"`
	Status      string                 `json:"status"`
	StartedAt   time.Time              `json:"started_at"`
	ElapsedMS   int64                  `json:"elapsed_ms"`
	OutputChars int                    `json:"output_chars,omitempty"`
	Steps       []CreativePlanningStep `json:"steps"`
}
