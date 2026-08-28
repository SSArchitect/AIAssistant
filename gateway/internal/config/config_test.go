package config

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestPulseConsumptionTTLConfig(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.yaml")
	if err := os.WriteFile(path, []byte(`
server:
  host: 127.0.0.1
  port: 8080
pulse:
  consumption_ttl_days: 3
`), 0o600); err != nil {
		t.Fatalf("write config: %v", err)
	}

	cfg, err := Load(path)
	if err != nil {
		t.Fatalf("load config: %v", err)
	}
	if got := cfg.Pulse.ConsumptionTTLDuration(); got != 3*24*time.Hour {
		t.Fatalf("expected three-day Pulse consumption TTL, got %s", got)
	}
	if got := (PulseConfig{}).ConsumptionTTLDuration(); got != 7*24*time.Hour {
		t.Fatalf("expected seven-day default Pulse consumption TTL, got %s", got)
	}
}
