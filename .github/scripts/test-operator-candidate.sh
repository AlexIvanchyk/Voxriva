#!/usr/bin/env bash
set -euo pipefail
archive=$(realpath "${1:?operator archive required}")
image=${2:?exact application image ID required}
mcp_image=${3:?exact MCP image ID required}
[[ "$image" =~ ^sha256:[a-f0-9]{64}$ && "$mcp_image" =~ ^sha256:[a-f0-9]{64}$ ]]
work=$(mktemp -d)
cleanup() {
    if [[ -n ${operator:-} && -f "$operator/scripts/example.py" ]]; then
        (cd "$operator" && python3 scripts/example.py remove --name release-candidate) || true
    fi
    rm -rf "$work"
}
trap cleanup EXIT
tar -xzf "$archive" -C "$work"
operator=$(find "$work" -mindepth 1 -maxdepth 1 -type d)
cd "$operator"
sha256sum --check SHA256SUMS
[[ ! -e Dockerfile && ! -d backend && ! -d frontend && ! -d .git ]]
docker image inspect "$mcp_image" --format '{{.Os}}/{{.Architecture}}' | grep -Fx linux/amd64
python3 scripts/example.py --name release-candidate --image "$image"
# Repeating startup must verify the same notification instead of sending again.
python3 scripts/example.py --name release-candidate --image "$image"
python3 - <<'PY'
import json
from pathlib import Path
p = Path('output/example/release-candidate/verification.json')
evidence = json.loads(p.read_text())
assert evidence['status'] == 'sent' and evidence['inline_images'] == 2
assert evidence['image_bytes_match'] and evidence['mailpit_receipts'] == 1
print('Source-free operator candidate: SMTP receipt, inline images and idempotent repeat verified.')
PY
