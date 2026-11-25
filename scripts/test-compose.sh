#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

export VOXRIVA_TEST_PROJECT="voxriva-test-$$"
export VOXRIVA_MAILPIT_PORT="${VOXRIVA_TEST_MAILPIT_PORT:-18025}"
export VOXRIVA_PORT="${VOXRIVA_TEST_PORT:-18080}"
export VOXRIVA_TEST_EMAIL="admin@example.test"
export VOXRIVA_TEST_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
export VOXRIVA_TEST_URL="http://127.0.0.1:$VOXRIVA_PORT"

compose=(docker compose -p "$VOXRIVA_TEST_PROJECT")
docker version --format '{{.Server.Version}}' >/dev/null
cleanup() {
    result=$?
    if (( result != 0 )); then
        "${compose[@]}" ps -a >&2 || true
        "${compose[@]}" logs --tail=50 >&2 || true
    fi
    "${compose[@]}" down --volumes --remove-orphans
}
trap cleanup EXIT
"${compose[@]}" up --build --detach --wait --wait-timeout 120

for (( attempt=0; attempt<45; attempt++ )); do
    if curl --silent --fail --output /dev/null "$VOXRIVA_TEST_URL/health/ready"; then
        python3 -c 'import json, os; print(json.dumps({"email": os.environ["VOXRIVA_TEST_EMAIL"], "password": os.environ["VOXRIVA_TEST_PASSWORD"]}))' |
            "${compose[@]}" exec -T api python -c 'import asyncio, sys; from backend.app.features.identity.bootstrap import bootstrap; from backend.app.features.identity.schemas import NewAccount; from backend.app.infrastructure.settings import Settings; asyncio.run(bootstrap(Settings().database_url, NewAccount.model_validate_json(sys.stdin.read())))'
        npm --prefix frontend run test:e2e -- "$@"
        exit
    fi
    sleep 2
done
echo "The test stack did not become ready at $VOXRIVA_TEST_URL." >&2
exit 1
