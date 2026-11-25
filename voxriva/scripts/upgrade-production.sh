#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Caller sets VOXRIVA_IMAGE to the NEW immutable reference. The backup manifest
# records the configured image; capture old image IDs separately before upgrade.
: "${VOXRIVA_IMAGE:?Set the new versioned image reference}"
: "${1:?Usage: VOXRIVA_IMAGE=... bash scripts/upgrade-production.sh NEW_BACKUP_DIRECTORY}"
compose=(docker compose --env-file "${VOXRIVA_ENV_FILE:-.env.production}")
pull_services=(api relay email-worker push-worker migrate postgres redis proxy)
app_services=(api relay email-worker push-worker)
while IFS= read -r service; do
    if [[ "$service" == "mcp" ]]; then
        pull_services+=(mcp)
        app_services+=(mcp)
    fi
done < <("${compose[@]}" config --services)
if [[ "${VOXRIVA_UPGRADE_OFFLINE:-0}" == "1" ]]; then
    while IFS= read -r image; do
        docker image inspect "$image" >/dev/null
    done < <("${compose[@]}" config --images)
else
    "${compose[@]}" pull "${pull_services[@]}"
fi
python3 scripts/production-data.py backup "$1"
maintenance_exit() {
    local upgrade_result=$?
    if (( upgrade_result != 0 )); then
        "${compose[@]}" stop "${app_services[@]}" proxy >&2 || true
    fi
    return "$upgrade_result"
}
trap maintenance_exit EXIT
# Never start new code against an old schema, even if the migration container
# from a previous release already completed successfully.
"${compose[@]}" run --rm --no-deps migrate
"${compose[@]}" up -d --wait --wait-timeout 180 "${app_services[@]}"
# Keep public ingress closed until actual database/broker readiness succeeds.
"${compose[@]}" exec -T api python -c 'import json, urllib.request; assert json.load(urllib.request.urlopen("http://127.0.0.1:8000/health/ready", timeout=5))["status"] == "ready"'
"${compose[@]}" up -d --wait --wait-timeout 180 proxy
