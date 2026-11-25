#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${1:?Usage: build-release.sh VERSION REVISION [OUTPUT_DIRECTORY]}"
: "${2:?Supply a source revision or source archive SHA256}"
version="$1"; revision="$2"; output="${3:-release/$version}"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?$ ]] || { echo 'Use a semantic version.' >&2; exit 1; }
image="${VOXRIVA_RELEASE_IMAGE:-voxriva:$version}"
[[ ! -e "$output" ]] || { echo 'Output already exists.' >&2; exit 1; }
mkdir -p "$output"
if [[ -n "${VOXRIVA_EXISTING_IMAGE_ID:-}" ]]; then
    # Export the exact image tested by CI, even if the source tree changed later.
    [[ "$VOXRIVA_EXISTING_IMAGE_ID" =~ ^sha256:[a-f0-9]{64}$ ]] || { echo 'Use a local immutable image ID.' >&2; exit 1; }
    : "${VOXRIVA_EXISTING_BUILD_INPUTS:?Supply the original build-inputs.env}"
    actual_version=$(docker image inspect "$VOXRIVA_EXISTING_IMAGE_ID" --format '{{index .Config.Labels "org.opencontainers.image.version"}}')
    actual_revision=$(docker image inspect "$VOXRIVA_EXISTING_IMAGE_ID" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')
    [[ "$actual_version" == "$version" && "$actual_revision" == "$revision" ]] || { echo 'Tested image version/revision labels do not match.' >&2; exit 1; }
    if previous=$(docker image inspect "$image" --format '{{.Id}}' 2>/dev/null); then
        [[ "$previous" == "$VOXRIVA_EXISTING_IMAGE_ID" ]] || { echo 'Refusing to overwrite an existing image tag. Choose a new candidate tag.' >&2; exit 1; }
    else
        docker tag "$VOXRIVA_EXISTING_IMAGE_ID" "$image"
    fi
    cp "$VOXRIVA_EXISTING_BUILD_INPUTS" "$output/build-inputs.env"
else
    # Resolve mutable upstream tags once and record the immutable build inputs.
    node_image="${NODE_IMAGE:-node:22-bookworm-slim}"
    python_image="${PYTHON_IMAGE:-python:3.13-slim-trixie@sha256:7249d5587b78209a006dc4a3b5340678f84ea729239193aa559962cd8c1fce50}"
    for base in "$node_image" "$python_image"; do docker pull "$base"; done
    node_digest=$(docker image inspect "$node_image" --format '{{index .RepoDigests 0}}')
    python_digest=$(docker image inspect "$python_image" --format '{{index .RepoDigests 0}}')
    printf 'NODE_IMAGE=%s\nPYTHON_IMAGE=%s\n' "$node_digest" "$python_digest" > "$output/build-inputs.env"
    docker build --build-arg "NODE_IMAGE=$node_digest" --build-arg "PYTHON_IMAGE=$python_digest" --build-arg "VERSION=$version" --build-arg "REVISION=$revision" -t "$image" .
fi
docker image inspect "$image" > "$output/image-inspect.json"
# Extract bundled SDK and frozen contract without executing application code.
container=$(docker create "$image")
trap 'docker rm "$container" >/dev/null' EXIT
docker cp "$container:/app/frontend/dist/downloads/." "$output/"
docker cp "$container:/app/release-metadata/." "$output/"
docker save "$image" -o "$output/voxriva-image.tar"
cp compose.production.yaml "$output/"
cp -R deploy scripts "$output/"
cp PRODUCTION.md README.md LICENSE THIRD_PARTY_NOTICES.md "$output/"
if [[ -f MCP.md ]]; then cp MCP.md compose.mcp.production.yaml "$output/"; fi
mkdir -p "$output/docs"
cp docs/*.md "$output/docs/"
cp -R docs/journeys docs/contributing docs/assets "$output/docs/"
mkdir -p "$output/sdk/python" "$output/contracts" "$output/examples/provider-plugin"
cp sdk/python/README.md sdk/python/LICENSE "$output/sdk/python/"
cp contracts/*.json "$output/contracts/"
cp examples/provider-plugin/README.md examples/provider-plugin/LICENSE "$output/examples/provider-plugin/"
cp requirements-runtime.lock "$output/"
cp frontend/package-lock.json "$output/frontend-package-lock.json"
# Mandatory application/library vulnerability check; OS analysis is opt-in advisory.
scanner="aquasec/trivy:0.69.3@sha256:bcc376de8d77cfe086a917230e818dc9f8528e3c852f7b1aff648949b6258d1c"
app_status=0
license_status=0
os_status=not_run
docker run --rm -v "$(cd "$output" && pwd):/reports" \
    "$scanner" image --input /reports/voxriva-image.tar --scanners vuln --pkg-types library \
    --list-all-pkgs --format json --output /reports/app-dependencies.json \
    --exit-code 1 --severity HIGH,CRITICAL || app_status=$?
docker run --rm -v "$(cd "$output" && pwd):/reports" \
    "$scanner" image --input /reports/voxriva-image.tar --scanners license \
    --format json --output /reports/licenses.json || license_status=$?
if [[ "${VOXRIVA_OS_SCAN:-0}" == "1" ]]; then
    os_status=0
    docker run --rm -v "$(cd "$output" && pwd):/reports" \
        "$scanner" image --input /reports/voxriva-image.tar --scanners vuln --pkg-types os \
        --format json --output /reports/os-advisory.json --exit-code 0 || os_status=$?
fi
if [[ -n "${VOXRIVA_APP_CHECKS_FILE:-}" ]]; then cp "$VOXRIVA_APP_CHECKS_FILE" "$output/app-checks.json"; fi
python3 - "$output" "$app_status" "$license_status" "$os_status" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
(root / 'scan-status.json').write_text(json.dumps({
    'policy': 'app-gates-v2', 'app_dependencies_exit_code': int(sys.argv[2]),
    'license_inventory_exit_code': int(sys.argv[3]), 'os_advisory': sys.argv[4],
}, indent=2) + '\n')
PY
# Missing/failed required checks remain blocked; OS findings never decide this gate.
python3 scripts/finalize-release.py "$output"
printf 'Local release artifacts: %s. Owner license/publication prerequisites still apply.\n' "$output"
