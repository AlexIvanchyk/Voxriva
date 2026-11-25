import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/finalize-release.py"
spec = importlib.util.spec_from_file_location("release_finalizer", SCRIPT)
assert spec and spec.loader
finalizer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(finalizer)


def evidence(root: Path) -> None:
    files = {
        "image-inspect.json": [{"Id": "sha256:tested"}],
        "scan-status.json": {
            "policy": "app-gates-v2",
            "app_dependencies_exit_code": 0,
            "license_inventory_exit_code": 0,
            "os_advisory": "not_run",
        },
        "app-dependencies.json": {
            "Metadata": {"ImageID": "sha256:tested"},
            "Results": [
                {
                    "Class": "lang-pkgs",
                    "Type": "python-pkg",
                    "Packages": [{"Name": "synthetic-app", "Version": "1"}],
                }
            ],
        },
        "licenses.json": {"Metadata": {"ImageID": "sha256:tested"}, "Results": []},
        "app-checks.json": {
            "image_id": "sha256:tested",
            "checks": {
                name: {"status": "passed", "evidence": "synthetic-ci-log"}
                for name in finalizer.REQUIRED_CHECKS
            },
        },
    }
    for name, value in files.items():
        (root / name).write_text(json.dumps(value))


def test_os_findings_and_unperformed_os_scan_do_not_block_app_gate(tmp_path: Path):
    evidence(tmp_path)
    assert finalizer.evaluate(tmp_path) == []
    (tmp_path / "os-advisory.json").write_text(
        json.dumps({"Vulnerabilities": [{"Severity": "CRITICAL"}]})
    )
    assert finalizer.evaluate(tmp_path) == []


@pytest.mark.parametrize(
    "change",
    [
        "scan_failed",
        "missing_report",
        "empty_inventory",
        "app_finding",
        "wrong_image",
        "missing_security_check",
        "license_failed",
    ],
)
def test_required_app_evidence_cannot_be_silently_green(tmp_path: Path, change: str):
    evidence(tmp_path)
    if change in {"scan_failed", "license_failed"}:
        path = tmp_path / "scan-status.json"
        data = json.loads(path.read_text())
        data[
            "app_dependencies_exit_code"
            if change == "scan_failed"
            else "license_inventory_exit_code"
        ] = 1
    elif change == "missing_report":
        (tmp_path / "app-dependencies.json").unlink()
        assert finalizer.evaluate(tmp_path)
        return
    elif change == "missing_security_check":
        path = tmp_path / "app-checks.json"
        data = json.loads(path.read_text())
        data["checks"].pop("preview_sandbox")
    else:
        path = tmp_path / "app-dependencies.json"
        data = json.loads(path.read_text())
        if change == "empty_inventory":
            data["Results"] = []
        elif change == "wrong_image":
            data["Metadata"]["ImageID"] = "sha256:untested"
        else:
            data["Results"][0]["Vulnerabilities"] = [{"Severity": "HIGH"}]
    path.write_text(json.dumps(data))
    assert finalizer.evaluate(tmp_path)


def test_indexed_artifact_is_never_rewritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    (tmp_path / "SHA256SUMS").write_text("historical artifact\n")
    monkeypatch.setattr("sys.argv", [str(SCRIPT), str(tmp_path)])
    with pytest.raises(SystemExit, match="Refusing to rewrite"):
        finalizer.main()
    assert (tmp_path / "SHA256SUMS").read_text() == "historical artifact\n"
