// Package connect implements source-isolated messaging for the Super Chat runtime.
package connect

import (
	"context"
	"errors"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/models"
)

const ProtocolVersion = "connect.v1"

var (
	ErrNotFound     = errors.New("connection not found")
	ErrForbidden    = errors.New("source is not bound to this account")
	ErrDisconnected = errors.New("connection is disconnected")
	ErrConflict     = errors.New("idempotency or identity conflict")
	ErrUnsupported  = errors.New("connector is not supported")
	ErrInvalid      = errors.New("invalid request")
)

type Config map[string]string
type Field struct {
	Key      string `json:"key"`
	Label    string `json:"label"`
	Secret   bool   `json:"secret"`
	Required bool   `json:"required"`
}
type Descriptor struct {
	ID      string   `json:"id"`
	Name    string   `json:"name"`
	Auth    string   `json:"auth"`
	Fields  []Field  `json:"fields"`
	Input   []string `json:"input"`
	Output  []string `json:"output"`
	HelpURL string   `json:"help_url,omitempty"`
}
type Diagnostic struct {
	Name   string `json:"name"`
	Status string `json:"status"`
	Detail string `json:"detail,omitempty"`
}
type AuthResult struct {
	Config                       Config
	RemoteID, Sender, NextAction string
	Ready                        bool
}
type Inbound struct {
	MessageID, Sender, Peer, Thread, Text, ContextToken, Cursor string
	Unsupported                                                 bool
}
type Outgoing struct{ DeliveryID, Peer, Text, ContextToken string }
type Adapter interface {
	Descriptor() Descriptor
	Authenticate(context.Context, Config) (AuthResult, error)
	Check(context.Context, Config) ([]Diagnostic, error)
	Listen(context.Context, Config, func(Inbound) error, func()) error
	Send(context.Context, Config, Outgoing) (string, error)
}
type Runner interface {
	Run(context.Context, models.ConnectTurn, func(bridge.RunEvent)) (*bridge.ChatResponse, error)
	Cancel(string) error
}
type Role struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

// RoleProvider returns only enabled roles available to this account.
type RoleProvider interface {
	ListRoles(context.Context, string) ([]Role, error)
}

func EffectiveRole(id string) string {
	if id == "" {
		return "default"
	}
	return id
}

type CreateRequest struct {
	Kind        string `json:"kind"`
	Name        string `json:"name"`
	RequestID   string `json:"request_id"`
	RoleID      string `json:"role_id,omitempty"`
	Note        string `json:"note,omitempty"`
	Credentials Config `json:"credentials"`
}

// SendError distinguishes a known rejection from an ambiguous network result.
type SendError struct {
	Message           string
	Retryable         bool
	Unknown           bool
	Timeout           bool
	RetryAfterSeconds int
}

func (e *SendError) Error() string { return e.Message }
