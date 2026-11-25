# Local fictional demo fixture

For isolated evaluation, use `python3 scripts/example.py` from the repository root.
It creates an owned Compose installation, reuses the Northstar template/assets,
and verifies one real Mailpit email. See [evaluation](../../docs/evaluate.md),
[first API email](../../docs/quickstart.md) and [example tooling](../example/README.md).

The richer seed here is for a **separately authorized empty local installation**.
It is not an installer/reset command and must not run against an existing user's
data. No current docs task authorizes reseeding the primary `voxriva` stack.
It provides fictional projects, environments, role grants, localized/branched
content, safe push preview and controlled local SMTP delivery/recovery cases.

After the operator has explicitly prepared the intended empty installation,
use its matching Compose overlay and protected state. The existing seed refuses
a nonempty project list and deliberately has no reset operation:

```sh
docker compose -p voxriva -f compose.yaml -f scripts/demo/compose.demo.yaml up -d --build
.venv/bin/python scripts/demo/assets.py
.venv/bin/python scripts/demo/seed.py --state output/demo/private-state.json
.venv/bin/python scripts/demo/verify.py --state output/demo/private-state.json
```

Private state contains the intended local URL/account plus issued credentials
and IDs, and must remain mode 0600 in a mode-0700 ignored output directory. Do not
copy it into docs, screenshots or command logs. All recipients use `example.test`;
SMTP is allowlisted to local Mailpit. Push uses no cloud credential/device send.
`verify.py` retains compatibility with additional historical local message state.

The original Northstar raster artwork comes from `assets.py` and versioned
`scripts/demo/assets/`. These shared assets and fixture code also serve the
first-email launcher. Existing documentation screenshots remain under
`docs/assets/screenshots/`; use them selectively with factual captions.
Private captures/diagnostics remain ignored. The current presentation uses
substantive text and existing static screenshots; no recording pipeline belongs
to the documentation or release payload.
