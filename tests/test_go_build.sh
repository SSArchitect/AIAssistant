#!/bin/bash
# Go gateway build and vet checks
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR/gateway"

echo "=== Go Gateway Tests ==="

echo "[1/3] go vet..."
go vet ./...
echo "  PASS"

echo "[2/3] go build..."
go build -o /dev/null ./cmd/server/
echo "  PASS"

echo "[3/3] Checking for compilation issues..."
# Build all packages
go build ./...
echo "  PASS"

echo ""
echo "All Go checks passed!"
