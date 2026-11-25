#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
cloud_override=$(mktemp /tmp/voxriva-cloud-compose.XXXXXX)
trap 'rm -f "$cloud_override"' EXIT
# These doubles exist only in this isolated test stack. Production images contain neither
# sitecustomize.py nor this environment flag, and never override cloud endpoints.
python3 - "$PWD" > "$cloud_override" <<'PY'
import json
import sys
role = {"environment": {"PYTHONPATH": "/cloud-test:/app", "VOXRIVA_CLOUD_TEST_DOUBLES": "1"}, "volumes": [sys.argv[1]+"/tests/cloud_doubles:/cloud-test:ro", sys.argv[1]+"/frontend/e2e/fixtures/ses-events/signing-cert.pem:/sns-signing-cert.pem:ro"]}
print(json.dumps({"services": {name: role for name in ["api", "email-worker", "push-worker"]}}))
PY
export COMPOSE_FILE="$PWD/compose.yaml:$cloud_override"
bash scripts/test-compose.sh --grep 'cloud provider contracts|verified SES events' "$@"
