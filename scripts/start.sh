#!/bin/bash
#
# Agent Assistant - Service Startup Script
#
# Usage:
#   ./scripts/start.sh          # Start all services (default)
#   ./scripts/start.sh start    # Same as above
#   ./scripts/start.sh stop     # Stop all services
#   ./scripts/start.sh restart  # Restart all services
#   ./scripts/start.sh status   # Check service status
#   ./scripts/start.sh logs     # Tail logs
#
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

# --- Configuration ---
AGENT_HOST="0.0.0.0"
AGENT_PORT=9090
GATEWAY_PORT=8080
PID_DIR="$PROJECT_DIR/.pids"
LOG_DIR="$PROJECT_DIR/logs"
GATEWAY_BIN="$PROJECT_DIR/gateway/gateway"
HEALTH_TIMEOUT=30

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# --- Helper Functions ---

log_info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

ensure_dirs() {
    mkdir -p "$PID_DIR" "$LOG_DIR" "$PROJECT_DIR/data"
}

is_running() {
    local pid_file="$PID_DIR/$1.pid"
    if [ -f "$pid_file" ]; then
        local pid
        pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
        # Stale pid file
        rm -f "$pid_file"
    fi
    return 1
}

get_pid() {
    local pid_file="$PID_DIR/$1.pid"
    if [ -f "$pid_file" ]; then
        cat "$pid_file"
    fi
}

wait_for_health() {
    local name=$1
    local url=$2
    local timeout=$3

    for i in $(seq 1 "$timeout"); do
        if curl -sf "$url" > /dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}

# --- Build ---

build_gateway() {
    log_info "Building Go Gateway..."
    cd "$PROJECT_DIR/gateway"
    if go build -o "$GATEWAY_BIN" ./cmd/server/ 2>&1; then
        log_ok "Gateway built successfully"
    else
        log_error "Gateway build failed"
        exit 1
    fi
    cd "$PROJECT_DIR"
}

# --- Start ---

start_agent() {
    if is_running agent; then
        log_warn "Agent Engine is already running (PID $(get_pid agent))"
        return 0
    fi

    log_info "Starting Agent Engine on :${AGENT_PORT}..."
    cd "$PROJECT_DIR"
    python3 -m uvicorn agent.main:app \
        --host "$AGENT_HOST" \
        --port "$AGENT_PORT" \
        >> "$LOG_DIR/agent.log" 2>&1 &
    local pid=$!
    echo "$pid" > "$PID_DIR/agent.pid"

    log_info "Waiting for Agent Engine to be ready..."
    if wait_for_health "agent" "http://localhost:${AGENT_PORT}/agent/health" "$HEALTH_TIMEOUT"; then
        log_ok "Agent Engine started (PID $pid)"
    else
        log_error "Agent Engine failed to start within ${HEALTH_TIMEOUT}s"
        log_error "Check logs: $LOG_DIR/agent.log"
        kill "$pid" 2>/dev/null || true
        rm -f "$PID_DIR/agent.pid"
        return 1
    fi
}

start_gateway() {
    if is_running gateway; then
        log_warn "Gateway is already running (PID $(get_pid gateway))"
        return 0
    fi

    # Build if binary doesn't exist or source is newer
    if [ ! -f "$GATEWAY_BIN" ] || \
       [ "$(find "$PROJECT_DIR/gateway" -name '*.go' -newer "$GATEWAY_BIN" 2>/dev/null | head -1)" ]; then
        build_gateway
    fi

    log_info "Starting Gateway on :${GATEWAY_PORT}..."
    cd "$PROJECT_DIR"
    PROJECT_ROOT="$PROJECT_DIR" "$GATEWAY_BIN" >> "$LOG_DIR/gateway.log" 2>&1 &
    local pid=$!
    echo "$pid" > "$PID_DIR/gateway.pid"
    cd "$PROJECT_DIR"

    sleep 1
    if is_running gateway; then
        log_ok "Gateway started (PID $pid)"
    else
        log_error "Gateway failed to start"
        log_error "Check logs: $LOG_DIR/gateway.log"
        return 1
    fi
}

