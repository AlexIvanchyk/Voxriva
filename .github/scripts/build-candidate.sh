#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root/voxriva"
version=${1:?Supply VERSION}
revision=${2:?Supply the full source revision}
output=${3:?Supply a fresh absolute output directory}
: "${CI_SOURCE_EVIDENCE:?Supply successful source checks from this run}"
: "${CI_ARTIFACT_DIR:?Supply an isolated test artifact directory}"
[[ "$output" = /* && ! -e "$output" ]] || { echo 'Use a fresh absolute directory.' >&2; exit 1; }
python3 "$root/.github/scripts/release_metadata.py" preflight --root "$PWD" --version "$version" --revision "$revision"
mkdir -p "$output"
export DOCKER_DEFAULT_PLATFORM=linux/amd64
python_image=python:3.13-slim-trixie@sha256:7249d5587b78209a006dc4a3b5340678f84ea729239193aa559962cd8c1fce50
node_image=node:22-bookworm-slim
docker pull "$python_image"
docker pull "$node_image"
python_digest=$(docker image inspect "$python_image" --format '{{index .RepoDigests 0}}')
node_digest=$(docker image inspect "$node_image" --format '{{index .RepoDigests 0}}')
printf 'NODE_IMAGE=%s\nPYTHON_IMAGE=%s\n' "$node_digest" "$python_digest" > "$output/build-inputs.env"
app_image="voxriva:ci-$revision"
mcp_image="voxriva-mcp:ci-$revision"
source_url="$GITHUB_SERVER_URL/$GITHUB_REPOSITORY"
docker build --platform linux/amd64 --build-arg "PYTHON_IMAGE=$python_digest" \
    --build-arg "NODE_IMAGE=$node_digest" --build-arg "VERSION=$version" --build-arg "REVISION=$revision" \
    --label "org.opencontainers.image.source=$source_url" -t "$app_image" .
docker build --platform linux/amd64 -f Dockerfile.mcp --build-arg "PYTHON_IMAGE=$python_digest" \
    --label "org.opencontainers.image.version=$version" --label "org.opencontainers.image.revision=$revision" \
    --label "org.opencontainers.image.source=$source_url" -t "$mcp_image" .
app_id=$(docker image inspect "$app_image" --format '{{.Id}}')
mcp_id=$(docker image inspect "$mcp_image" --format '{{.Id}}')

# Exact application image: HTTPS, sign-in, SMTP delivery, backup/keyring restore
# and image replacement; exact MCP image: PostgreSQL + HTTP and stdio smoke.
VOXRIVA_TEST_IMAGE="$app_id" bash scripts/test-production-compose.sh
CI_MCP_IMAGE="$mcp_id" bash "$root/.github/scripts/e2e.sh" mcp
run_url="$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID/attempts/$GITHUB_RUN_ATTEMPT"
docker image inspect "$app_id" > "$output/application-inspect.tmp"
python3 "$root/.github/scripts/release_metadata.py" bind --source "$CI_SOURCE_EVIDENCE" \
    --inspect "$output/application-inspect.tmp" --version "$version" --revision "$revision" \
    --runtime "$run_url: exact-image production Compose smoke passed" --output "$output/application-checks.tmp"
VOXRIVA_RELEASE_IMAGE="$app_image" VOXRIVA_EXISTING_IMAGE_ID="$app_id" \
    VOXRIVA_EXISTING_BUILD_INPUTS="$output/build-inputs.env" VOXRIVA_APP_CHECKS_FILE="$output/application-checks.tmp" \
    VOXRIVA_OS_SCAN=0 bash scripts/build-release.sh "$version" "$revision" "$output/application"
rm "$output/application-inspect.tmp" "$output/application-checks.tmp"

mkdir "$output/mcp"
docker image inspect "$mcp_id" > "$output/mcp/image-inspect.json"
docker save "$mcp_image" -o "$output/mcp/voxriva-mcp-image.tar"
python3 "$root/.github/scripts/release_metadata.py" bind --source "$CI_SOURCE_EVIDENCE" \
    --inspect "$output/mcp/image-inspect.json" --version "$version" --revision "$revision" \
    --runtime "$run_url: exact-image PostgreSQL HTTP/stdio MCP smoke passed" --output "$output/mcp/app-checks.json"
scanner=aquasec/trivy:0.69.3@sha256:bcc376de8d77cfe086a917230e818dc9f8528e3c852f7b1aff648949b6258d1c
app_status=0
license_status=0
# The third-party scanner receives an exported image archive, never a socket.
docker run --rm -v "$output/mcp:/reports" "$scanner" image --input /reports/voxriva-mcp-image.tar \
    --scanners vuln --pkg-types library --list-all-pkgs --format json --output /reports/app-dependencies.json \
    --exit-code 1 --severity HIGH,CRITICAL || app_status=$?
docker run --rm -v "$output/mcp:/reports" "$scanner" image --input /reports/voxriva-mcp-image.tar \
    --scanners license --format json --output /reports/licenses.json || license_status=$?
python3 - "$output/mcp/scan-status.json" "$app_status" "$license_status" <<'PY'
import json, pathlib, sys
pathlib.Path(sys.argv[1]).write_text(json.dumps({"policy":"app-gates-v2", "app_dependencies_exit_code":int(sys.argv[2]), "license_inventory_exit_code":int(sys.argv[3]), "os_advisory":"not_run"}, indent=2)+'\n')
PY
python3 scripts/finalize-release.py "$output/mcp"
cp "$CI_SOURCE_EVIDENCE" "$output/source-checks.json"
cp LICENSE "$output/"
# Notices are copied only from these explicit distribution inputs, never a
# workspace glob that could collect environment files, keys or local reports.
for notice in THIRD_PARTY_NOTICES.md THIRD-PARTY-NOTICES.md; do
    if [[ -f "$notice" ]]; then cp "$notice" "$output/"; fi
done
python3 "$root/.github/scripts/release_metadata.py" index --root "$output" --version "$version" --revision "$revision"
