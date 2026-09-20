package bridge

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
)

type CreationReviewRequest struct {
	CreationPlanningRequest
	NodeID       string   `json:"node_id"`
	CandidateIDs []string `json:"candidate_ids"`
}
type CreationReviewResponse struct {
	Findings   []CreationReviewFinding `json:"findings,omitempty"`
	Decision   string                  `json:"decision"`
	AssetID    string                  `json:"asset_id"`
	Reason     string                  `json:"reason"`
	ModelUsed  string                  `json:"model_used"`
	TokensUsed map[string]int          `json:"tokens_used"`
	RunID      string                  `json:"run_id"`
}

type CreationReviewFinding struct {
	CandidateID      string `json:"candidate_id"`
	Category         string `json:"category"`
	SourceID         string `json:"source_id"`
	RequirementQuote string `json:"requirement_quote"`
	Observation      string `json:"observation"`
}

func (c *AgentClient) ReviewCreation(ctx context.Context, req CreationReviewRequest) (*CreationReviewResponse, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, err
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/agent/creation/review", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	request.Header.Set("Content-Type", "application/json")
	response, err := (&http.Client{Transport: c.httpClient.Transport}).Do(request)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		return nil, creationResponseError(response.Body, "自动审阅未完成，请稍后继续；已确认内容与生成结果保留")
	}
	var result CreationReviewResponse
	err = json.NewDecoder(io.LimitReader(response.Body, 64<<10)).Decode(&result)
	return &result, err
}
