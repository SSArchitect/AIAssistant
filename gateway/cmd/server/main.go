package main

import (
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/aan/agent-assistant-gateway/internal/config"
	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/handlers"
	"github.com/aan/agent-assistant-gateway/internal/middleware"
	"github.com/gin-gonic/gin"
)

func main() {
	// Resolve project root: gateway binary lives in gateway/, project root is one level up
	execPath, _ := os.Executable()
	projectRoot := filepath.Dir(filepath.Dir(execPath))
	// For `go run`, executable is in a temp dir, so fall back to PROJECT_ROOT env or cwd parent
	if os.Getenv("PROJECT_ROOT") != "" {
		projectRoot = os.Getenv("PROJECT_ROOT")
	} else if _, err := os.Stat(filepath.Join(projectRoot, "config", "config.yaml")); err != nil {
		// Try cwd parent (when running from gateway/)
		cwd, _ := os.Getwd()
		if _, err := os.Stat(filepath.Join(cwd, "config", "config.yaml")); err == nil {
			projectRoot = cwd
		} else {
			projectRoot = filepath.Dir(cwd)
		}
	}
	slog.Info("Project root", "path", projectRoot)

	// Load config
	configPath := filepath.Join(projectRoot, "config", "config.yaml")
	if p := os.Getenv("CONFIG_PATH"); p != "" {
		configPath = p
	}

	cfg, err := config.Load(configPath)
	if err != nil {
		slog.Warn("Could not load config file, using defaults", "error", err)
		cfg = &config.Config{
			Server:   config.ServerConfig{Host: "0.0.0.0", Port: 8080},
			Agent:    config.AgentConfig{URL: "http://localhost:9090", TimeoutSeconds: 1800},
			Database: config.DatabaseConfig{Path: "./data/assistant.db"},
		}
	}

	// Resolve relative paths against project root
	dbPath := cfg.Database.Path
	if !filepath.IsAbs(dbPath) {
		dbPath = filepath.Join(projectRoot, dbPath)
	}

	// Init database
	if err := database.Init(dbPath); err != nil {
		slog.Error("Failed to initialize database", "error", err)
		os.Exit(1)
	}
	slog.Info("Database initialized", "path", dbPath)

	// Init agent client
	agentClient := bridge.NewAgentClient(cfg.Agent.URL, cfg.Agent.TimeoutDuration())
	configSyncer := handlers.NewConfigSyncer(agentClient)

	// Init handlers
	chatHandler := handlers.NewChatHandler(agentClient, configSyncer)
	convHandler := handlers.NewConversationHandler(agentClient)
	accountHandler := handlers.NewAccountHandler()
	healthHandler := handlers.NewHealthHandler(agentClient)
	adminHandler := handlers.NewAdminHandler(agentClient, configSyncer)
	mediaHandler := handlers.NewMediaHandler()
	pulseHandler := handlers.NewPulseHandlerWithSyncer(agentClient, configSyncer)
	todoHandler := handlers.NewTodoHandler()
	driveHandler := handlers.NewDriveHandler(agentClient)
	evalHandler := handlers.NewEvalHandler(projectRoot, dbPath, cfg.Agent.URL)

	// Setup router
	r := gin.Default()
	r.Use(middleware.CORS())

	// API routes
	api := r.Group("/api")
	{
		api.GET("/health", healthHandler.Health)
		api.GET("/accounts", accountHandler.List)
		api.POST("/accounts", accountHandler.Create)
		api.POST("/accounts/login", accountHandler.Login)
		api.POST("/accounts/guest", accountHandler.Guest)
		api.POST("/chat", chatHandler.Chat)
		api.GET("/agents", chatHandler.ListAgents)
		api.GET("/roles", chatHandler.ListRoles)
		api.POST("/roles", chatHandler.CreateRole)
		api.PUT("/roles/:id", chatHandler.UpdateRole)
		api.DELETE("/roles/:id", chatHandler.DeleteRole)
		api.GET("/roles/:id/memories", chatHandler.ListRoleMemories)
		api.POST("/roles/:id/memories", chatHandler.CreateRoleMemory)
		api.PUT("/roles/:id/memories/:memory_id", chatHandler.UpdateRoleMemory)
		api.DELETE("/roles/:id/memories/:memory_id", chatHandler.DeleteRoleMemory)
		api.GET("/tools", chatHandler.ListTools)
		api.PUT("/tools/settings", chatHandler.UpdateToolSettings)
		api.GET("/runs", chatHandler.ListRuns)
		api.GET("/runs/:id", chatHandler.GetRun)
		api.POST("/runs/:id/cancel", chatHandler.CancelRun)
		api.GET("/evals/conversation", evalHandler.ConversationOverview)
		api.GET("/evals/conversation/candidates", evalHandler.ConversationCandidates)
		api.POST("/evals/conversation/collect", evalHandler.CollectConversationCandidates)
		api.PUT("/evals/conversation/candidates/:id", evalHandler.UpdateConversationCandidate)
		api.GET("/evals/conversation/runs/:id", evalHandler.ConversationRunReport)
		api.GET("/evals/conversation/cases", evalHandler.ConversationCases)
		api.POST("/evals/conversation/cases", evalHandler.ApproveConversationCase)
		api.PUT("/evals/conversation/cases/:id", evalHandler.UpdateConversationCase)
		api.DELETE("/evals/conversation/cases/:id", evalHandler.DeleteConversationCase)
		api.POST("/evals/conversation/run", evalHandler.RunConversationEval)
		api.POST("/aigc/image", chatHandler.GenerateImage)
		api.GET("/media/download", mediaHandler.Download)
		api.GET("/pulse", pulseHandler.Get)
		api.POST("/pulse/refresh", pulseHandler.Refresh)
		api.POST("/pulse/events", pulseHandler.RecordEvent)
		api.GET("/pulse/topics", pulseHandler.ListTopics)
		api.POST("/pulse/topics", pulseHandler.CreateTopic)
		api.PUT("/pulse/topics/:id", pulseHandler.UpdateTopic)
		api.DELETE("/pulse/topics/:id", pulseHandler.DeleteTopic)
		api.GET("/todos", todoHandler.List)
		api.GET("/todos/:id", todoHandler.Get)
		api.POST("/todos", todoHandler.Create)
		api.PUT("/todos/:id", todoHandler.Update)
		api.POST("/todos/:id/complete", todoHandler.Complete)
		api.DELETE("/todos/:id", todoHandler.Delete)
		api.GET("/todo-suggestions", todoHandler.ListSuggestions)
		api.POST("/todo-suggestions/refresh", todoHandler.RefreshSuggestions)
		api.POST("/todo-suggestions/:id/accept", todoHandler.AcceptSuggestion)
		api.POST("/todo-suggestions/:id/dismiss", todoHandler.DismissSuggestion)
		api.GET("/drive/tree", driveHandler.Tree)
		api.GET("/drive/items", driveHandler.List)
		api.POST("/drive/folders", driveHandler.CreateFolder)
		api.POST("/drive/files", driveHandler.CreateFile)
		api.GET("/drive/items/:id", driveHandler.Get)
		api.PUT("/drive/items/:id", driveHandler.Update)
		api.PUT("/drive/items/:id/share", driveHandler.Share)
		api.DELETE("/drive/items/:id", driveHandler.Delete)
		api.GET("/drive/items/:id/download", driveHandler.Download)
		api.GET("/drive/search", driveHandler.Search)
		api.POST("/drive/context", driveHandler.Context)
		api.GET("/conversations", convHandler.List)
		api.POST("/conversations", convHandler.Create)
		api.GET("/conversations/:id", convHandler.Get)
		api.DELETE("/conversations/:id", convHandler.Delete)

		// Admin routes
		api.POST("/admin/login", adminHandler.Login)

		admin := api.Group("/admin")
		admin.Use(adminHandler.RequireAuth())
		{
			admin.GET("/session", adminHandler.Session)
			admin.GET("/settings", adminHandler.GetSettings)
			admin.PUT("/settings", adminHandler.UpdateSettings)
			admin.GET("/costs", adminHandler.GetCosts)
			admin.GET("/accounts/:id/password", adminHandler.GetAccountPassword)
			admin.POST("/test-provider", adminHandler.TestProvider)
			admin.POST("/validate-provider", adminHandler.ValidateProvider)
			admin.POST("/list-models", adminHandler.ListModels)
		}
	}

	// Sync settings to agent on startup (non-blocking). Gateway and Agent can
	// start at the same time under launchd, so retry briefly if Agent is not up yet.
	go func() {
		synced := false
		for attempt := 1; attempt <= 6; attempt++ {
			if err := adminHandler.SyncToAgent(); err != nil {
				slog.Warn("Failed to sync settings to agent on startup", "attempt", attempt, "error", err)
			} else {
				synced = true
				slog.Info("Settings synced to agent", "attempt", attempt)
			}
			if attempt < 6 {
				time.Sleep(time.Duration(attempt*2) * time.Second)
			}
		}
		if !synced {
			slog.Warn("Failed to sync settings to agent after startup retries")
		}
	}()
	// Pulse generation is intentionally user-triggered only. The previous
	// scheduler fanned out across every account every 30 minutes and could
	// repeatedly regenerate incomplete/fallback feeds.

	// Serve static files (Web UI)
	webDir := filepath.Join(projectRoot, "web")
	r.Static("/static", filepath.Join(webDir, "static"))
	r.StaticFile("/", filepath.Join(webDir, "index.html"))
	r.StaticFile("/index.html", filepath.Join(webDir, "index.html"))
	r.StaticFile("/guest", filepath.Join(webDir, "index.html"))
	r.StaticFile("/guest/", filepath.Join(webDir, "index.html"))
	r.GET("/share/drive/:token", driveHandler.PublicShare)
	r.StaticFile("/admin", filepath.Join(webDir, "admin.html"))
	r.StaticFile("/admin/", filepath.Join(webDir, "admin.html"))
	r.StaticFile("/admin.html", filepath.Join(webDir, "admin.html"))

	// Start server
	addr := fmt.Sprintf("%s:%d", cfg.Server.Host, cfg.Server.Port)
	slog.Info("Starting gateway server", "addr", addr)
	if err := r.Run(addr); err != nil {
		slog.Error("Server failed", "error", err)
		os.Exit(1)
	}
}
