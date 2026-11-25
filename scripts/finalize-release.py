#!/usr/bin/env python3
"""Validate application evidence and index a fresh candidate; OS scans are advisory."""

import argparse
import hashlib
import json
from pathlib import Path

REQUIRED_CHECKS = {
    "auth_permissions",
    "tenant_isolation",
    "secret_handling",
    "preview_sandbox",
    "runtime_smoke",
}


def evaluate(root: Path) -> list[str]:
    failures = []
    try:
        image_id = json.loads((root / "image-inspect.json").read_text())[0]["Id"]
        status = json.loads((root / "scan-status.json").read_text())
        if status.get("policy") != "app-gates-v2":
            failures.append("Missing current application scan policy evidence")
        if (
            type(status.get("app_dependencies_exit_code")) is not int
            or status["app_dependencies_exit_code"] != 0
        ):
            failures.append("Application dependency scan failed or did not run")
        report = json.loads((root / "app-dependencies.json").read_text())
        if report.get("Metadata", {}).get("ImageID") != image_id:
            failures.append("Application dependency report does not match the image")
        results = report.get("Results", [])
        python = [r for r in results if r.get("Type") == "python-pkg"]
        if not python or not any(r.get("Packages") for r in python):
            failures.append(
                "Application dependency scan has no Python package inventory"
            )
        if any(
            v.get("Severity") in {"HIGH", "CRITICAL"}
            for r in results
            if r.get("Class") == "lang-pkgs"
            for v in r.get("Vulnerabilities", []) or []
        ):
            failures.append("Application dependencies contain HIGH/CRITICAL findings")
        if (
            type(status.get("license_inventory_exit_code")) is not int
            or status["license_inventory_exit_code"] != 0
        ):
            failures.append("License inventory failed or did not run")
        licenses = json.loads((root / "licenses.json").read_text())
        if licenses.get("Metadata", {}).get("ImageID") != image_id:
            failures.append("License inventory does not match the image")
        checks = json.loads((root / "app-checks.json").read_text())
        if checks.get("image_id") != image_id:
            failures.append(
                "Application security/runtime evidence does not match the image"
            )
        for category in sorted(REQUIRED_CHECKS):
            evidence = checks.get("checks", {}).get(category, {})
            if evidence.get("status") != "passed" or not evidence.get("evidence"):
                failures.append(f"Application check missing/not passed: {category}")
    except (
        OSError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        AttributeError,
    ) as error:
        failures.append(
            f"Required evidence unavailable/invalid: {type(error).__name__}"
        )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    root = parser.parse_args().directory
    if (root / "SHA256SUMS").exists():
        raise SystemExit(
            "Refusing to rewrite an indexed candidate; use a fresh directory."
        )
    failures = evaluate(root)
    if failures:
        (root / "RELEASE-BLOCKED").write_text("\n".join(failures) + "\n")
    else:
        (root / "APP-CHECKS-PASSED").write_text(
            "Required application checks passed for this image. OS scan is optional/advisory.\n"
            "Owner license, namespace, platform and publication decisions still apply.\n"
            "This is not a full source-code or exploitability audit.\n"
        )
    with (root / "SHA256SUMS").open("w") as output:
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.name != "SHA256SUMS":
                with path.open("rb") as source:
                    checksum = hashlib.file_digest(source, "sha256").hexdigest()
                output.write(f"{checksum}  {path.relative_to(root)}\n")
    print(
        "Application checks blocked: " + "; ".join(failures)
        if failures
        else "Application checks passed; publication prerequisites remain."
    )
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
