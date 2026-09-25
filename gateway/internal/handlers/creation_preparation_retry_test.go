package handlers

import (
	"context"
	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"reflect"
	"testing"
	"time"
)

type preparationRetryDirector struct {
	*fakeAutomaticDirector
	attempts []bridge.CreationNodeRequest
	failures int
	code     string
}

func (f *preparationRetryDirector) CreateMedia(ctx context.Context, req bridge.CreationNodeRequest) (*bridge.CreationNodeResponse, error) {
	if req.Kind == "image" {
		f.attempts = append(f.attempts, req)
		if f.failures > 0 {
			f.failures--
			return nil, &bridge.CreationMediaError{Code: f.code, Retryable: true, Message: "图片准备未完成；尚未提交生成"}
		}
	}
	return f.fakeAutomaticDirector.CreateMedia(ctx, req)
}
func TestAutomaticPreparationRetriesBeforeSubmissionWithoutQualityRepair(t *testing.T) {
	for _, code := range []string{"media_reference_view_failed", "media_image_prompt_compaction_failed"} {
		for _, failures := range []int{2, 20} {
			t.Run(code+string(rune('A'+failures)), func(t *testing.T) {
				r, h, base, token, row := setupAutomatic(t)
				f := &preparationRetryDirector{fakeAutomaticDirector: base, failures: failures, code: code}
				h.generator = f
				startAutomatic(t, r, h, token, row.ID, "prep-retry")
				row = waitAutomatic(t, h, row.ID)
				doc, _ := projectDocument(row)
				retries := 0
				for _, s := range doc.Automation.Steps {
					if s.Stage == "prepare_retry" {
						retries++
					}
				}
				expected := failures
				if expected > 5 {
					expected = 5
				}
				if retries != expected || doc.Automation.ImageReviews["visual"].Retries != 0 {
					t.Fatal(retries, doc.Automation)
				}
				for _, req := range f.attempts[:expected+1] {
					if !reflect.DeepEqual(req, f.attempts[0]) {
						t.Fatal("changed pre-submission request")
					}
				}
				if failures > 5 {
					if row.AutomaticStatus != "failed" || len(f.attempts) != 6 || len(base.requests) != 0 {
						t.Fatal(row.AutomaticStatus, len(f.attempts), len(base.requests))
					}
				} else if row.AutomaticStatus != "completed" || len(base.requests) != 3 {
					t.Fatal(row.AutomaticStatus, len(base.requests))
				}
			})
		}
	}
}
func TestAutomaticPreparationStopsDuringBackoff(t *testing.T) {
	r, h, base, token, row := setupAutomatic(t)
	f := &preparationRetryDirector{fakeAutomaticDirector: base, failures: 20, code: "media_reference_view_failed"}
	h.generator = f
	h.retryWait = func(context.Context, time.Duration) error {
		return h.db.Model(&models.CreationProject{}).Where("id = ?", row.ID).Update("automatic_status", "stopping").Error
	}
	startAutomatic(t, r, h, token, row.ID, "stop-prep")
	row = waitAutomatic(t, h, row.ID)
	if row.AutomaticStatus != "cancelled" || len(f.attempts) != 1 || len(base.requests) != 0 {
		t.Fatal(row.AutomaticStatus, len(f.attempts))
	}
}

func TestPlanningDeadlineReportsTimeoutRatherThanConfiguration(t *testing.T) {
	message := creationFailureMessage(context.DeadlineExceeded, "检查默认对话模型配置")
	if message == "检查默认对话模型配置" || message == "" {
		t.Fatal(message)
	}
}
