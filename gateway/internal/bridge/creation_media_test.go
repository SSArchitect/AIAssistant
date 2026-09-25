package bridge

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestCreationMediaErrorsKeepSafeDiagnosisAndRecoveryIdentity(t *testing.T) {
	for _, body := range []string{`{"detail":{"code":"media_wait_timeout","provider_task_id":"task-1","message":"SECRET"}}`, `{"detail":{"code":"SECRET","provider_task_id":"invalid/task","message":"SECRET"}}`, `<html>SECRET</html>`} {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(504); w.Write([]byte(body)) }))
		_, err := NewAgentClient(server.URL, time.Second).CreateMedia(context.Background(), CreationNodeRequest{})
		server.Close()
		var detail *CreationMediaError
		if !errors.As(err, &detail) || strings.Contains(err.Error(), "SECRET") {
			t.Fatal("unsafe media error", err)
		}
		if strings.Contains(body, "media_wait_timeout") {
			if !detail.Retryable || detail.ProviderTaskID != "task-1" || !strings.Contains(detail.Message, "超时") {
				t.Fatal(detail)
			}
		} else if (detail.Retryable && !strings.HasPrefix(body, "<html>")) || detail.ProviderTaskID != "" {
			t.Fatal("untrusted response accepted", detail)
		}
	}
}

func TestImagePreparationErrorsDoNotPretendProviderSubmissionFailed(t *testing.T) {
	for _, code := range []string{"media_image_prompt_capacity", "media_image_prompt_compaction_failed", "media_reference_view_failed"} {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(400)
			w.Write([]byte(`{"detail":{"code":"` + code + `","provider_task_id":"","message":"SECRET"}}`))
		}))
		_, err := NewAgentClient(server.URL, time.Second).CreateMedia(context.Background(), CreationNodeRequest{})
		server.Close()
		var detail *CreationMediaError
		if !errors.As(err, &detail) || detail.Code != code || detail.Retryable != (code != "media_image_prompt_capacity") || detail.ProviderTaskID != "" || !strings.Contains(detail.Message, "尚未提交生成") || strings.Contains(detail.Message, "SECRET") {
			t.Fatal("image preparation error lost its safe classification", err)
		}
	}
}
