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

func Load(path string) (*Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}

	cfg := &Config{
		Server:   ServerConfig{Host: "0.0.0.0", Port: 8080},
		Agent:    AgentConfig{URL: "http://localhost:9090", TimeoutSeconds: 1800},
		Database: DatabaseConfig{Path: "./data/assistant.db"},
	}

	if err := yaml.Unmarshal(data, cfg); err != nil {
		return nil, err
	}

	return cfg, nil
}