do_start() {
    ensure_dirs

    echo ""
    echo "========================================="
    echo "  Agent Assistant - Starting Services"
    echo "========================================="
    echo ""

    start_agent
    start_gateway

    echo ""
    echo "========================================="
    log_ok "All services are running!"
    echo ""
    echo "  Web UI:   http://localhost:${GATEWAY_PORT}"
    echo "  Agent:    http://localhost:${AGENT_PORT}"
    echo "  Logs:     $LOG_DIR/"
    echo ""
    echo "  Stop:     ./scripts/start.sh stop"
    echo "  Status:   ./scripts/start.sh status"
    echo "  Logs:     ./scripts/start.sh logs"
    echo "========================================="
    echo ""
}

# --- Stop ---

stop_service() {
    local name=$1
    if is_running "$name"; then
        local pid
        pid=$(get_pid "$name")
        log_info "Stopping $name (PID $pid)..."
        kill "$pid" 2>/dev/null
        # Wait for graceful shutdown
        for i in $(seq 1 10); do
            if ! kill -0 "$pid" 2>/dev/null; then
                log_ok "$name stopped"
                rm -f "$PID_DIR/$name.pid"
                return 0
            fi
            sleep 0.5
        done
        # Force kill
        log_warn "$name didn't stop gracefully, force killing..."
        kill -9 "$pid" 2>/dev/null || true
        rm -f "$PID_DIR/$name.pid"
        log_ok "$name force stopped"
    else
        log_info "$name is not running"
    fi
}

do_stop() {
    echo ""
    echo "Stopping Agent Assistant..."
    echo ""
    stop_service gateway
    stop_service agent
    echo ""
    log_ok "All services stopped"
    echo ""
}

# --- Status ---

do_status() {
    echo ""
    echo "Agent Assistant - Service Status"
    echo "================================"
    echo ""

    # Agent
    if is_running agent; then
        local agent_pid
        agent_pid=$(get_pid agent)
        log_ok "Agent Engine   : running (PID $agent_pid, port $AGENT_PORT)"
    else
        log_error "Agent Engine   : stopped"
    fi

    # Gateway
    if is_running gateway; then
        local gw_pid
        gw_pid=$(get_pid gateway)
        log_ok "Gateway        : running (PID $gw_pid, port $GATEWAY_PORT)"
    else
        log_error "Gateway        : stopped"
    fi

    # Health checks
    echo ""
    echo "Health Checks:"
    if curl -sf "http://localhost:${AGENT_PORT}/agent/health" > /dev/null 2>&1; then
        local skills
        skills=$(curl -sf "http://localhost:${AGENT_PORT}/agent/health" | python3 -c "import sys,json; print(json.load(sys.stdin).get('skills_count', '?'))" 2>/dev/null || echo "?")
        log_ok "Agent health   : OK ($skills skills loaded)"
    else
        log_error "Agent health   : UNREACHABLE"
    fi

    if curl -sf "http://localhost:${GATEWAY_PORT}/api/health" > /dev/null 2>&1; then
        log_ok "Gateway health : OK"
    else
        log_error "Gateway health : UNREACHABLE"
    fi

    echo ""
}

# --- Logs ---

do_logs() {
    if [ ! -d "$LOG_DIR" ]; then
        log_warn "No logs directory found"
        exit 1
    fi

    echo "=== Tailing logs (Ctrl+C to stop) ==="
    echo ""
    tail -f "$LOG_DIR/agent.log" "$LOG_DIR/gateway.log" 2>/dev/null
}

# --- Main ---

CMD="${1:-start}"

case "$CMD" in
    start)
        do_start
        ;;
    stop)
        do_stop
        ;;
    restart)
        do_stop
        sleep 1
        do_start
        ;;
    status)
        do_status
        ;;
    logs)
        do_logs
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        exit 1
        ;;
esac
