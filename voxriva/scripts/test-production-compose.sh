#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export VOXRIVA_TEST_PROJECT="voxriva-test-release-$$"
export COMPOSE_PROJECT_NAME="$VOXRIVA_TEST_PROJECT"
scratch=$(mktemp -d)
export VOXRIVA_SECRETS_DIR="$scratch/secrets"
export VOXRIVA_ENV_FILE="$scratch/production.env"
export VOXRIVA_IMAGE="${VOXRIVA_TEST_IMAGE:-voxriva:release-test}"
export VOXRIVA_HOST=localhost
export VOXRIVA_HTTPS_BIND=127.0.0.1
export VOXRIVA_HTTPS_PORT="${VOXRIVA_TEST_HTTPS_PORT:-18443}"
export VOXRIVA_SMTP_ALLOWED_HOSTS='["mailpit"]'
export VOXRIVA_TEST_URL="https://localhost:$VOXRIVA_HTTPS_PORT"
export VOXRIVA_TEST_SELF_SIGNED_TLS=1
export VOXRIVA_TEST_EMAIL=admin@example.test
export VOXRIVA_TEST_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
cat > "$scratch/test.yaml" <<'YAML'
services:
  mailpit:
    image: axllent/mailpit:v1.33.1
YAML
export COMPOSE_FILE="$PWD/compose.production.yaml:$scratch/test.yaml"
printf 'COMPOSE_PROJECT_NAME=%s\nCOMPOSE_FILE=%s\n' "$COMPOSE_PROJECT_NAME" "$COMPOSE_FILE" > "$VOXRIVA_ENV_FILE"
compose=(docker compose --env-file "$VOXRIVA_ENV_FILE")
cleanup() {
    result=$?
    if (( result != 0 )); then "${compose[@]}" ps -a >&2 || true; "${compose[@]}" logs --tail=30 >&2 || true; fi
    "${compose[@]}" down --volumes --remove-orphans
    if [[ -n "${upgrade_image:-}" ]]; then docker image rm "$upgrade_image" >/dev/null || true; fi
    rm -rf "$scratch"
}
trap cleanup EXIT
python3 scripts/init-production-secrets.py "$VOXRIVA_SECRETS_DIR"
openssl req -x509 -newkey rsa:2048 -nodes -keyout "$VOXRIVA_SECRETS_DIR/tls.key" -out "$VOXRIVA_SECRETS_DIR/tls.crt" -days 1 -subj /CN=localhost -addext subjectAltName=DNS:localhost >/dev/null 2>&1
if [[ -z "${VOXRIVA_TEST_IMAGE:-}" ]]; then docker build -t "$VOXRIVA_IMAGE" .; fi
wait_for_https() {
    # Compose considers a proxy without a healthcheck ready when its process starts.
    # Wait for the real TLS endpoint, retaining certificate/hostname verification.
    for (( attempt=0; attempt<30; attempt++ )); do
        if curl --silent --show-error --cacert "$VOXRIVA_SECRETS_DIR/tls.crt" --fail "$VOXRIVA_TEST_URL/health/ready"; then return 0; fi
        sleep 1
    done
    return 1
}
"${compose[@]}" up -d --wait --wait-timeout 180
wait_for_https
python3 -c 'import json, os; print(json.dumps({"email": os.environ["VOXRIVA_TEST_EMAIL"], "password": os.environ["VOXRIVA_TEST_PASSWORD"]}))' |
    "${compose[@]}" exec -T api python -c 'import asyncio, sys; from backend.app.features.identity.bootstrap import bootstrap; from backend.app.features.identity.schemas import NewAccount; from backend.app.infrastructure.settings import Settings; asyncio.run(bootstrap(Settings().database_url, NewAccount.model_validate_json(sys.stdin.read())))'
browser_status=0
npm --prefix frontend run test:e2e -- 10-notifications.spec.ts --grep 'delivers a real API' --output "$PWD/test-results/$VOXRIVA_TEST_PROJECT" || browser_status=$?
"${compose[@]}" exec -T api python -c 'import asyncio; from sqlalchemy import text; from sqlalchemy.ext.asyncio import create_async_engine; from backend.app.infrastructure.settings import Settings; from backend.app.features.providers.adapters.crypto import encrypt; s=Settings()
async def run():
 e=create_async_engine(s.database_url)
 async with e.begin() as c:
  await c.execute(text("CREATE TABLE release_restore_probe (ciphertext text NOT NULL)"))
  await c.execute(text("INSERT INTO release_restore_probe VALUES (:value)"), {"value": encrypt(s, {"password": "synthetic-restore-secret"})})
 await e.dispose()
