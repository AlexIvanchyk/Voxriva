"""Pure delivery policies must be usable without bootstrapping a worker."""

import subprocess
import sys


def test_importing_delivery_does_not_construct_settings_or_celery():
    script = """
import celery
from backend.app.infrastructure.settings import Settings

def forbidden(*args, **kwargs):
    raise AssertionError("Import started process resources")

Settings.__init__ = forbidden
celery.Celery = forbidden
from backend.app.features.notifications.delivery import consume, publish_once
assert callable(consume) and callable(publish_once)
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stderr
