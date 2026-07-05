package bridge

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"time"
)

type AgentClient struct {
	baseURL      string
	httpClient   *http.Client
	streamClient *http.Client
}

type ChatRequest struct {
	ConversationID  string                 `json:"conversation_id"`
	UserID          string                 `json:"user_id,omitempty"`
	Message         string                 `json:"message"`
	Stream          bool                   `json:"stream"`
	ModelPreference *string                `json:"model_preference,omitempty"`
	AgentID         string                 `json:"agent_id,omitempty"`
	RoleID          string                 `json:"role_id,omitempty"`
	ModeIDs         []string               `json:"mode_ids,omitempty"`
	ModePrompts     []string               `json:"mode_prompts,omitempty"`
	ContextBlocks   []string               `json:"context_blocks,omitempty"`
	DriveContext    *DriveContext          `json:"drive_context,omitempty"`
	Attachments     []ChatAttachment       `json:"attachments,omitempty"`
	AgentInput      map[string]interface{} `json:"agent_input,omitempty"`
	Handoff         map[string]interface{} `json:"handoff,omitempty"`
	MemoryEnabled   *bool                  `json:"memory_enabled,omitempty"`
	RunID           string                 `json:"run_id,omitempty"`
	DisabledTools   []string               `json:"disabled_tools,omitempty"`
}

type SearchRequest struct {
	Query   string   `json:"query"`
	Sources []string `json:"sources,omitempty"`
	Limit   int      `json:"limit,omitempty"`
}

type SearchResult struct {
	Title    string                 `json:"title"`
	Snippet  string                 `json:"snippet,omitempty"`
	URL      string                 `json:"url,omitempty"`
	Source   string                 `json:"source,omitempty"`
	Metadata map[string]interface{} `json:"metadata,omitempty"`
}

type SearchResponse struct {
	Query          string         `json:"query"`
	Sources        []string       `json:"sources"`
	ProviderErrors []string       `json:"provider_errors,omitempty"`
	Results        []SearchResult `json:"results"`
}

type ChatAttachment struct {
	Name      string `json:"name,omitempty"`
	Type      string `json:"type,omitempty"`
	Size      int    `json:"size,omitempty"`
	Kind      string `json:"kind,omitempty"`
	Content   string `json:"content,omitempty"`
	DataURL   string `json:"data_url,omitempty"`
	Truncated bool   `json:"truncated,omitempty"`
}

type DriveContext struct {
	CurrentFolderID string             `json:"current_folder_id,omitempty"`
	CurrentPath     string             `json:"current_path,omitempty"`
	Items           []DriveContextItem `json:"items,omitempty"`
	Truncated       bool               `json:"truncated,omitempty"`
}

type DriveContextItem struct {
	ID        string `json:"id,omitempty"`
	Type      string `json:"type,omitempty"`
	Name      string `json:"name,omitempty"`
	Path      string `json:"path,omitempty"`
	MimeType  string `json:"mime_type,omitempty"`
	Size      int64  `json:"size,omitempty"`
	Summary   string `json:"summary,omitempty"`
	UpdatedAt string `json:"updated_at,omitempty"`
}

type SkillCallInfo struct {
	Skill         string `json:"skill"`
	Action        string `json:"action"`
	Status        string `json:"status"`
	ResultSummary string `json:"result_summary,omitempty"`
}

type Citation struct {
	Index    int                    `json:"index"`
	Title    string                 `json:"title"`
	URL      string                 `json:"url"`
	Snippet  string                 `json:"snippet,omitempty"`
	Source   string                 `json:"source,omitempty"`
	Metadata map[string]interface{} `json:"metadata,omitempty"`
}

type ChatArtifact struct {
	Type     string                 `json:"type"`
	ItemID   string                 `json:"item_id,omitempty"`
	Name     string                 `json:"name,omitempty"`
	Title    string                 `json:"title,omitempty"`
	MimeType string                 `json:"mime_type,omitempty"`
	Size     int64                  `json:"size,omitempty"`
	Summary  string                 `json:"summary,omitempty"`
	URL      string                 `json:"url,omitempty"`
	Metadata map[string]interface{} `json:"metadata,omitempty"`
}

