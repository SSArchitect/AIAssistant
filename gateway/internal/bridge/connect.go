package bridge

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"time"
)

type ConnectRun struct {
	RunID    string        `json:"run_id"`
	Status   string        `json:"status"`
	Response *ChatResponse `json:"response"`
	Error    string        `json:"error"`
}

func (c *AgentClient) ConnectRun(ctx context.Context, request *ChatRequest, runID, userID string) (*ConnectRun, error) {
	method := http.MethodGet
	path := "/agent/connect/runs/" + url.PathEscape(runID) + "?user_id=" + url.QueryEscape(userID)
	var body []byte
	if request != nil {
		method = http.MethodPost
		path = "/agent/connect/runs"
		var e error
		body, e = json.Marshal(request)
		if e != nil {
			return nil, e
		}
	}
	ctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	req, e := http.NewRequestWithContext(ctx, method, c.baseURL+path, bytes.NewReader(body))
	if e != nil {
		return nil, e
	}
	req.Header.Set("Content-Type", "application/json")
	resp, e := c.httpClient.Do(req)
	if e != nil {
		return nil, e
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("Connect runtime status %d", resp.StatusCode)
	}
	var result ConnectRun
	e = json.NewDecoder(resp.Body).Decode(&result)
	return &result, e
}
