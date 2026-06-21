#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

echo "=== Agent Assistant - Development Mode ==="

# Cleanup on exit
cleanup() {
    echo ""
    echo "Shutting down..."
    kill $AGENT_PID 2>/dev/null || true
    kill $GATEWAY_PID 2>/dev/null || true
    exit 0
}
trap cleanup SIGINT SIGTERM

# Start Python Agent Engine
echo "Starting Python Agent Engine on :9090..."
cd "$PROJECT_DIR"
python3 -m uvicorn agent.main:app --host 0.0.0.0 --port 9090 --reload &
AGENT_PID=$!

# Wait for agent to be ready
echo "Waiting for Agent Engine to start..."
AGENT_READY=false
for i in $(seq 1 30); do
    if curl -s http://localhost:9090/agent/health > /dev/null 2>&1; then
        echo "Agent Engine is ready!"
        AGENT_READY=true
        break
    fi
    sleep 1
done

if [ "$AGENT_READY" = false ]; then
    echo "WARNING: Agent Engine failed to start within 30 seconds!"
    echo "Check logs above for errors. Starting Gateway anyway..."
fi

# Start Go Gateway
echo "Starting Go Gateway on :8080..."
cd "$PROJECT_DIR/gateway"
PROJECT_ROOT="$PROJECT_DIR" go run ./cmd/server/ &
GATEWAY_PID=$!

echo ""
echo "=== Agent Assistant is running ==="
echo "  Web UI:  http://localhost:8080"
echo "  Agent:   http://localhost:9090"
echo "  Press Ctrl+C to stop"
echo ""

# Wait for either process to exit
wait