type RunEvent struct {
	ID         string                 `json:"id"`
	RunID      string                 `json:"run_id"`
	Type       string                 `json:"type"`
	Status     string                 `json:"status"`
	Title      string                 `json:"title"`
	StepID     string                 `json:"step_id,omitempty"`
	Payload    map[string]interface{} `json:"payload"`
	DurationMS *int                   `json:"duration_ms,omitempty"`
	CreatedAt  string                 `json:"created_at"`
}

type MemoryRecord struct {
	ID          string                 `json:"id"`
	RoleID      string                 `json:"role_id"`
	UserID      string                 `json:"user_id,omitempty"`
	Kind        string                 `json:"kind"`
	Scope       string                 `json:"scope,omitempty"`
	Status      string                 `json:"status,omitempty"`
	ReviewState string                 `json:"review_state,omitempty"`
	Content     string                 `json:"content"`
	Source      string                 `json:"source"`
	AgentID     *string                `json:"agent_id,omitempty"`
	Confidence  float64                `json:"confidence"`
	Tags        []string               `json:"tags"`
	SourceTrace map[string]interface{} `json:"source_trace,omitempty"`
	ValidFrom   *string                `json:"valid_from,omitempty"`
	ValidUntil  *string                `json:"valid_until,omitempty"`
	LastUsedAt  *string                `json:"last_used_at,omitempty"`
	TTLDays     *int                   `json:"ttl_days,omitempty"`
	Sensitivity string                 `json:"sensitivity,omitempty"`
	ReviewNotes string                 `json:"review_notes,omitempty"`
	Version     int                    `json:"version,omitempty"`
	CreatedAt   string                 `json:"created_at"`
	UpdatedAt   string                 `json:"updated_at"`
	Metadata    map[string]interface{} `json:"metadata"`
}

type ChatResponse struct {
	ConversationID string          `json:"conversation_id"`
	UserID         string          `json:"user_id,omitempty"`
	Response       string          `json:"response"`
	SkillsUsed     []string        `json:"skills_used"`
	Citations      []Citation      `json:"citations,omitempty"`
	Artifacts      []ChatArtifact  `json:"artifacts,omitempty"`
	Plan           []SkillCallInfo `json:"plan,omitempty"`
	ModelUsed      string          `json:"model_used"`
	TokensUsed     map[string]int  `json:"tokens_used"`
	ErrorType      string          `json:"error_type,omitempty"`
	AgentID        string          `json:"agent_id"`
	RoleID         string          `json:"role_id,omitempty"`
	Runtime        string          `json:"runtime"`
	RunID          string          `json:"run_id,omitempty"`
	Events         []RunEvent      `json:"events,omitempty"`
	MemoryContext  []MemoryRecord  `json:"memory_context,omitempty"`
	MemoryUpdates  []MemoryRecord  `json:"memory_updates,omitempty"`
}

type FollowUpRequest struct {
	UserQuestion    string  `json:"user_question"`
	AssistantAnswer string  `json:"assistant_answer"`
	Language        string  `json:"language,omitempty"`
	ModelPreference *string `json:"model_preference,omitempty"`
}

type FollowUpResponse struct {
	Questions []string `json:"questions"`
	ModelUsed string   `json:"model_used,omitempty"`
}

type AIGCImageRequest struct {
	Prompt           string                   `json:"prompt" binding:"required"`
	Model            string                   `json:"model,omitempty"`
	AspectRatio      string                   `json:"aspect_ratio,omitempty"`
	ResponseFormat   string                   `json:"response_format,omitempty"`
	N                int                      `json:"n,omitempty"`
	PromptOptimizer  *bool                    `json:"prompt_optimizer,omitempty"`
	Seed             *int                     `json:"seed,omitempty"`
	Width            *int                     `json:"width,omitempty"`
	Height           *int                     `json:"height,omitempty"`
	AIGCWatermark    *bool                    `json:"aigc_watermark,omitempty"`
	Style            map[string]interface{}   `json:"style,omitempty"`
	SubjectReference []map[string]interface{} `json:"subject_reference,omitempty"`
}

