package config

import (
	"os"
	"time"

	"gopkg.in/yaml.v3"
)

type Config struct {
	Server   ServerConfig   `yaml:"server"`
	Agent    AgentConfig    `yaml:"agent"`
	Database DatabaseConfig `yaml:"database"`
	Pulse    PulseConfig    `yaml:"pulse"`
}

type ServerConfig struct {
	Host string `yaml:"host"`
	Port int    `yaml:"port"`
}

type AgentConfig struct {
	URL            string `yaml:"url"`
	TimeoutSeconds int    `yaml:"timeout"` // seconds
}

func (a AgentConfig) TimeoutDuration() time.Duration {
	if a.TimeoutSeconds <= 0 {
		return 1800 * time.Second
	}
	return time.Duration(a.TimeoutSeconds) * time.Second
}

type DatabaseConfig struct {
	Path string `yaml:"path"`
}

type PulseConfig struct {
	ConsumptionTTLDays int `yaml:"consumption_ttl_days"`
}

func (p PulseConfig) ConsumptionTTLDuration() time.Duration {
	if p.ConsumptionTTLDays <= 0 {
		return 7 * 24 * time.Hour
	}
	return time.Duration(p.ConsumptionTTLDays) * 24 * time.Hour
}

func Load(path string) (*Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}

	cfg := &Config{
		Server:   ServerConfig{Host: "0.0.0.0", Port: 8080},
		Agent:    AgentConfig{URL: "http://localhost:9090", TimeoutSeconds: 1800},
		Database: DatabaseConfig{Path: "./data/assistant.db"},
		Pulse:    PulseConfig{ConsumptionTTLDays: 7},
	}

	if err := yaml.Unmarshal(data, cfg); err != nil {
		return nil, err
	}

	return cfg, nil
}
