package connect

import (
	"context"
	"crypto/cipher"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/google/uuid"
	"gorm.io/gorm"
)

type Service struct {
	db          *gorm.DB
	cipher      cipher.AEAD
	adapters    map[string]Adapter
	runner      Runner
	mu          sync.Mutex // Short database transitions; never held across network I/O.
	ctx         context.Context
	cancel      context.CancelFunc
	once        sync.Once
	workers     map[string]context.CancelFunc
	running     map[string]context.CancelFunc
	authorizing map[string]bool
	checks      map[string]*checkFlight
	wg          sync.WaitGroup
}

type checkFlight struct {
	done   chan struct{}
	result models.ConnectCheck
	err    error
}

func NewService(db *gorm.DB, key []byte, runner Runner, adapters ...Adapter) (*Service, error) {
	a, e := newCipher(key)
	if e != nil {
		return nil, e
	}
	if e = db.AutoMigrate(&models.ConnectConnection{}, &models.ConnectSource{}, &models.ConnectTurn{}, &models.ConnectDelivery{}, &models.ConnectCheck{}); e != nil {
		return nil, e
	}
	ctx, cancel := context.WithCancel(context.Background())
	s := &Service{db: db, cipher: a, runner: runner, adapters: map[string]Adapter{}, ctx: ctx, cancel: cancel, workers: map[string]context.CancelFunc{}, running: map[string]context.CancelFunc{}}
	s.authorizing = map[string]bool{}
	s.checks = map[string]*checkFlight{}
	for _, adapter := range adapters {
		s.adapters[adapter.Descriptor().ID] = adapter
	}
	return s, nil
}
func (s *Service) Close() {
	s.cancel()
	s.mu.Lock()
	for _, cancel := range s.workers {
		cancel()
	}
	for _, cancel := range s.running {
		cancel()
	}
	s.mu.Unlock()
	s.wg.Wait()
}
func (s *Service) Catalog() []Descriptor {
	out := []Descriptor{}
	for _, a := range s.adapters {
		out = append(out, a.Descriptor())
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out
}
func (s *Service) List(user string) ([]models.ConnectConnection, error) {
	out := []models.ConnectConnection{}
	e := s.db.Where("user_id = ?", user).Order("created_at DESC").Find(&out).Error
	return out, e
}
func (s *Service) Get(user, id string) (models.ConnectConnection, error) {
	var c models.ConnectConnection
	e := s.db.First(&c, "id = ? AND user_id = ?", id, user).Error
	if errors.Is(e, gorm.ErrRecordNotFound) {
		e = ErrNotFound
	}
	return c, e
}
func hash(v any) string {
	b, _ := json.Marshal(v)
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:])
}
func newID(prefix string) string { return prefix + uuid.NewString() }
func (s *Service) ListRoles(ctx context.Context, user string) ([]Role, error) {
	if provider, ok := s.runner.(RoleProvider); ok {
		ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
		defer cancel()
		return provider.ListRoles(ctx, user)
	}
	return []Role{{ID: "default", Name: "Default"}}, nil
}
func (s *Service) validateRole(ctx context.Context, user, roleID string) error {
	if len(roleID) > 160 {
		return ErrInvalid
	}
	roles, err := s.ListRoles(ctx, user)
	if err != nil {
		return err
	}
	for _, role := range roles {
		if role.ID == EffectiveRole(roleID) {
			return nil
		}
	}
	return fmt.Errorf("%w: 人设不存在或已停用，请重新选择", ErrInvalid)
}
func (s *Service) SetRole(ctx context.Context, user, id, roleID string) (models.ConnectConnection, error) {
	if _, err := s.Get(user, id); err != nil {
		return models.ConnectConnection{}, err
	}
	roleID = strings.TrimSpace(roleID)
	if roleID == "" {
		return models.ConnectConnection{}, ErrInvalid
	}
	if err := s.validateRole(ctx, user, roleID); err != nil {
		return models.ConnectConnection{}, err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	// Reload after validation; changing a role must never undo a concurrent disconnect.
	c, err := s.Get(user, id)
	if err != nil {
		return c, err
	}
	err = s.db.Model(&c).Update("role_id", roleID).Error
	return c, err
}
func (s *Service) Create(ctx context.Context, user string, r CreateRequest) (models.ConnectConnection, error) {
	a, ok := s.adapters[r.Kind]
	if !ok {
		return models.ConnectConnection{}, ErrUnsupported
	}
	r.Name = strings.TrimSpace(r.Name)
	r.Note = strings.TrimSpace(r.Note)
	if len([]rune(r.Note)) > MaxNoteLength {
		return models.ConnectConnection{}, ErrInvalid
	}
	if r.Name == "" || len([]rune(r.Name)) > 80 || r.RequestID == "" || len(r.RequestID) > 160 {
		return models.ConnectConnection{}, ErrInvalid
	}
	for _, f := range a.Descriptor().Fields {
		if f.Required && strings.TrimSpace(r.Credentials[f.Key]) == "" {
			return models.ConnectConnection{}, fmt.Errorf("%w: %s is required", ErrInvalid, f.Label)
		}
	}
	r.RoleID = strings.TrimSpace(r.RoleID)
	// Preserve pre-role creation hashes and treat an explicit default as the omitted default.
	if r.RoleID == "default" {
		r.RoleID = ""
	}
	digest := hash(r)
	var previous models.ConnectConnection
	if err := s.db.Unscoped().First(&previous, "user_id = ? AND request_id = ?", user, r.RequestID).Error; err == nil {
		if previous.DeletedAt.Valid || previous.RequestHash != digest {
			return previous, ErrConflict
		}
		return previous, nil
	} else if !errors.Is(err, gorm.ErrRecordNotFound) {
		return previous, err
	}
	if err := s.validateRole(ctx, user, r.RoleID); err != nil {
		return models.ConnectConnection{}, err
	}
	s.mu.Lock()
	var existing models.ConnectConnection
	err := s.db.Unscoped().First(&existing, "user_id = ? AND request_id = ?", user, r.RequestID).Error
	if err == nil {
		s.mu.Unlock()
		if existing.DeletedAt.Valid || existing.RequestHash != digest {
			return existing, ErrConflict
		}
		return existing, nil
	}
	if !errors.Is(err, gorm.ErrRecordNotFound) {
		s.mu.Unlock()
		return existing, err
	}
	cfg := Config{}
	for _, f := range a.Descriptor().Fields {
		cfg[f.Key] = strings.TrimSpace(r.Credentials[f.Key])
	}
	cfg["pairing_code"] = uuid.NewString()
	cfg["pairing_expires"] = time.Now().Add(10 * time.Minute).Format(time.RFC3339)
	c := models.ConnectConnection{ID: newID("cx_"), UserID: user, RequestID: r.RequestID, RequestHash: digest, Kind: r.Kind, Name: r.Name, Note: r.Note, RoleID: EffectiveRole(r.RoleID), DesiredState: "enabled", Status: "connecting", Generation: 1}
	c.Secret, err = s.seal(c.ID, cfg)
	if err == nil {
		err = s.db.Create(&c).Error
	}
	s.mu.Unlock()
	if err != nil {
		return c, err
	}
	return s.authenticate(ctx, c, cfg)
}
func (s *Service) authenticate(ctx context.Context, c models.ConnectConnection, cfg Config) (models.ConnectConnection, error) {
	for {
		s.mu.Lock()
		if !s.authorizing[c.ID] {
			break
		}
		s.mu.Unlock()
		if !pause(ctx, 50*time.Millisecond) {
			return c, ctx.Err()
		}
	}
	fresh, err := s.Get(c.UserID, c.ID)
	if err != nil || fresh.Generation != c.Generation || fresh.DesiredState != "enabled" {
		s.mu.Unlock()
		return fresh, ErrDisconnected
	}
	if fresh.Status == "connected" || fresh.Status == "awaiting_pairing" {
		s.mu.Unlock()
		return fresh, nil
	}
	cfg, err = s.open(c.ID, fresh.Secret)
	if err != nil {
		s.mu.Unlock()
		return fresh, err
	}
	s.authorizing[c.ID] = true
	s.mu.Unlock()
	defer func() { s.mu.Lock(); delete(s.authorizing, c.ID); s.mu.Unlock() }()
	auth, e := s.adapters[c.Kind].Authenticate(ctx, cfg)
	s.mu.Lock()
	defer s.mu.Unlock()
	var current models.ConnectConnection
	if err := s.db.First(&current, "id = ?", c.ID).Error; err != nil {
		return current, err
	}
	if current.Generation != c.Generation || current.DesiredState != "enabled" {
		return current, ErrDisconnected
	}
	if e != nil {
		// A shutdown or cancelled management request does not revoke platform authorization.
		// Keep the saved state so the supervisor can continue it with a fresh context.
		if ctx.Err() != nil {
			return current, ctx.Err()
		}
		if s.ctx.Err() != nil {
			return current, s.ctx.Err()
		}
		current.Status = "error"
		current.LastError = publicError(e)
		return current, s.db.Save(&current).Error
	}
	if auth.Config == nil {
		auth.Config = cfg
	}
	// A reconnect may refresh credentials, but may not inherit another identity's history.
	if current.RemoteID != "" && auth.RemoteID != "" && current.RemoteID != auth.RemoteID {
		current.Status = "error"
		current.LastError = "平台账号与原连接不一致，请使用原账号重新授权"
		return current, s.db.Save(&current).Error
	}
	if current.Sender != "" && auth.Sender != "" && current.Sender != auth.Sender {
		current.Status = "error"
		current.LastError = "授权用户与原连接不一致，请使用原账号重新授权"
		return current, s.db.Save(&current).Error
	}
	current.Secret, e = s.seal(c.ID, auth.Config)
	if e != nil {
		return current, e
	}
	if auth.RemoteID != "" {
		key := current.Kind + ":" + auth.RemoteID
		var count int64
		if e = s.db.Model(&models.ConnectConnection{}).Where("remote_key = ? AND id <> ?", key, c.ID).Count(&count).Error; e != nil {
			return current, e
		}
		if count > 0 {
			current.Status = "error"
			current.LastError = "此平台账号已绑定另一条连接"
			s.db.Save(&current)
			return current, nil
		}
		current.RemoteKey = &key
		current.RemoteID = auth.RemoteID
	}
	if auth.Sender != "" {
		current.Sender = auth.Sender
	}
	current.NextAction = auth.NextAction
	current.LastError = ""
	current.Status = "awaiting_auth"
	if auth.Ready {
		current.Status = "connected"
		if current.Sender == "" {
			current.Status = "awaiting_pairing"
			current.NextAction = actionJSON("pairing", auth.Config["pairing_code"], "向机器人私聊发送 /connect 后面的配对码")
		}
	}
	e = s.db.Save(&current).Error
	return current, e
}
func actionJSON(kind, value, description string) string {
	b, _ := json.Marshal(map[string]string{"kind": kind, "value": value, "description": description})
	return string(b)
}
func publicError(e error) string {
	var send *SendError
	if errors.As(e, &send) {
		return send.Message
	}
	return "连接请求失败，请检查网络、凭据和平台权限"
}
func (s *Service) Disconnect(user, id string) (models.ConnectConnection, error) {
	s.mu.Lock()
	c, e := s.Get(user, id)
	if e != nil {
		s.mu.Unlock()
		return c, e
	}
	if c.DesiredState == "disconnected" {
		s.mu.Unlock()
		return c, nil
	}
	var active []models.ConnectTurn
	e = s.db.Transaction(func(tx *gorm.DB) error {
		if e := tx.Where("connection_id = ? AND status = ?", id, "running").Find(&active).Error; e != nil {
			return e
		}
		c.DesiredState = "disconnected"
		c.Status = "disconnected"
		c.Generation++
		c.NextAction = ""
		if e := tx.Save(&c).Error; e != nil {
			return e
		}
		if e := tx.Model(&models.ConnectTurn{}).Where("connection_id = ? AND status IN ?", id, []string{"queued", "running"}).Updates(map[string]any{"status": "cancelled"}).Error; e != nil {
			return e
		}
		return tx.Model(&models.ConnectDelivery{}).Where("connection_id = ? AND status IN ?", id, []string{"pending", "retry_wait"}).Update("status", "revoked").Error
	})
	if e == nil {
		for key, cancel := range s.workers {
			if strings.HasPrefix(key, id+":") {
				cancel()
			}
		}
		for _, t := range active {
			if cancel := s.running[t.ID]; cancel != nil {
				cancel()
			}
		}
	}
	s.mu.Unlock()
	if e == nil && s.runner != nil {
		for _, t := range active {
			go s.runner.Cancel(t.RunID)
		}
	}
	return c, e
}
func (s *Service) Reconnect(ctx context.Context, user, id string, credentials Config) (models.ConnectConnection, error) {
	// Fence and cancel the old generation before replacing any credentials.
	if _, e := s.Disconnect(user, id); e != nil {
		return models.ConnectConnection{}, e
	}
	s.mu.Lock()
	c, e := s.Get(user, id)
	if e != nil {
		s.mu.Unlock()
		return c, e
	}
	cfg, e := s.open(c.ID, c.Secret)
	if e != nil {
		s.mu.Unlock()
		return c, e
	}
	// Only adapter-declared credential fields are accepted; transport/session fields are server-owned.
	for _, f := range s.adapters[c.Kind].Descriptor().Fields {
		if v := strings.TrimSpace(credentials[f.Key]); v != "" {
			cfg[f.Key] = v
		}
	}
	delete(cfg, "qrcode")
	delete(cfg, "bot_token")
	delete(cfg, "verify_code")
	cfg["pairing_code"] = uuid.NewString()
	cfg["pairing_expires"] = time.Now().Add(10 * time.Minute).Format(time.RFC3339)
	for key, cancel := range s.workers {
		if strings.HasPrefix(key, id+":") {
			cancel()
		}
	}
	c.Generation++
	c.DesiredState = "enabled"
	c.Status = "connecting"
	c.NextAction = ""
	c.LastError = ""
	c.Secret, e = s.seal(c.ID, cfg)
	if e == nil {
		e = s.db.Save(&c).Error
	}
	s.mu.Unlock()
	if e != nil {
		return c, e
	}
	return s.authenticate(ctx, c, cfg)
}
func (s *Service) Check(ctx context.Context, user, id string) (models.ConnectCheck, error) {
	c, e := s.Get(user, id)
	if e != nil {
		return models.ConnectCheck{}, e
	}
	key := fmt.Sprintf("%s:%d", id, c.Generation)
	s.mu.Lock()
	if pending := s.checks[key]; pending != nil {
		s.mu.Unlock()
		select {
		case <-ctx.Done():
			return models.ConnectCheck{}, ctx.Err()
		case <-pending.done:
			return pending.result, pending.err
		}
	}
	pending := &checkFlight{done: make(chan struct{})}
	s.checks[key] = pending
	s.mu.Unlock()
	result, err := s.check(ctx, c)
	s.mu.Lock()
	pending.result, pending.err = result, err
	delete(s.checks, key)
	close(pending.done)
	s.mu.Unlock()
	return result, err
}
func (s *Service) check(ctx context.Context, c models.ConnectConnection) (models.ConnectCheck, error) {
	id := c.ID
	var e error
	// One recent check is reused; checks never start a listener or authenticate a new identity.
	var previous models.ConnectCheck
	if e = s.db.Where("connection_id = ? AND generation = ? AND created_at > ?", id, c.Generation, time.Now().Add(-5*time.Second)).Order("created_at DESC").First(&previous).Error; e == nil {
		return previous, nil
	}
	cfg, e := s.open(c.ID, c.Secret)
	if e != nil {
		return previous, e
	}
	ctx, cancel := context.WithTimeout(ctx, 12*time.Second)
	defer cancel()
	results, e := s.adapters[c.Kind].Check(ctx, cfg)
	results = append(results, Diagnostic{Name: "inbound", Status: "unknown", Detail: "检测不发送消息；接收状态以实际入站记录为准"}, Diagnostic{Name: "delivery", Status: "unknown", Detail: "检测不发送测试消息"})
	status := "passed"
	if e != nil {
		results = append(results, Diagnostic{Name: "transport", Status: "failed", Detail: publicError(e)})
		status = "failed"
	}
	for _, r := range results {
		if r.Status == "unknown" && status == "passed" {
			status = "partial"
		}
		if r.Status == "failed" {
			status = "failed"
		}
	}
	b, _ := json.Marshal(results)
	check := models.ConnectCheck{ID: newID("check_"), ConnectionID: id, Generation: c.Generation, Status: status, Results: string(b), CreatedAt: time.Now()}
	s.mu.Lock()
	defer s.mu.Unlock()
	// A check may finish after deletion; never recreate diagnostics for a removed connection.
	if _, err := s.Get(c.UserID, id); err != nil {
		return models.ConnectCheck{}, err
	}
	e = s.db.Transaction(func(tx *gorm.DB) error {
		if err := tx.Create(&check).Error; err != nil {
			return err
		}
		return tx.Model(&models.ConnectConnection{}).Where("id = ? AND generation = ?", id, c.Generation).Update("last_check_at", check.CreatedAt).Error
	})
	return check, e
}
func (s *Service) GetCheck(user, id, checkID string) (models.ConnectCheck, error) {
	if _, e := s.Get(user, id); e != nil {
		return models.ConnectCheck{}, e
	}
	var c models.ConnectCheck
	e := s.db.First(&c, "id = ? AND connection_id = ?", checkID, id).Error
	if errors.Is(e, gorm.ErrRecordNotFound) {
		e = ErrNotFound
	}
	return c, e
}
func (s *Service) Detail(user, id string) (map[string]any, error) {
	c, e := s.Get(user, id)
	if e != nil {
		return nil, e
	}
	sources := []models.ConnectSource{}
	turns := []models.ConnectTurn{}
	checks := []models.ConnectCheck{}
	deliveries := []models.ConnectDelivery{}
	for _, query := range []struct {
		dest  any
		order string
		limit int
	}{{&sources, "created_at DESC", 50}, {&turns, "created_at DESC", 30}, {&checks, "created_at DESC", 5}, {&deliveries, "created_at DESC", 30}} {
		if e = s.db.Where("connection_id = ?", id).Order(query.order).Limit(query.limit).Find(query.dest).Error; e != nil {
			return nil, e
		}
	}
	return map[string]any{"connection": c, "sources": sources, "turns": turns, "checks": checks, "deliveries": deliveries}, nil
}

// Accept is the only ingress into source routing. The connection and sender are verified first.
func (s *Service) Accept(id string, generation uint64, in Inbound) (models.ConnectTurn, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	var out models.ConnectTurn
	if in.Cursor != "" && in.MessageID == "" {
		return out, s.saveCursor(id, generation, in.Cursor)
	}
	if in.MessageID == "" || in.Sender == "" || in.Peer == "" || len(in.Text) > 128*1024 || len(in.MessageID) > 256 {
		return out, ErrInvalid
	}
	e := s.db.Transaction(func(tx *gorm.DB) error {
		var c models.ConnectConnection
		if err := tx.First(&c, "id = ?", id).Error; err != nil {
			return ErrNotFound
		}
		if c.DesiredState != "enabled" || c.Generation != generation {
			return ErrDisconnected
		}
		cfg, err := s.open(id, c.Secret)
		if err != nil {
			return err
		}
		if c.Sender == "" {
			expiry, _ := time.Parse(time.RFC3339, cfg["pairing_expires"])
			want := "/connect " + cfg["pairing_code"]
			if time.Now().After(expiry) || subtle.ConstantTimeCompare([]byte(strings.TrimSpace(in.Text)), []byte(want)) != 1 {
				return ErrForbidden
			}
			c.Sender = in.Sender
			c.NextAction = ""
			c.Status = "connected"
			return tx.Save(&c).Error
		}
		if in.Sender != c.Sender {
			return ErrForbidden
		}
		sourceID := "src_" + hash([]string{c.UserID, c.Kind, c.ID, c.RemoteID, in.Peer, in.Thread, in.Sender})
		err = tx.First(&out, "source_id = ? AND external_id = ?", sourceID, in.MessageID).Error
		digest := hash([]any{in.Text, in.Unsupported})
		if err == nil {
			if out.PayloadHash != digest {
				return ErrConflict
			}
			return nil
		}
		if !errors.Is(err, gorm.ErrRecordNotFound) {
			return err
		}
		var source models.ConnectSource
		err = tx.First(&source, "id = ?", sourceID).Error
		if errors.Is(err, gorm.ErrRecordNotFound) {
			source = models.ConnectSource{ID: sourceID, ConnectionID: id, UserID: c.UserID, Peer: in.Peer, Sender: in.Sender, Thread: in.Thread, Epoch: 1}
		} else if err != nil {
			return err
		}
		if in.ContextToken != "" {
			source.ContextSecret, err = s.seal(sourceID, Config{"context_token": in.ContextToken})
			if err != nil {
				return err
			}
		}
		text := strings.TrimSpace(in.Text)
		control := in.Unsupported || text == "/new" || text == "/stop" || text == "/status" || text == "/help"
		if !control && source.ConversationID != "" {
			var existing int64
			if err = tx.Model(&models.Conversation{}).Where("id = ? AND user_id = ?", source.ConversationID, c.UserID).Count(&existing).Error; err != nil {
				return err
			}
			// A user may have deleted this conversation in the workbench. The next message starts fresh.
			if existing == 0 {
				source.ConversationID = ""
				source.Epoch++
			}
		}
		if source.ConversationID == "" && !control {
			conv := models.Conversation{ID: newID("conv_"), UserID: c.UserID, AgentID: "super_chat", SourceID: sourceID, Title: c.Name + " · " + string([]rune(text)[:min(30, len([]rune(text)))])}
			if err = tx.Create(&conv).Error; err != nil {
				return err
			}
			source.ConversationID = conv.ID
		}
		out = models.ConnectTurn{ID: newID("turn_"), SourceID: sourceID, ExternalID: in.MessageID, PayloadHash: digest, ConnectionID: id, Generation: generation, UserID: c.UserID, ConversationID: source.ConversationID, RunID: newID("run_"), RoleID: EffectiveRole(c.RoleID), Text: in.Text, Status: "queued"}
		if control {
			out.Status = "completed"
			reply := "当前没有正在执行的任务。"
			if in.Unsupported {
				reply = "当前 Connect 支持文字私聊，请使用文字描述你的请求。"
			}
			if text == "/new" {
				source.Epoch++
				source.ConversationID = ""
				reply = "已为你开启新话题。想聊点什么？\n人设和长期记忆已保留。旧任务仍会完成；如需取消，请发送 /stop。"
			}
			if text == "/help" {
				reply = "/new：下一条普通消息开始新会话，保留人设和长期记忆。\n/status：查看任务状态。\n/stop：停止本来源待处理和执行中的任务。\n/help：查看指令。\n在工作台 Connect 中点击“人设”可切换当前连接的人设。"
			}
			if text == "/status" {
				var active models.ConnectTurn
				if tx.Where("source_id = ? AND status IN ?", sourceID, []string{"queued", "running"}).Order("created_at ASC").First(&active).Error == nil {
					reply = "任务状态：" + active.Status
				}
			}
			if text == "/stop" {
				var active []models.ConnectTurn
				if err = tx.Where("source_id = ? AND status IN ?", sourceID, []string{"queued", "running"}).Find(&active).Error; err != nil {
					return err
				}
				for _, t := range active {
					if cancel := s.running[t.ID]; cancel != nil {
						cancel()
					}
					if s.runner != nil {
						go s.runner.Cancel(t.RunID)
					}
				}
				if err = tx.Model(&models.ConnectTurn{}).Where("source_id = ? AND status IN ?", sourceID, []string{"queued", "running"}).Update("status", "cancelled").Error; err != nil {
					return err
				}
				if err = tx.Model(&models.ConnectDelivery{}).Where("source_id = ? AND status IN ?", sourceID, []string{"pending", "retry_wait"}).Update("status", "revoked").Error; err != nil {
					return err
				}
				reply = "已请求停止当前任务。"
			}
			if err = tx.Create(&models.ConnectDelivery{ID: out.ID + ":0", TurnID: out.ID, ConnectionID: id, SourceID: sourceID, Generation: generation, Text: reply, Status: "pending"}).Error; err != nil {
				return err
			}
		}
		if err = tx.Save(&source).Error; err != nil {
			return err
		}
		if err = tx.Create(&out).Error; err != nil {
			return err
		}
		now := time.Now()
		return tx.Model(&c).Updates(map[string]any{"last_inbound_at": now, "status": "connected"}).Error
	})
	return out, e
}
func (s *Service) saveCursor(id string, generation uint64, cursor string) error {
	var c models.ConnectConnection
	if e := s.db.First(&c, "id = ?", id).Error; e != nil {
		return e
	}
	if c.Generation != generation || c.DesiredState != "enabled" {
		return ErrDisconnected
	}
	cfg, e := s.open(id, c.Secret)
	if e != nil {
		return e
	}
	cfg["cursor"] = cursor
	secret, e := s.seal(id, cfg)
	if e != nil {
		return e
	}
	return s.db.Model(&c).Update("secret", secret).Error
}
