#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root/voxriva"
suite=${1:?Supply chromium, cloud, crash, sdk, mcp or mcp-keys}
: "${CI_ARTIFACT_DIR:?Use an isolated CI artifact directory}"
mkdir -p "$CI_ARTIFACT_DIR/$suite"
export PLAYWRIGHT_JUNIT_OUTPUT_FILE="$CI_ARTIFACT_DIR/$suite/raw.xml"
browser_args=(--project=chromium '--reporter=line,junit' --output "$CI_ARTIFACT_DIR/$suite/private-traces")

run_mcp() (
    # Release callers supply an already-built, labelled candidate; PR builds use
    # the same Dockerfile and saved PostgreSQL/HTTP/stdio smoke scenario.
    image=${CI_MCP_IMAGE:-voxriva-mcp:ci-smoke}
    if [[ -z ${CI_MCP_IMAGE:-} ]]; then
        docker build --platform linux/amd64 -f Dockerfile.mcp -t "$image" .
    fi
    project="voxriva-mcp-smoke-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}-$$"
    override=$(mktemp)
    python3 - "$image" > "$override" <<'PY'
import json, sys
print(json.dumps({"services": {role: {"image": sys.argv[1]} for role in ("migrate", "api", "mcp")}}))
PY
    compose=(docker compose -p "$project" -f compose.mcp.smoke.yaml -f "$override")
    # shellcheck disable=SC2329 # Invoked by the EXIT trap in this subshell.
    cleanup_mcp() {
        "${compose[@]}" down --volumes --remove-orphans >/dev/null
        rm -f "$override"
    }
    trap cleanup_mcp EXIT
    "${compose[@]}" up -d --wait --wait-timeout 180 api mcp
    "${compose[@]}" exec -T mcp python - < scripts/mcp-smoke.py
)

run_mcp_keys() (
    # The saved local wrapper currently hardcodes /private/tmp (macOS). Keep
    # CI paths portable while running its unchanged Compose and browser tests.
    export VOXRIVA_TEST_PROJECT="voxriva-test-mcp-keys-${GITHUB_RUN_ID:-local}-$$"
    export VOXRIVA_TEST_EMAIL=mcp-browser@example.test
    export VOXRIVA_TEST_PASSWORD='Synthetic MCP browser password'
    export VOXRIVA_MCP_KEYS_PORT=${VOXRIVA_MCP_KEYS_PORT:-18183}
    export VOXRIVA_TEST_URL="http://127.0.0.1:$VOXRIVA_MCP_KEYS_PORT"
    export VOXRIVA_MCP_KEYS_IMAGE="voxriva-mcp:ci-keys"
    compose=(docker compose -p "$VOXRIVA_TEST_PROJECT" -f compose.mcp-keys-test.yaml)
    # shellcheck disable=SC2329 # Invoked by the EXIT trap in this subshell.
    cleanup_keys() { "${compose[@]}" down --volumes --remove-orphans >/dev/null; }
    trap cleanup_keys EXIT
    npm --prefix frontend run build
    docker build --platform linux/amd64 -f Dockerfile.mcp -t "$VOXRIVA_MCP_KEYS_IMAGE" .
    "${compose[@]}" up -d --wait --wait-timeout 180 api
    "${compose[@]}" exec -T api python - <<'PY'
import asyncio, os
from backend.app.features.identity.bootstrap import bootstrap
from backend.app.features.identity.schemas import NewAccount
from backend.app.infrastructure.settings import Settings
asyncio.run(bootstrap(Settings().database_url, NewAccount(email="mcp-browser@example.test", password="Synthetic MCP browser password")))
PY
    npm --prefix frontend run test:e2e -- 30-mcp-keys.spec.ts "${browser_args[@]}"
)

run_suite() {
    case "$suite" in
        chromium) bash scripts/test-compose.sh "${browser_args[@]}" ;;
        cloud) bash scripts/test-cloud-compose.sh "${browser_args[@]}" ;;
        crash) bash scripts/test-worker-crash-compose.sh "${browser_args[@]}" ;;
        sdk) bash scripts/test-sdk-compose.sh "${browser_args[@]}" ;;
        mcp) run_mcp ;;
        mcp-keys) run_mcp_keys ;;
        *) echo 'Unknown CI suite' >&2; return 2 ;;
    esac
}

# Do not upload traces/screenshots: even fictional issued keys can be present.
# Capture the real suite exit code without weakening any required test gate.
set +e
(set -e; run_suite)
status=$?
set -e
python3 "$root/.github/scripts/release_metadata.py" summary --suite "$suite" \
    --exit-code "$status" --output "$CI_ARTIFACT_DIR/$suite/summary.json"
exit "$status"
