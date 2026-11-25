from pathlib import Path

import pytest

from backend.app.infrastructure.settings import Settings


def test_file_secrets_override_environment_values(tmp_path: Path) -> None:
    database = tmp_path / "database"
    metrics = tmp_path / "metrics"
    database.write_text("postgresql+asyncpg://private-credential@postgres/voxriva\n")
    metrics.write_text("private-metrics-token\n")
    settings = Settings(
        database_url="wrong-value",
        database_url_file=database,
        metrics_token_file=metrics,
    )
    assert settings.database_url == database.read_text().strip()
    assert "private-credential" not in repr(settings)
    assert settings.metrics_token is not None
    assert settings.metrics_token.get_secret_value() == "private-metrics-token"
    assert "private-metrics-token" not in repr(settings)


def test_missing_secret_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        Settings(database_url_file=tmp_path / "missing")