type GeneratedImage struct {
	Index    int    `json:"index"`
	URL      string `json:"url,omitempty"`
	Base64   string `json:"base64,omitempty"`
	MimeType string `json:"mime_type"`
}

type AIGCImageResponse struct {
	ID             string                 `json:"id"`
	Provider       string                 `json:"provider"`
	Model          string                 `json:"model"`
	Prompt         string                 `json:"prompt"`
	AspectRatio    string                 `json:"aspect_ratio"`
	ResponseFormat string                 `json:"response_format"`
	Images         []GeneratedImage       `json:"images"`
	Metadata       map[string]interface{} `json:"metadata"`
}

type SkillInfo struct {
	Name             string                   `json:"name"`
	Description      string                   `json:"description"`
	Parameters       []map[string]interface{} `json:"parameters,omitempty"`
	Version          string                   `json:"version,omitempty"`
	Tags             []string                 `json:"tags,omitempty"`
	Source           string                   `json:"source,omitempty"`
	Enabled          bool                     `json:"enabled"`
	UserEnabled      *bool                    `json:"user_enabled,omitempty"`
	EffectiveEnabled bool                     `json:"effective_enabled"`
	Configurable     bool                     `json:"configurable"`
}

type SkillListResponse struct {
	Skills       []SkillInfo       `json:"skills"`
	UserSettings map[string]string `json:"user_settings,omitempty"`
	MCP          ToolMCPConfig     `json:"mcp,omitempty"`
	Disabled     []string          `json:"disabled,omitempty"`
}

type ToolMCPConfig struct {
	Enabled bool   `json:"enabled"`
	Servers string `json:"servers"`
}

type AgentInfo struct {
	ID           string                 `json:"id"`
	Name         string                 `json:"name"`
	Description  string                 `json:"description"`
	Runtime      string                 `json:"runtime"`
	Framework    string                 `json:"framework"`
	Enabled      bool                   `json:"enabled"`
	Experimental bool                   `json:"experimental"`
	Capabilities []string               `json:"capabilities"`
	Metadata     map[string]interface{} `json:"metadata"`
}

type AgentListResponse struct {
	Agents []AgentInfo `json:"agents"`
}

type RoleProfile struct {
	ID            string                 `json:"id"`
	Name          string                 `json:"name"`
	Description   string                 `json:"description"`
	BasePersona   string                 `json:"base_persona"`
	Instructions  []string               `json:"instructions"`
	Enabled       bool                   `json:"enabled"`
	MemoryEnabled bool                   `json:"memory_enabled"`
	Metadata      map[string]interface{} `json:"metadata"`
}

type RoleListResponse struct {
	Roles []RoleProfile `json:"roles"`
}

type RoleWriteRequest struct {
	UserID        string                 `json:"user_id,omitempty"`
	ID            string                 `json:"id,omitempty"`
	Name          string                 `json:"name,omitempty"`
	Description   string                 `json:"description,omitempty"`
	BasePersona   string                 `json:"base_persona,omitempty"`
	Instructions  []string               `json:"instructions,omitempty"`
	Enabled       *bool                  `json:"enabled,omitempty"`
	MemoryEnabled *bool                  `json:"memory_enabled,omitempty"`
	Metadata      map[string]interface{} `json:"metadata,omitempty"`
}

type MemoryListResponse struct {
	Memories []MemoryRecord `json:"memories"`
}

type MemoryWriteRequest struct {
	UserID      string                 `json:"user_id,omitempty"`
	Kind        string                 `json:"kind,omitempty"`
	Scope       string                 `json:"scope,omitempty"`
	Status      string                 `json:"status,omitempty"`
	ReviewState string                 `json:"review_state,omitempty"`
	Content     string                 `json:"content,omitempty"`
	Source      string                 `json:"source,omitempty"`
	AgentID     string                 `json:"agent_id,omitempty"`
	Confidence  float64                `json:"confidence,omitempty"`
	Tags        []string               `json:"tags,omitempty"`
	SourceTrace map[string]interface{} `json:"source_trace,omitempty"`
	ValidFrom   *string                `json:"valid_from,omitempty"`
	ValidUntil  *string                `json:"valid_until,omitempty"`
	TTLDays     *int                   `json:"ttl_days,omitempty"`
	Sensitivity string                 `json:"sensitivity,omitempty"`
	ReviewNotes string                 `json:"review_notes,omitempty"`
	Metadata    map[string]interface{} `json:"metadata,omitempty"`
}

