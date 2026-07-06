.PHONY: dev start stop restart status logs build clean install test test-py test-go collect-search-evals eval-search eval-search-compare eval-search-trace eval-search-live

# ===== Production =====

# Start all services (background, with logs)
start:
	./scripts/start.sh start

# Stop all services
stop:
	./scripts/start.sh stop

# Restart all services
restart:
	./scripts/start.sh restart

# Check service status
status:
	./scripts/start.sh status

# Tail service logs
logs:
	./scripts/start.sh logs

# ===== Development =====

# Start both services in foreground (dev mode with hot reload)
dev:
	./scripts/dev.sh

# Start Agent Engine only (foreground, hot reload)
dev-agent:
	python3 -m uvicorn agent.main:app --host 0.0.0.0 --port 9090 --reload

# Start Gateway only (foreground)
dev-gateway:
	cd gateway && PROJECT_ROOT=$(CURDIR) go run ./cmd/server/

# ===== Build =====

# Build Go Gateway binary
build:
	cd gateway && go build -o gateway ./cmd/server/

# Install Python dependencies
install:
	pip3 install -r agent/requirements.txt

# ===== Test =====

# Run all tests (Go + Python)
test:
	./scripts/test.sh

# Run Python tests only
test-py:
	python3 -m pytest tests/ -v --tb=short

# Run Go checks only
test-go:
	cd gateway && go vet ./... && go test ./... && go build -o /dev/null ./cmd/server/

# Run deterministic offline search quality evals
eval-search:
	python3 scripts/eval_search.py --mode offline

# Collect trace-derived cases and query bank from local/server traces
collect-search-evals:
	python3 scripts/collect_search_eval_cases.py

# Compare offline rewrite against original-query-only baseline
eval-search-compare:
	python3 scripts/eval_search.py --mode offline --compare-original

# Run broader trace-derived offline search quality evals
eval-search-trace:
	python3 scripts/eval_search.py --cases evals/search/trace_cases.json --mode offline

# Run live search quality evals against configured providers
eval-search-live:
	python3 scripts/eval_search.py --mode live --endpoint http://127.0.0.1:9090/agent/search

# ===== Misc =====

# Clean build artifacts and data
clean:
	rm -f gateway/gateway
	rm -rf data/ logs/ .pids/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
