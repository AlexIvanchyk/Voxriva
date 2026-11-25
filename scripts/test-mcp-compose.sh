#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# All names are isolated from the application and other test agents' stacks.
mcp_project="voxriva-mcp-smoke-${RANDOM}-${RANDOM}"
compose=(docker compose -p "$mcp_project" -f compose.mcp.smoke.yaml)
cleanup() { "${compose[@]}" down --volumes --remove-orphans >/dev/null; }
trap cleanup EXIT
docker build -f Dockerfile.mcp -t voxriva-mcp:authoring-check .
"${compose[@]}" up -d --wait api mcp
"${compose[@]}" exec -T mcp python - < scripts/mcp-smoke.py
