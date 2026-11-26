# Run locally and send your first email

Start an isolated Voxriva installation, explore the dashboard and send a welcome
email through the HTTP API. The launcher supplies fictional content, credentials
and a local Mailpit inbox, so no cloud account or dashboard setup is needed.

## Requirements

Have Docker Engine with Compose v2 running and host Python 3.10+ on macOS/Linux.
No host Node.js or installed Python packages are needed. Published container
images target **linux/amd64**. A native ARM64 image is not published.

## Download and start { #start-locally }

Download the operator bundle, verify its checksum, then run the launcher. No
source checkout or image build is needed:

```sh
curl -fLO https://github.com/AlexIvanchyk/Voxriva/releases/download/v0.1.1/Voxriva-0.1.1-operator.tar.gz
curl -fLO https://github.com/AlexIvanchyk/Voxriva/releases/download/v0.1.1/OPERATOR-SHA256SUMS
shasum -a 256 -c OPERATOR-SHA256SUMS
tar -xzf Voxriva-0.1.1-operator.tar.gz
cd Voxriva-0.1.1
python3 scripts/example.py
```

For development from a source checkout, the same launcher builds locally:

```sh
python3 scripts/example.py
```

The command prepares and deploys `northstar-welcome`, binds local Mailpit SMTP,
creates a Delivery key and verifies one sample through the API, relay and worker.
It prints an App URL, an Email URL and the location of your private login file.
Use those actual URLs; ports are selected automatically.

## Open the dashboard and inbox

Sign in at the printed App URL using `output/example/local/access.txt`. Open
**Templates** to inspect `northstar-welcome`, **Deployments** to see the active
version, and **Notifications** to inspect the verified sample. Open the printed
Email URL to see the received message in Mailpit.

You can edit and preview a draft without sending. Publish and deploy separately
when you want future API requests to use changed content. The following request
uses the original fixture contract; follow [the dashboard tour](dashboard.md)
after the first send if you want to change that contract.

## Load local credentials

The default example stores its actual URL/key in private state. In a shell with
command tracing disabled, load them without printing the key:

```sh
export VOXRIVA_URL="$(python3 -c 'import json; print(json.load(open("output/example/local/state.json"))["base_url"])')"
export VOXRIVA_API_KEY="$(python3 -c 'import json; print(json.load(open("output/example/local/state.json"))["delivery_key"])')"
```

For a named example, replace `local` in both paths. For your own installation,
provide the installation root URL and an environment **Delivery** key through
your application secret configuration. Dashboard and Template / MCP credentials
cannot submit runtime notifications.

## Validate and send { #send-the-first-message }

[welcome.json](examples/welcome.json) is the complete runtime request. The
fixture's published defaults supply the omitted banner and phone; synthetic
preview data supplies nothing at delivery time. Edit this file to try your own
valid values, keeping the published contract in mind.

```sh
curl --silent --show-error --fail-with-body --noproxy '*' \
  "$VOXRIVA_URL/api/v1/notifications/validate" \
  -H "Authorization: Bearer $VOXRIVA_API_KEY" \
  -H 'Content-Type: application/json' \
  --data-binary @docs/examples/welcome.json
```

Expect HTTP 200, `valid: true` and the resolved template/provider revision IDs.
This request creates no notification and contacts neither provider nor broker.
A later send resolves active deployments again.

```sh
curl --silent --show-error --fail-with-body --noproxy '*' \
  "$VOXRIVA_URL/api/v1/notifications" \
  -H "Authorization: Bearer $VOXRIVA_API_KEY" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: docs:welcome:001' \
  --data-binary @docs/examples/welcome.json \
  --dump-header /tmp/voxriva-accepted.headers \
  --output /tmp/voxriva-accepted.json

python3 - <<'PY'
import json
from pathlib import Path
accepted = json.loads(Path("/tmp/voxriva-accepted.json").read_text())
print(accepted["id"], accepted["status"], accepted["replayed"])
print(accepted["status_url"])
PY
```

Expect HTTP 202 and `Location: /api/v1/notifications/<returned-id>`. A new
acceptance returns `replayed: false`; repeating the command unchanged returns the
same ID with `replayed: true`, possibly already Sent. Reuse the original key/body
after a timeout. Change the key only for a new intended message; changing this
payload while retaining the key produces HTTP 409.

## Inspect the outcome

```sh
export VOXRIVA_NOTIFICATION_ID="$(python3 -c 'import json; print(json.load(open("/tmp/voxriva-accepted.json"))["id"])')"
curl --silent --show-error --fail-with-body --noproxy '*' \
  "$VOXRIVA_URL/api/v1/notifications/$VOXRIVA_NOTIFICATION_ID" \
  -H "Authorization: Bearer $VOXRIVA_API_KEY"
```

Status can initially be `queued` or `processing`; query again after the worker
runs. The isolated SMTP path should reach `sent`. Inspect `attempts`,
`template_version_id`, `provider_revision_id` and `resolution` in the response.
API-key responses mask the email recipient.

Open the Mailpit URL printed by the launcher to inspect the new actual message.
Sent itself establishes SMTP acceptance; Mailpit receipt is a separate local
observation. Neither result proves delivery to an external inbox.

Continue with [Python sync/async clients](journeys/integrate.md), the exact
[Delivery API](api.md), [retry/idempotency semantics](journeys/operate.md) or
[template contracts](journeys/email.md). No cloud account is needed for this
example. FCM and verified SES receipt events have separate provider prerequisites.

## Stop or remove the example

```sh
python3 scripts/example.py stop
```

Stopping preserves the workspace. To permanently delete only this example's
owned resources and generated credentials:

```sh
python3 scripts/example.py remove
```

See [the local example reference](evaluate.md) for named installations, explicit
ports, reruns and isolation. Use [self-hosting](self-hosting.md) for a persistent
installation.
