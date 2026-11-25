"""Exercise the real Bash/Python controller with a fake Docker process boundary."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

FAKE_DOCKER = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with Path(os.environ['UPGRADE_EVENTS']).open('a') as output:
    output.write(json.dumps(args) + '\\n')
if args[:2] == ['image', 'inspect']:
    sys.exit(0)
args = args[args.index('--env-file') + 2:]
services = ['api', 'relay', 'email-worker', 'push-worker', 'migrate', 'postgres', 'redis', 'proxy', 'mcp']
if args == ['config', '--services']:
    print('\\n'.join(services))
elif args == ['config', '--images']:
    print('synthetic-api:next\\nsynthetic-mcp:next')
elif args == ['config', '--format', 'json']:
    print(json.dumps({'services': {name: {'image': 'synthetic:next'} for name in services},
                     'secrets': {'provider-keyring': {'file': os.environ['UPGRADE_KEY']}}}))
elif args[0] == 'images':
    print('sha256:synthetic-old-image')
elif 'pg_dump' in args:
    sys.stdout.buffer.write(b'synthetic database dump')
elif args[0] == 'pull' and os.environ['UPGRADE_MODE'] == 'pull_failure':
    sys.exit(1)
elif args[:3] == ['exec', '-T', 'api'] and os.environ['UPGRADE_MODE'] == 'ready_failure':
    sys.exit(1)
"""


@pytest.mark.parametrize("mode", ["ok", "ready_failure", "pull_failure"])
def test_upgrade_maintenance_boundary(tmp_path: Path, mode: str) -> None:
    application = Path(__file__).resolve().parents[2]
    deployment = tmp_path / "deployment"
    scripts = deployment / "scripts"
    scripts.mkdir(parents=True)
    for name in ["upgrade-production.sh", "production-data.py"]:
        shutil.copy(application / "scripts" / name, scripts / name)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    key = tmp_path / "keyring"
    key.write_bytes(b"synthetic-active-key,synthetic-historical-key")
    events = tmp_path / "events.jsonl"
    backup = tmp_path / "backup"
    result = subprocess.run(
        ["bash", str(scripts / "upgrade-production.sh"), str(backup)],
        env={
            **os.environ,
            "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
            "VOXRIVA_IMAGE": "synthetic-api:next",
            "VOXRIVA_UPGRADE_OFFLINE": "1" if mode == "ready_failure" else "0",
            "UPGRADE_MODE": mode,
            "UPGRADE_EVENTS": str(events),
            "UPGRADE_KEY": str(key),
        },
        capture_output=True,
        text=True,
        timeout=20,
    )
    calls = [json.loads(line) for line in events.read_text().splitlines()]
    commands = [
        call[call.index("--env-file") + 2 :] for call in calls if call[0] == "compose"
    ]
    stops = [command for command in commands if command[0] == "stop"]
    if mode == "pull_failure":
        assert result.returncode != 0
        assert not stops  # A registry failure must not interrupt the old installation.
        assert not backup.exists()
        return

    assert (backup / "provider-keyring").read_bytes() == key.read_bytes()
    manifest = json.loads((backup / "manifest.json").read_text())
    assert "mcp" in manifest["stopped_services"]
    assert "mcp" in stops[0]  # The optional authoring server is a database writer.
    migration = next(
        i
        for i, command in enumerate(commands)
        if command[:3] == ["run", "--rm", "--no-deps"]
    )
    application_start = next(
        i for i, command in enumerate(commands) if command[0] == "up"
    )
    readiness = next(
        i for i, command in enumerate(commands) if command[:3] == ["exec", "-T", "api"]
    )
    assert migration < application_start < readiness
    assert "proxy" not in commands[application_start]
    assert "mcp" in commands[application_start]
    if mode == "ready_failure":
        assert result.returncode != 0
        assert all("proxy" not in command for command in commands if command[0] == "up")
        assert set(stops[-1][1:]) == {
            "api",
            "relay",
            "email-worker",
            "push-worker",
            "mcp",
            "proxy",
        }
    else:
        assert result.returncode == 0, result.stderr
        proxy_start = next(
            i
            for i, command in enumerate(commands)
            if command[0] == "up" and "proxy" in command
        )
        assert readiness < proxy_start
        assert len(stops) == 1  # Successful EXIT must not stop the new release.