type RunRecord struct {
	RunID          string         `json:"run_id"`
	ConversationID string         `json:"conversation_id"`
	UserID         string         `json:"user_id,omitempty"`
	AgentID        string         `json:"agent_id"`
	Runtime        string         `json:"runtime"`
	Status         string         `json:"status"`
	Input          string         `json:"input"`
	Output         string         `json:"output"`
	ModelUsed      string         `json:"model_used"`
	TokensUsed     map[string]int `json:"tokens_used"`
	SkillsUsed     []string       `json:"skills_used"`
	Artifacts      []ChatArtifact `json:"artifacts,omitempty"`
	ErrorType      *string        `json:"error_type,omitempty"`
	ErrorMessage   *string        `json:"error_message,omitempty"`
	DurationMS     *int           `json:"duration_ms,omitempty"`
	StartedAt      string         `json:"started_at"`
	CompletedAt    *string        `json:"completed_at,omitempty"`
	Events         []RunEvent     `json:"events"`
}

type RunListResponse struct {
	Runs []RunRecord `json:"runs"`
}

func NewAgentClient(baseURL string, timeout time.Duration) *AgentClient {
	return &AgentClient{
		baseURL: baseURL,
		httpClient: &http.Client{
			Timeout: timeout,
		},
		streamClient: &http.Client{},
	}
}

func (c *AgentClient) Chat(req ChatRequest) (*ChatResponse, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal request: %w", err)
	}

	resp, err := c.httpClient.Post(
		c.baseURL+"/agent/chat",
		"application/json",
		bytes.NewReader(body),
	)
	if err != nil {
		return nil, fmt.Errorf("agent request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("agent returned status %d: %s", resp.StatusCode, string(respBody))
	}

	var chatResp ChatResponse
	if err := json.NewDecoder(resp.Body).Decode(&chatResp); err != nil {
		return nil, fmt.Errorf("decode response: %w", err)
	}

	return &chatResp, nil
}

func (c *AgentClient) Search(req SearchRequest) (*SearchResponse, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal search request: %w", err)
	}

	resp, err := c.httpClient.Post(
		c.baseURL+"/agent/search",
		"application/json",
		bytes.NewReader(body),
	)
	if err != nil {
		return nil, fmt.Errorf("agent search request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("agent search returned status %d: %s", resp.StatusCode, string(respBody))
	}

	var searchResp SearchResponse
	if err := json.NewDecoder(resp.Body).Decode(&searchResp); err != nil {
		return nil, fmt.Errorf("decode search response: %w", err)
	}

	return &searchResp, nil
}

func (c *AgentClient) ChatStream(req ChatRequest) (*http.Response, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal request: %w", err)
	}

	resp, err := c.streamClient.Post(
		c.baseURL+"/agent/chat/stream",
		"application/json",
		bytes.NewReader(body),
	)
	if err != nil {
		return nil, fmt.Errorf("agent stream request failed: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		defer resp.Body.Close()
		respBody, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("agent stream returned status %d: %s", resp.StatusCode, string(respBody))
	}

	return resp, nil
}

func (c *AgentClient) GenerateFollowUps(req FollowUpRequest) (*FollowUpResponse, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal follow-up request: %w", err)
	}

	resp, err := c.httpClient.Post(
		c.baseURL+"/agent/followups",
		"application/json",
		bytes.NewReader(body),
	)
	if err != nil {
		return nil, fmt.Errorf("follow-up request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("follow-up request returned status %d: %s", resp.StatusCode, string(respBody))
	}

	var followUpResp FollowUpResponse
	if err := json.NewDecoder(resp.Body).Decode(&followUpResp); err != nil {
		return nil, fmt.Errorf("decode follow-up response: %w", err)
	}

	return &followUpResp, nil
}

