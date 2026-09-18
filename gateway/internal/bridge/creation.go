package bridge

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
)

type ImageReferenceContext struct {
	Role string `json:"role"`
	Note string `json:"note"`
}
type CreationNodeRequest struct {
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
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("媒体生成服务返回 %d", resp.StatusCode)
	}
	var result CreationNodeResponse
	err = json.NewDecoder(io.LimitReader(resp.Body, 90<<20)).Decode(&result)
	return &result, err
}
