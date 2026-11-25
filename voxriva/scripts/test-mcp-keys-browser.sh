#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export VOXRIVA_TEST_PROJECT="voxriva-test-mcp-keys-$$"
export VOXRIVA_TEST_EMAIL="mcp-browser@example.test"
export VOXRIVA_TEST_PASSWORD="Synthetic MCP browser password"
export VOXRIVA_TEST_URL="http://127.0.0.1:${VOXRIVA_MCP_KEYS_PORT:-18183}"
export VOXRIVA_MCP_KEYS_IMAGE="${VOXRIVA_MCP_KEYS_IMAGE:-voxriva-mcp:keys-browser}"
mcp_browser_results=$(mktemp -d /private/tmp/voxriva-mcp-keys-browser.XXXXXX)
compose=(docker compose -p "$VOXRIVA_TEST_PROJECT" -f compose.mcp-keys-test.yaml)
cleanup() {
  result=$?
  if (( result != 0 )); then "${compose[@]}" logs --tail=30 >&2 || true; fi
  "${compose[@]}" down --volumes --remove-orphans >/dev/null
  echo "Browser artifacts: $mcp_browser_results"
}
trap cleanup EXIT
npm --prefix frontend run build
docker build -f Dockerfile.mcp -t "$VOXRIVA_MCP_KEYS_IMAGE" .
"${compose[@]}" up -d --wait --wait-timeout 150 api
for ((attempt=0; attempt<30; attempt++)); do
  if curl --fail --silent "$VOXRIVA_TEST_URL/health/live" >/dev/null; then break; fi
  sleep 1
done
curl --fail --silent "$VOXRIVA_TEST_URL/health/live" >/dev/null
"${compose[@]}" exec -T api python - <<'PY'
import asyncio
from backend.app.features.identity.bootstrap import bootstrap
from backend.app.features.identity.schemas import NewAccount
from backend.app.infrastructure.settings import Settings
asyncio.run(bootstrap(Settings().database_url, NewAccount(email="mcp-browser@example.test", password="Synthetic MCP browser password")))
PY
npm --prefix frontend run test:e2e -- e2e/30-mcp-keys.spec.ts --project=chromium --output="$mcp_browser_results"