asyncio.run(run())'
# Rotate before backup: previously encrypted values require the OLD ring member.
chmod 600 "$VOXRIVA_SECRETS_DIR/provider-keyring"
python3 -c 'import base64,secrets,sys; from pathlib import Path; p=Path(sys.argv[1]); p.write_text(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()+","+p.read_text().strip())' "$VOXRIVA_SECRETS_DIR/provider-keyring"
chmod 444 "$VOXRIVA_SECRETS_DIR/provider-keyring"
python3 scripts/production-data.py backup "$scratch/backup"
snapshot_sql="SELECT md5(COALESCE((SELECT jsonb_agg(to_jsonb(n) ORDER BY id)::text FROM notifications n), '[]') || COALESCE((SELECT jsonb_agg(to_jsonb(p) ORDER BY id)::text FROM provider_revisions p), '[]'))"
snapshot() { "${compose[@]}" exec -T postgres psql -U voxriva -d voxriva -Atc "$snapshot_sql"; }
before_restore=$(snapshot)
cp -R "$scratch/backup" "$scratch/corrupt-backup"
printf corrupted >> "$scratch/corrupt-backup/provider-keyring"
if python3 scripts/production-data.py restore "$scratch/corrupt-backup"; then echo 'Corrupt backup accepted' >&2; exit 1; fi
if python3 scripts/production-data.py restore "$scratch/backup"; then echo 'Unsafe restore accepted' >&2; exit 1; fi
"${compose[@]}" exec -T postgres psql -U voxriva -d voxriva -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'
chmod 600 "$VOXRIVA_SECRETS_DIR/provider-keyring"
python3 -c 'import base64,secrets,sys; open(sys.argv[1],"wb").write(base64.urlsafe_b64encode(secrets.token_bytes(32)))' "$VOXRIVA_SECRETS_DIR/provider-keyring"
chmod 444 "$VOXRIVA_SECRETS_DIR/provider-keyring"
python3 scripts/production-data.py restore "$scratch/backup"
cmp "$scratch/backup/provider-keyring" "$VOXRIVA_SECRETS_DIR/provider-keyring"
[[ "$(snapshot)" == "$before_restore" ]]
"${compose[@]}" run --rm --no-deps migrate
"${compose[@]}" up -d --wait --wait-timeout 180 api relay email-worker push-worker proxy
"${compose[@]}" exec -T api python -c 'import asyncio; from sqlalchemy import text; from sqlalchemy.ext.asyncio import create_async_engine; from backend.app.infrastructure.settings import Settings; from backend.app.features.providers.adapters.crypto import decrypt; s=Settings()
async def run():
 e=create_async_engine(s.database_url)
 async with e.connect() as c:
  value=(await c.execute(text("SELECT ciphertext FROM release_restore_probe"))).scalar_one()
  assert decrypt(s,value)=={"password":"synthetic-restore-secret"}
  for value in (await c.execute(text("SELECT encrypted_secrets FROM provider_revisions"))).scalars():
   decrypt(s,value)
 await e.dispose()
asyncio.run(run())'
# A distinct local image tag tests replacement; historical compatibility needs
# the actual previous release once one exists.
upgrade_image="voxriva:upgrade-$VOXRIVA_TEST_PROJECT"
docker tag "$VOXRIVA_IMAGE" "$upgrade_image"
export VOXRIVA_IMAGE="$upgrade_image"
VOXRIVA_UPGRADE_OFFLINE=1 bash scripts/upgrade-production.sh "$scratch/pre-upgrade"
wait_for_https
"${compose[@]}" exec -T postgres psql -U voxriva -d voxriva -Atc "SELECT status,count(*) FROM notifications GROUP BY status" | tee "$scratch/status"
echo 'Production database/keyring restore and image replacement passed.'
if (( browser_status != 0 )); then
    echo 'Browser release gate failed; data checks continued independently. See the isolated Playwright output.' >&2
    exit "$browser_status"
fi
[[ "$(cat "$scratch/status")" == 'sent|1' ]]
echo 'Production HTTPS, sign-in, SMTP delivery, keyring restore and image replacement passed.' 
