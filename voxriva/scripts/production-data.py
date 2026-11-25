#!/usr/bin/env python3
"""Offline-consistent backup/restore. Inherits Compose CLI environment."""

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

APP = ["proxy", "api", "relay", "email-worker", "push-worker", "mcp"]
COMPOSE = [
    "docker",
    "compose",
    "--env-file",
    os.environ.get("VOXRIVA_ENV_FILE", ".env.production"),
]


def compose(*args, **kwargs):
    return subprocess.run([*COMPOSE, *args], check=True, **kwargs)


def digest(path):
    return hashlib.file_digest(path.open("rb"), "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["backup", "restore"])
    parser.add_argument("directory", type=Path)
    options = parser.parse_args()
    # Resolve the *actual* Compose bind source, including env-file interpolation.
    config = json.loads(
        compose("config", "--format", "json", capture_output=True, text=True).stdout
    )
    writers = [name for name in APP if name in config["services"]]
    key = Path(config["secrets"]["provider-keyring"]["file"])
    folder = options.directory.resolve()
    if options.operation == "backup":
        folder.mkdir(mode=0o700, parents=True, exist_ok=False)
        # Stop writers first. Leave stopped on success or failure; operator resumes explicitly.
        compose("stop", *writers)
        with (folder / "database.dump").open("xb") as output:
            compose(
                "exec",
                "-T",
                "postgres",
                "pg_dump",
                "-U",
                "voxriva",
                "-d",
                "voxriva",
                "--format=custom",
                "--no-owner",
                "--no-acl",
                stdout=output,
            )
        (folder / "provider-keyring").write_bytes(key.read_bytes())
        manifest = {
            "format": 1,
            "image": config["services"]["api"]["image"],
            "application_image_ids": compose(
                "images", "-q", "api", capture_output=True, text=True
            ).stdout.splitlines(),
            "stopped_services": writers,
            "sha256": {
                name: digest(folder / name)
                for name in ["database.dump", "provider-keyring"]
            },
        }
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        for path in folder.iterdir():
            path.chmod(0o600)
        print(f"Backup complete: {folder}. Applications remain stopped.")
    else:
        manifest = json.loads((folder / "manifest.json").read_text())
        if manifest["format"] != 1 or set(manifest["sha256"]) != {
            "database.dump",
            "provider-keyring",
        }:
            raise SystemExit("Unsupported backup manifest.")
        for name, expected in manifest["sha256"].items():
            if digest(folder / name) != expected:
                raise SystemExit(f"Checksum mismatch: {name}. Nothing restored.")
        compose("stop", *writers)
        count = compose(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "voxriva",
            "-d",
            "voxriva",
            "-Atc",
            "SELECT count(*) FROM pg_tables WHERE schemaname='public'",
            capture_output=True,
            text=True,
        ).stdout.strip()
        if count != "0":
            raise SystemExit(
                "Restore requires an empty database. Use a NEW Compose project/volume; never down -v production."
            )
        with (folder / "database.dump").open("rb") as source:
            compose(
                "exec",
                "-T",
                "postgres",
                "pg_restore",
                "-U",
                "voxriva",
                "-d",
                "voxriva",
                "--single-transaction",
                "--exit-on-error",
                "--no-owner",
                "--no-acl",
                stdin=source,
            )
        # Write in place: existing bind mounts keep the inode. Preserve bind-backed secret permissions.
        key.chmod(0o600)
        key.write_bytes((folder / "provider-keyring").read_bytes())
        key.chmod(0o444)
        print(
            "Database AND provider keyring restored. Applications remain stopped; run migration and startup procedure."
        )


if __name__ == "__main__":
    main()
