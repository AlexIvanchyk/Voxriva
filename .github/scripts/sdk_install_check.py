"""Install an SDK distribution in a fresh environment, then exercise installed code."""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SMOKE = r'''
import asyncio
import importlib.metadata
import json
from pathlib import Path
import sys
from uuid import UUID

import httpx
import voxriva_sdk
from voxriva_sdk import AsyncClient, Client, NotificationStatus

version = sys.argv[1]
assert importlib.metadata.version("voxriva-sdk") == version
assert voxriva_sdk.__version__ == version
location = Path(voxriva_sdk.__file__).resolve()
assert location.is_relative_to(Path(sys.prefix).resolve()), location
assert (location.parent / "py.typed").is_file()
identifier = "00000000-0000-4000-8000-000000000001"
calls = []

def handle(request):
    assert request.method == "POST"
    assert request.url == "https://voxriva.example.test/api/v1/notifications"
    assert request.headers["Authorization"] == "Bearer synthetic-sdk-install-key"
    assert request.headers["Idempotency-Key"] in {"install:sync", "install:async"}
    payload = json.loads(request.content)
    assert payload["context"] == {"name": "Ada"}
    assert payload["recipient"] == "person@example.test"
    calls.append(request)
    return httpx.Response(202, json={
        "id": identifier, "status": "queued", "environment_id": identifier,
        "template_version_id": identifier, "provider_revision_id": identifier,
        "replayed": False, "status_url": f"/api/v1/notifications/{identifier}",
    })

with httpx.Client(transport=httpx.MockTransport(handle)) as http:
    with Client("https://voxriva.example.test", "synthetic-sdk-install-key", http_client=http) as client:
        result = client.send("welcome", recipient="person@example.test", context={"name": "Ada"}, idempotency_key="install:sync")
        assert result.id == UUID(identifier) and result.status is NotificationStatus.QUEUED

async def asynchronous():
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        async with AsyncClient("https://voxriva.example.test", "synthetic-sdk-install-key", http_client=http) as client:
            result = await client.send("welcome", recipient="person@example.test", context={"name": "Ada"}, idempotency_key="install:async")
            assert result.id == UUID(identifier) and result.status is NotificationStatus.QUEUED

asyncio.run(asynchronous())
assert len(calls) == 2
print(f"Installed voxriva-sdk {version}: sync/async requests and py.typed verified")
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distribution", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--tests", type=Path, required=True)
    args = parser.parse_args()
    distribution, tests = args.distribution.resolve(), args.tests.resolve()
    if not distribution.is_file() or distribution.is_symlink() or not tests.is_file():
        raise SystemExit("An exact distribution file and SDK test file are required")
    environment = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}}
    environment.update({"PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_INDEX_URL": "https://pypi.org/simple"})
    environment.pop("PIP_EXTRA_INDEX_URL", None)
    with tempfile.TemporaryDirectory(prefix="voxriva-sdk-install-") as temporary:
        directory = Path(temporary)
        subprocess.run([sys.executable, "-I", "-m", "venv", str(directory / "venv")], check=True, env=environment)
        python = str(directory / "venv/bin/python")

        def run(*arguments):
            subprocess.run([python, "-I", *arguments], check=True, cwd=directory, env=environment)

        # No mixed TestPyPI/PyPI dependency lookup. The reviewed SDK is installed
        # separately; only its public runtime/test dependencies come from PyPI.
        run("-m", "pip", "install", "--no-cache-dir", "httpx==0.28.1", "pytest==9.0.3")
        run("-m", "pip", "install", "--no-cache-dir", "--no-deps", str(distribution))
        run("-m", "pip", "check")
        smoke = directory / "installed_smoke.py"
        smoke.write_text(SMOKE)
        run(str(smoke), args.version)
        run("-m", "pytest", "-c", "/dev/null", "--rootdir", str(directory),
            "--import-mode=importlib", "--confcutdir", str(tests.parent), "-q", str(tests))


if __name__ == "__main__":
    main()
