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

type CreativeReference struct {
	NodeID  string `json:"node_id"`
	AssetID string `json:"asset_id"`
	Role    string `json:"role"`
	Note    string `json:"note"`
}
type CreativeRevisionSuggestion struct {
	Label       string `json:"label"`
	Instruction string `json:"instruction"`
}
type CreativeNode struct {
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
	Planning *CreativePlanningActivity `json:"planning,omitempty"`
	Role     string                    `json:"role"`
	Content  string                    `json:"content"`
	NodeID   string                    `json:"node_id,omitempty"`
	AssetIDs []string                  `json:"asset_ids,omitempty"`
}
type PlanningAsset struct {
	ID       string `json:"id"`
	Name     string `json:"name"`
	MimeType string `json:"mime_type"`
	DataURL  string `json:"data_url,omitempty"`
}
type CreationPlanningRequest struct {
	ProjectID           string                            `json:"project_id"`
	UserID              string                            `json:"user_id"`
	Messages            []CreativeMessage                 `json:"messages"`
	CurrentPlan         CreativePlan                      `json:"current_plan"`
	Assets              []PlanningAsset                   `json:"assets"`
	Templates           []map[string]interface{}          `json:"templates"`
	PreferredTemplateID string                            `json:"preferred_template_id"`
	NodeContext         map[string]map[string]interface{} `json:"node_context"`
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
		return nil, fmt.Errorf("创作规划服务返回 %d", response.StatusCode)
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
			// The agent route emits safe errors; still constrain the public surface.
			message := "创作助手暂时无法完成规划，原有内容已保留，请重试"
			if event.Message == "创作方案格式校验失败，原有内容已保留，请补充要求或重试" || event.Message == "创作规划等待超时，原有内容已保留，请重试" {
				message = event.Message
			}
			safeMessages := map[string]string{
				"model_image_unsupported":   "当前规划模型不支持图片输入，请配置支持图片理解的模型后重试；素材已保留",
				"provider_auth_failed":      "规划模型鉴权或访问权限异常，请检查模型服务配置；原有内容已保留",
				"provider_rate_limited":     "规划模型调用额度不足或请求过于频繁，请检查额度或稍后重试；原有内容已保留",
				"provider_request_rejected": "规划模型拒绝了本次请求，请检查所选模型的输入能力与配置；原有内容已保留",
				"provider_unavailable":      "暂时无法连接规划模型服务，请稍后重试；原有内容已保留",
				"planning_timeout":          "创作规划等待超时，原有内容已保留，请重试",
				"planning_output_truncated": "模型未完整返回创作方案，原有内容已保留；请分段规划后继续",
				"invalid_plan":              "创作方案格式校验失败，原有内容已保留，请补充要求或重试",
			}
			if safe, ok := safeMessages[event.Code]; ok {
				message = safe
			}
			return nil, &CreationPlanningError{Message: message}
		}
	}
}

type CreationPlanningError struct{ Message string }

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
