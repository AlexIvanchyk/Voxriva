#!/usr/bin/env python3
"""Create local production secrets once; run on the deployment host."""

import base64
import secrets
import sys
from pathlib import Path
from urllib.parse import quote

folder = Path(sys.argv[1] if len(sys.argv) > 1 else "secrets")
folder.mkdir(exist_ok=True)
if any(folder.iterdir()):
    raise SystemExit("Refusing to initialize a nonempty secrets directory.")
folder.chmod(0o700)
password = secrets.token_urlsafe(48)
values = {
    "postgres-password": password,
    "database-url": f"postgresql+asyncpg://voxriva:{quote(password, safe='')}@postgres:5432/voxriva",
    "provider-keyring": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    "metrics-token": secrets.token_urlsafe(48),
}
for name, value in values.items():
    path = folder / name
    path.write_text(value + "\n")
    # Host directory is 0700; bind-mounted files must be readable by UID 10001.
    path.chmod(0o444)
print("Secrets initialized. Supply tls.crt and tls.key before starting production.")