func (c *AgentClient) GenerateImage(req AIGCImageRequest) (*AIGCImageResponse, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal image request: %w", err)
	}

	resp, err := c.httpClient.Post(
		c.baseURL+"/agent/aigc/image",
		"application/json",
		bytes.NewReader(body),
	)
	if err != nil {
		return nil, fmt.Errorf("image generation request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("image generation returned status %d: %s", resp.StatusCode, string(respBody))
	}

	var imageResp AIGCImageResponse
	if err := json.NewDecoder(resp.Body).Decode(&imageResp); err != nil {
		return nil, fmt.Errorf("decode image response: %w", err)
	}

	return &imageResp, nil
}

func (c *AgentClient) ListSkills() (*SkillListResponse, error) {
	resp, err := c.httpClient.Get(c.baseURL + "/agent/skills")
	if err != nil {
		return nil, fmt.Errorf("skills request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("agent returned status %d: %s", resp.StatusCode, string(respBody))
	}

	var skills SkillListResponse
	if err := json.NewDecoder(resp.Body).Decode(&skills); err != nil {
		return nil, fmt.Errorf("decode skills: %w", err)
	}

	return &skills, nil
}

func (c *AgentClient) ListAgents() (*AgentListResponse, error) {
	resp, err := c.httpClient.Get(c.baseURL + "/agent/agents")
	if err != nil {
		return nil, fmt.Errorf("agents request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("agent returned status %d: %s", resp.StatusCode, string(respBody))
	}

	var agents AgentListResponse
	if err := json.NewDecoder(resp.Body).Decode(&agents); err != nil {
		return nil, fmt.Errorf("decode agents: %w", err)
	}

	return &agents, nil
}

func (c *AgentClient) ListRoles(userID string) (*RoleListResponse, error) {
	endpoint := c.baseURL + "/agent/roles"
	if userID != "" {
		endpoint += "?user_id=" + url.QueryEscape(userID)
	}
	resp, err := c.httpClient.Get(endpoint)
	if err != nil {
		return nil, fmt.Errorf("roles request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("agent returned status %d: %s", resp.StatusCode, string(respBody))
	}

	var roles RoleListResponse
	if err := json.NewDecoder(resp.Body).Decode(&roles); err != nil {
		return nil, fmt.Errorf("decode roles: %w", err)
	}
	return &roles, nil
}

func (c *AgentClient) CreateRole(req RoleWriteRequest) (*RoleProfile, error) {
	return c.writeRole(http.MethodPost, "/agent/roles", req)
}

func (c *AgentClient) UpdateRole(roleID string, req RoleWriteRequest) (*RoleProfile, error) {
	return c.writeRole(http.MethodPut, "/agent/roles/"+url.PathEscape(roleID), req)
}

func (c *AgentClient) DeleteRole(roleID string, userID string) error {
	endpoint := c.baseURL + "/agent/roles/" + url.PathEscape(roleID)
	if userID != "" {
		endpoint += "?user_id=" + url.QueryEscape(userID)
	}
	httpReq, err := http.NewRequest(http.MethodDelete, endpoint, nil)
	if err != nil {
		return fmt.Errorf("build delete role request: %w", err)
	}
	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return fmt.Errorf("delete role request failed: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("delete role returned status %d: %s", resp.StatusCode, string(respBody))
	}
	return nil
}

func (c *AgentClient) ListRoleMemories(roleID string, userID string, kind string, agentID string, includeInactive bool) (*MemoryListResponse, error) {
	params := url.Values{}
	if userID != "" {
		params.Set("user_id", userID)
	}
	if kind != "" {
		params.Set("kind", kind)
	}
	if agentID != "" {
		params.Set("agent_id", agentID)
	}
	if includeInactive {
		params.Set("include_inactive", "true")
	}

	endpoint := c.baseURL + "/agent/roles/" + url.PathEscape(roleID) + "/memories"
	if encoded := params.Encode(); encoded != "" {
		endpoint += "?" + encoded
	}

	resp, err := c.httpClient.Get(endpoint)
	if err != nil {
		return nil, fmt.Errorf("role memories request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("role memories returned status %d: %s", resp.StatusCode, string(respBody))
	}

	var memories MemoryListResponse
	if err := json.NewDecoder(resp.Body).Decode(&memories); err != nil {
		return nil, fmt.Errorf("decode role memories: %w", err)
	}
	return &memories, nil
}

func (c *AgentClient) CreateRoleMemory(roleID string, req MemoryWriteRequest) (*MemoryRecord, error) {
	return c.writeRoleMemory(http.MethodPost, "/agent/roles/"+url.PathEscape(roleID)+"/memories", req)
}

func (c *AgentClient) UpdateRoleMemory(roleID string, memoryID string, req MemoryWriteRequest) (*MemoryRecord, error) {
	return c.writeRoleMemory(
		http.MethodPut,
		"/agent/roles/"+url.PathEscape(roleID)+"/memories/"+url.PathEscape(memoryID),
		req,
	)
}

func (c *AgentClient) writeRoleMemory(method string, path string, req MemoryWriteRequest) (*MemoryRecord, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal role memory request: %w", err)
	}
	httpReq, err := http.NewRequest(method, c.baseURL+path, bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("build role memory request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("role memory request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("role memory returned status %d: %s", resp.StatusCode, string(respBody))
	}

	var memory MemoryRecord
	if err := json.NewDecoder(resp.Body).Decode(&memory); err != nil {
		return nil, fmt.Errorf("decode role memory: %w", err)
	}
	return &memory, nil
}

func (c *AgentClient) DeleteRoleMemory(roleID string, memoryID string, userID string) error {
	endpoint := c.baseURL + "/agent/roles/" + url.PathEscape(roleID) + "/memories/" + url.PathEscape(memoryID)
	if userID != "" {
		endpoint += "?user_id=" + url.QueryEscape(userID)
	}

	httpReq, err := http.NewRequest(http.MethodDelete, endpoint, nil)
	if err != nil {
		return fmt.Errorf("build delete role memory request: %w", err)
	}
	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return fmt.Errorf("delete role memory request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("delete role memory returned status %d: %s", resp.StatusCode, string(respBody))
	}
	return nil
}

func (c *AgentClient) writeRole(method string, path string, req RoleWriteRequest) (*RoleProfile, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal role request: %w", err)
	}
	httpReq, err := http.NewRequest(method, c.baseURL+path, bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("build role request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("role request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("role request returned status %d: %s", resp.StatusCode, string(respBody))
	}

	var role RoleProfile
	if err := json.NewDecoder(resp.Body).Decode(&role); err != nil {
		return nil, fmt.Errorf("decode role: %w", err)
	}
	return &role, nil
}

func (c *AgentClient) ListRuns(conversationID string, userID string, limit int) (*RunListResponse, error) {
	params := url.Values{}
	if conversationID != "" {
		params.Set("conversation_id", conversationID)
	}
	if userID != "" {
		params.Set("user_id", userID)
	}
	if limit > 0 {
		params.Set("limit", strconv.Itoa(limit))
	}

	endpoint := c.baseURL + "/agent/runs"
	if encoded := params.Encode(); encoded != "" {
		endpoint += "?" + encoded
	}

	resp, err := c.httpClient.Get(endpoint)
	if err != nil {
		return nil, fmt.Errorf("runs request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("agent returned status %d: %s", resp.StatusCode, string(respBody))
	}

	var runs RunListResponse
	if err := json.NewDecoder(resp.Body).Decode(&runs); err != nil {
		return nil, fmt.Errorf("decode runs: %w", err)
	}

	return &runs, nil
}

func (c *AgentClient) GetRun(runID string) (*RunRecord, error) {
	resp, err := c.httpClient.Get(c.baseURL + "/agent/runs/" + url.PathEscape(runID))
	if err != nil {
		return nil, fmt.Errorf("run request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("agent returned status %d: %s", resp.StatusCode, string(respBody))
	}

	var run RunRecord
	if err := json.NewDecoder(resp.Body).Decode(&run); err != nil {
		return nil, fmt.Errorf("decode run: %w", err)
	}

	return &run, nil
}

func (c *AgentClient) CancelRun(runID string) error {
	httpReq, err := http.NewRequest(http.MethodPost, c.baseURL+"/agent/runs/"+url.PathEscape(runID)+"/cancel", nil)
	if err != nil {
		return fmt.Errorf("build cancel run request: %w", err)
	}
	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return fmt.Errorf("cancel run request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("agent returned status %d: %s", resp.StatusCode, string(respBody))
	}
	return nil
}

func (c *AgentClient) UpdateConfig(config map[string]string) error {
	body, err := json.Marshal(map[string]interface{}{"settings": config})
	if err != nil {
		return fmt.Errorf("marshal config: %w", err)
	}

	resp, err := c.httpClient.Post(
		c.baseURL+"/agent/config",
		"application/json",
		bytes.NewReader(body),
	)
	if err != nil {
		return fmt.Errorf("config update request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("config update returned status %d: %s", resp.StatusCode, string(respBody))
	}
	return nil
}

type TestProviderResponse struct {
	Success bool   `json:"success"`
	Message string `json:"message"`
	Model   string `json:"model,omitempty"`
}

type ValidateProviderResponse struct {
	Success     bool   `json:"success"`
	Status      string `json:"status"`
	Provider    string `json:"provider"`
	Message     string `json:"message"`
	ModelCount  int    `json:"model_count"`
	ValidatedAt string `json:"validated_at"`
}

func (c *AgentClient) TestProvider(provider string) (*TestProviderResponse, error) {
	body, err := json.Marshal(map[string]string{"provider": provider})
	if err != nil {
		return nil, fmt.Errorf("marshal request: %w", err)
	}

	resp, err := c.httpClient.Post(
		c.baseURL+"/agent/test-provider",
		"application/json",
		bytes.NewReader(body),
	)
	if err != nil {
		return nil, fmt.Errorf("test provider request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("test provider returned status %d: %s", resp.StatusCode, string(respBody))
	}

	var result TestProviderResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("decode response: %w", err)
	}
	return &result, nil
}

func (c *AgentClient) ValidateProvider(provider string) (*ValidateProviderResponse, error) {
	body, err := json.Marshal(map[string]string{"provider": provider})
	if err != nil {
		return nil, fmt.Errorf("marshal request: %w", err)
	}

	resp, err := c.httpClient.Post(
		c.baseURL+"/agent/validate-provider",
		"application/json",
		bytes.NewReader(body),
	)
	if err != nil {
		return nil, fmt.Errorf("validate provider request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("validate provider returned status %d: %s", resp.StatusCode, string(respBody))
	}

	var result ValidateProviderResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("decode response: %w", err)
	}
	return &result, nil
}

type ModelInfo struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

type ListModelsResponse struct {
	Success bool        `json:"success"`
	Models  []ModelInfo `json:"models"`
	Error   string      `json:"error,omitempty"`
}

func (c *AgentClient) ListModels(provider string) (*ListModelsResponse, error) {
	body, err := json.Marshal(map[string]string{"provider": provider})
	if err != nil {
		return nil, fmt.Errorf("marshal request: %w", err)
	}

	resp, err := c.httpClient.Post(
		c.baseURL+"/agent/list-models",
		"application/json",
		bytes.NewReader(body),
	)
	if err != nil {
		return nil, fmt.Errorf("list models request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("list models returned status %d: %s", resp.StatusCode, string(respBody))
	}

	var result ListModelsResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("decode response: %w", err)
	}
	return &result, nil
}

func (c *AgentClient) Health() error {
	resp, err := c.httpClient.Get(c.baseURL + "/agent/health")
	if err != nil {
		return fmt.Errorf("health check failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("agent unhealthy: status %d", resp.StatusCode)
	}
	return nil
}
