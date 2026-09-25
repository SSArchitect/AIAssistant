package handlers

import (
	"context"
	"errors"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
)

// Agent runtime settings are ephemeral. Restore persisted configuration before
// every operation, including later steps of an automatic workflow after a restart.
type configuredCreationAgent struct {
	*bridge.AgentClient
	syncer *ConfigSyncer
}

func (a *configuredCreationAgent) syncConfig(ctx context.Context) error {
	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	if err := ctx.Err(); err != nil {
		return err
	}
	settings, err := a.syncer.SettingsMap()
	if err == nil {
		err = a.UpdateConfigContext(ctx, settings)
	}
	if err != nil {
		return &bridge.CreationPlanningError{Code: planningRetryCode(err), Message: "创作服务配置同步失败，原有内容已保留，请稍后重试"}
	}
	return nil
}

func (a *configuredCreationAgent) PlanCreation(ctx context.Context, req bridge.CreationPlanningRequest) (*bridge.CreationPlanningResponse, error) {
	if err := a.syncConfig(ctx); err != nil {
		return nil, err
	}
	return a.AgentClient.PlanCreation(ctx, req)
}

func (a *configuredCreationAgent) PlanCreationWithProgress(ctx context.Context, req bridge.CreationPlanningRequest, progress func(bridge.CreationPlanningProgress)) (*bridge.CreationPlanningResponse, error) {
	if err := a.syncConfig(ctx); err != nil {
		return nil, err
	}
	return a.AgentClient.PlanCreationWithProgress(ctx, req, progress)
}

func (a *configuredCreationAgent) ReviewCreation(ctx context.Context, req bridge.CreationReviewRequest) (*bridge.CreationReviewResponse, error) {
	if err := a.syncConfig(ctx); err != nil {
		return nil, err
	}
	return a.AgentClient.ReviewCreation(ctx, req)
}

func (a *configuredCreationAgent) CreateMedia(ctx context.Context, req bridge.CreationNodeRequest) (*bridge.CreationNodeResponse, error) {
	if err := a.syncConfig(ctx); err != nil {
		return nil, err
	}
	return a.AgentClient.CreateMedia(ctx, req)
}

func creationFailureMessage(err error, fallback string) string {
	if errors.Is(err, context.DeadlineExceeded) {
		return "创作规划达到本轮总时限；已确认内容保留，部分节点仍未完成"
	}
	var safe *bridge.CreationPlanningError
	if errors.As(err, &safe) {
		return safe.Message
	}
	var media *bridge.CreationMediaError
	if errors.As(err, &media) {
		return media.Message
	}
	return fallback
}
