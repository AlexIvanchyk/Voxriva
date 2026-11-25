#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# These projects run only the non-disruptive UI smoke, never the serial suites
# that stop/restart shared services. The base script creates and removes its own
# isolated voxriva-test-* Compose project and fictional administrator.
export VOXRIVA_E2E_BROWSER_MATRIX=1
bash scripts/test-compose.sh --project firefox --project webkit --project mobile-chromium "$@"
