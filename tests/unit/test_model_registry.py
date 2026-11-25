"""Migrations must discover every feature through one SQLAlchemy metadata registry."""

import importlib

from backend.app.infrastructure.database import Base


def test_all_feature_models_share_the_migration_metadata():
    importlib.import_module("backend.app.infrastructure.model_registry")
    modules = [
        importlib.import_module(f"backend.app.features.{feature}.models")
        for feature in [
            "identity",
            "management",
            "projects",
            "templates",
            "deployments",
            "providers",
            "notifications",
        ]
    ]
    discovered = set()
    for module in modules:
        for value in vars(module).values():
            if isinstance(value, type) and hasattr(value, "__tablename__"):
                assert issubclass(value, Base)
                assert value.metadata is Base.metadata
                assert Base.metadata.tables[value.__tablename__] is value.__table__
                discovered.add(value.__tablename__)
    assert {
        "accounts",
        "projects",
        "templates",
        "template_deployments",
        "provider_revisions",
        "notifications",
        "notification_outbox",
        "notification_attempts",
    } <= discovered
    assert set(Base.metadata.tables) == discovered


def test_fresh_worker_bootstrap_registers_cross_feature_foreign_keys():
    """Worker correctness must not depend on API/test imports warming the registry."""
    import subprocess
    import sys

    script = """
import sys
assert "backend.app.infrastructure.model_registry" not in sys.modules
import backend.app.features.notifications.worker
from backend.app.infrastructure.database import Base
from sqlalchemy.orm import configure_mappers

configure_mappers()
# Sorting resolves foreign keys even for models not queried during bootstrap.
registered = {table.name for table in Base.metadata.sorted_tables}
assert {
    "accounts", "dashboard_sessions", "projects", "environments", "delivery_keys",
    "templates", "template_branches", "template_versions", "template_deployments",
    "provider_configurations", "provider_revisions", "notifications",
    "notification_outbox", "notification_attempts",
} <= registered, registered
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
