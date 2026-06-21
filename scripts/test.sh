#!/bin/bash
# Full test suite runner
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

echo "========================================"
echo "  Agent Assistant - Test Suite"
echo "========================================"
echo ""

FAILED=0

# --- Go Tests ---
echo "--- Go Gateway Checks ---"
cd "$PROJECT_DIR/gateway"

echo "[Go] Running go vet..."
if go vet ./... 2>&1; then
    echo "  PASS: go vet"
else
    echo "  FAIL: go vet"
    FAILED=1
fi

echo "[Go] Running go test..."
if go test ./... 2>&1; then
    echo "  PASS: go test"
else
    echo "  FAIL: go test"
    FAILED=1
fi

echo "[Go] Running go build..."
if go build -o /dev/null ./cmd/server/ 2>&1; then
    echo "  PASS: go build"
else
    echo "  FAIL: go build"
    FAILED=1
fi

echo ""

# --- Python Tests ---
cd "$PROJECT_DIR"
echo "--- Python Agent Tests ---"

echo "[Python] Running pytest..."
if python3 -m pytest tests/ -v --tb=short 2>&1; then
    echo ""
    echo "  PASS: pytest"
else
    echo ""
    echo "  FAIL: pytest"
    FAILED=1
fi

echo ""

# --- Web Checks ---
echo "--- Web UI Checks ---"

if command -v node >/dev/null 2>&1; then
    echo "[Web] Checking JavaScript syntax..."
    if node --check web/static/js/app.js 2>&1; then
        echo "  PASS: app.js syntax"
    else
        echo "  FAIL: app.js syntax"
        FAILED=1
    fi
else
    echo "  SKIP: node not found, skipping JavaScript syntax check"
fi

echo ""

# --- Config Validation ---
echo "--- Config Validation ---"

echo "[Config] Checking config.yaml syntax..."
if python3 -c "import yaml; yaml.safe_load(open('config/config.yaml'))" 2>&1; then
    echo "  PASS: config.yaml is valid YAML"
else
    echo "  FAIL: config.yaml has syntax errors"
    FAILED=1
fi

echo "[Config] Checking Python imports..."
if python3 -c "
from agent.config import settings
from agent.skills.registry import SkillRegistry
from agent.orchestrator.engine import AgentEngine
from agent.llm.factory import create_provider
from agent.llm.base import LLMProvider, LLMMessage
from agent.skills.base import Skill, SkillResult
print('  All imports OK')
" 2>&1; then
    echo "  PASS: imports"
else
    echo "  FAIL: import errors"
    FAILED=1
fi

echo "[Config] Checking skill discovery..."
if python3 -c "
from agent.skills.registry import SkillRegistry
reg = SkillRegistry()
reg.auto_discover('agent.skills.builtin')
skills = reg.list_skills()
names = {s.metadata().name for s in skills}
expected = {'echo', 'datetime', 'calculator'}
missing = expected - names
if missing:
    print(f'  FAIL: Missing skills: {missing}')
    exit(1)
print(f'  Found {len(skills)} skills: {names}')
" 2>&1; then
    echo "  PASS: skill discovery"
else
    echo "  FAIL: skill discovery"
    FAILED=1
fi

echo ""

# --- Summary ---
echo "========================================"
if [ $FAILED -eq 0 ]; then
    echo "  ALL TESTS PASSED"
else
    echo "  SOME TESTS FAILED"
fi
echo "========================================"

exit $FAILED
