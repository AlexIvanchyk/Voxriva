#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
crash_override=$(mktemp /tmp/voxriva-worker-crash-compose.XXXXXX)
crash_state=$(mktemp -d /tmp/voxriva-worker-crash-state.XXXXXX)
# The isolated application's UID needs write access to these synthetic barriers.
chmod 0777 "$crash_state"
cleanup_crash_files() {
    rm -f "$crash_override"
    rm -rf "$crash_state"
}
trap cleanup_crash_files EXIT
python3 - "$PWD" "$crash_state" > "$crash_override" <<'PY'
import json
import sys
print(json.dumps({"services": {
    "api": {"volumes": [sys.argv[2] + ":/crash-state"]},
    "email-worker": {
        "environment": {"PYTHONPATH": "/crash-test:/app", "VOXRIVA_WORKER_CRASH_TEST": "1"},
        "volumes": [sys.argv[1] + "/tests/crash_doubles:/crash-test:ro", sys.argv[2] + ":/crash-state"],
    },
}}))
PY
export COMPOSE_FILE="$PWD/compose.yaml:$crash_override"
export VOXRIVA_WORKER_CRASH_E2E=1
bash scripts/test-compose.sh --grep 'worker crash' "$@"
