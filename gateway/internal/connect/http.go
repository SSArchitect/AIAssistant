package connect

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"strconv"
	"time"
)

func platformClient() *http.Client {
	return &http.Client{Timeout: 40 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
}
func requestJSON(ctx context.Context, client *http.Client, method, url string, headers map[string]string, body any, out any) error {
	var data []byte
	var err error
	if body != nil {
		data, err = json.Marshal(body)
		if err != nil {
			return err
		}
	}
	req, err := http.NewRequestWithContext(ctx, method, url, bytes.NewReader(data))
	if err != nil {
		return ErrInvalid
	}
	req.Header.Set("Content-Type", "application/json")
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	resp, err := client.Do(req)
	if err != nil {
		var network net.Error
		return &SendError{Message: "平台请求未确认，请检查网络", Unknown: true, Timeout: errors.As(err, &network) && network.Timeout()}
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		delay, _ := strconv.Atoi(resp.Header.Get("Retry-After"))
		return &SendError{Message: fmt.Sprintf("平台请求失败（HTTP %d）", resp.StatusCode), Retryable: resp.StatusCode == 429, Unknown: resp.StatusCode >= 500, RetryAfterSeconds: delay}
	}
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 2*1024*1024+1))
	if err != nil || len(raw) > 2*1024*1024 {
		return &SendError{Message: "平台响应未能完整读取", Unknown: true}
	}
	if err = json.Unmarshal(raw, out); err != nil {
		return &SendError{Message: "平台响应格式异常", Unknown: true}
	}
	return nil
}
