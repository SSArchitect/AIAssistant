package bridge

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"regexp"
)

type ImageReferenceContext struct {
	Role string `json:"role"`
	Note string `json:"note"`
}
type CreationNodeRequest struct {
	ImageOperation  string                  `json:"image_operation,omitempty"`
	ResumeTaskID    string                  `json:"resume_task_id,omitempty"`
	ImagePurpose    string                  `json:"image_purpose,omitempty"`
	ImageReferences []ImageReferenceContext `json:"image_references,omitempty"`
	Kind            string                  `json:"kind"`
	Prompt          string                  `json:"prompt"`
	AspectRatio     string                  `json:"aspect_ratio"`
	DurationSeconds int                     `json:"duration_seconds"`
	CharacterStyle  string                  `json:"character_style"`
	InputImages     []string                `json:"input_images"`
	IdempotencyKey  string                  `json:"idempotency_key"`
	VideoMode       string                  `json:"video_mode,omitempty"`
	Storyboard      json.RawMessage         `json:"storyboard,omitempty"`
}
type CreationNodeResponse struct {
	Content        string `json:"content"`
	MimeType       string `json:"mime_type"`
	ProviderTaskID string `json:"provider_task_id"`
}

func (c *AgentClient) CreateMedia(ctx context.Context, req CreationNodeRequest) (*CreationNodeResponse, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, err
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/agent/creation/node", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	request.Header.Set("Content-Type", "application/json")
	// Generation can take longer than ordinary API calls; the worker owns the deadline.
	client := &http.Client{Transport: c.httpClient.Transport}
	resp, err := client.Do(request)
	if err != nil {
		return nil, newCreationMediaError("media_connection_failed", "")
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		var envelope struct {
			Detail struct {
				Code   string `json:"code"`
				TaskID string `json:"provider_task_id"`
			} `json:"detail"`
		}
		_ = json.NewDecoder(io.LimitReader(resp.Body, 4096)).Decode(&envelope)
		if envelope.Detail.Code == "" && resp.StatusCode >= 500 {
			envelope.Detail.Code = "media_status_unknown"
		}
		return nil, newCreationMediaError(envelope.Detail.Code, envelope.Detail.TaskID)
	}
	var result CreationNodeResponse
	err = json.NewDecoder(io.LimitReader(resp.Body, 90<<20)).Decode(&result)
	if err != nil {
		return nil, newCreationMediaError("media_status_unknown", "")
	}
	return &result, nil
}

// Fixed public diagnostics only; upstream bodies may contain credentials or HTML.
type CreationMediaError struct {
	Code           string
	Message        string
	ProviderTaskID string
	Retryable      bool
}

func (e *CreationMediaError) Error() string { return e.Message }
func newCreationMediaError(code, taskID string) *CreationMediaError {
	messages := map[string]string{
		"media_status_unknown":                 "生成服务响应中断，原任务状态尚未确认；继续时会先查询原任务",
		"media_wait_timeout":                   "等待生成结果超时，原任务可能仍在运行；继续时会接回原任务，不重复提交",
		"media_connection_failed":              "生成服务连接中断，原任务状态尚未确认；继续时会先查询原任务",
		"media_download_failed":                "生成结果下载中断，继续时会重取原任务结果",
		"media_artifact_expired":               "原任务产物已过期，需重新生成",
		"media_generation_failed":              "生成服务明确返回任务失败，请调整该节点后重新生成",
		"media_unauthorized":                   "生成服务鉴权失败，请检查服务配置",
		"media_idempotency_conflict":           "生成请求与原任务不一致，已停止提交，请重新审阅该节点",
		"media_unsupported_task_type":          "生成服务暂不支持此任务类型",
		"media_provider_busy":                  "生成服务繁忙，请稍后继续原任务",
		"media_invalid_output":                 "生成服务返回的媒体文件无效，请检查该节点",
		"media_storage_failed":                 "视频已生成但保存失败，请检查存储后继续原任务",
		"media_image_prompt_capacity":          "图片必须保留的原文与参考职责超出生成容量，请精简该节点；尚未提交生成",
		"media_image_prompt_compaction_failed": "图片执行稿自动整理未完成，原有方案与资产保留；尚未提交生成，可稍后继续",
		"media_reference_view_failed":          "人物参考视图准备未完成，原资产保留；尚未提交生成，可稍后继续",
	}
	message, ok := messages[code]
	if !ok {
		code = "media_provider_error"
		message = "媒体生成未完成，已有资产保留，请检查生成服务后重试"
	}
	if !regexp.MustCompile(`^[a-zA-Z0-9_-]{1,128}$`).MatchString(taskID) {
		taskID = ""
	}
	retryable := code == "media_status_unknown" || code == "media_wait_timeout" || code == "media_connection_failed" || code == "media_download_failed" || code == "media_storage_failed" || code == "media_provider_busy"
	return &CreationMediaError{Code: code, Message: message, ProviderTaskID: taskID, Retryable: retryable}
}
