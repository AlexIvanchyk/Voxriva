"""The cloud fixture must not burden bounded renderer subprocesses with SDKs."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ADAPTERS = (
    "backend.app.features.providers.adapters.ses",
    "backend.app.features.providers.adapters.fcm",
)


def cloud_environment():
    return {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(ROOT / "tests/cloud_doubles"), str(ROOT))),
        "PYTHONDONTWRITEBYTECODE": "1",
        "VOXRIVA_CLOUD_TEST_DOUBLES": "1",
    }


def test_cloud_fixture_leaves_the_bounded_authoring_renderer_free_of_cloud_sdks():
    payload = {
        "channel": "email",
        "draft": {
            "subject": "Hello {{ name }}",
            "text": "Cloud test publication",
            "variable_schema": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
        "context": {"name": "Synthetic"},
        "authoring": True,
    }
    result = subprocess.run(
        [sys.executable, "-X", "importtime", "-m", "backend.app.features.templates.rendering"],
        input=json.dumps(payload),
        cwd=ROOT,
        env=cloud_environment(),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    output = json.loads(result.stdout)
    assert output["rendered"]["subject"] == "Hello Synthetic"
    assert output["errors"] == []
    assert all(adapter not in result.stderr for adapter in ADAPTERS)
    assert "boto3" not in result.stderr
    assert "google.auth" not in result.stderr


@pytest.mark.parametrize("entrypoint", ["uvicorn", "celery"])
def test_cloud_fixture_still_patches_compose_api_and_worker_entrypoints(tmp_path, entrypoint):
    script = tmp_path / entrypoint
    script.write_text(
        "import json,sys\n"
        f"names={ADAPTERS!r}\n"
        "loaded=all(name in sys.modules for name in names)\n"
        "patched=loaded and all(getattr(sys.modules[name],provider)."
        "__dict__[method].__module__=='sitecustomize' for name,provider,method in "
        "[(names[0],'SESProvider','client'),(names[1],'FCMProvider','access_token')])\n"
        "print(json.dumps({'loaded':loaded,'patched':patched}))\n"
    )
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        env=cloud_environment(),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert json.loads(result.stdout) == {"loaded": True, "patched": True}
