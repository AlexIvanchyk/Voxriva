"""Exercise boundary failures against synthetic projects, without importing apps."""

import runpy
from pathlib import Path

import pytest

CHECKER = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "scripts/check-architecture.py")
)


def source(root, path, content):
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(content)


@pytest.mark.parametrize(
    "statement",
    [
        "from backend.app.features.projects.router import read_project",
        "from ..projects.router import read_project",
        "from ..projects import router",
    ],
)
def test_application_services_cannot_import_http_routers(tmp_path, statement):
    source(tmp_path, "backend/app/features/templates/service.py", statement)
    assert any(
        "application logic imports HTTP router" in error
        for error in CHECKER["violations"](tmp_path)
    )


def test_feature_imports_must_use_canonical_modules(tmp_path):
    source(
        tmp_path,
        "backend/app/features/templates/service.py",
        "from backend.app.catalog import visible_projects",
    )
    assert any(
        "canonical feature imports legacy" in error
        for error in CHECKER["violations"](tmp_path)
    )


def test_test_suites_depend_on_support_instead_of_other_suites(tmp_path):
    source(
        tmp_path,
        "tests/integration/test_projects.py",
        "from tests.integration.test_session import sign_in",
    )
    assert any(
        "tests must import support" in error
        for error in CHECKER["violations"](tmp_path)
    )


@pytest.mark.parametrize(
    "path,statement",
    [
        (
            "frontend/src/shared/api/client.ts",
            'import { token } from "../../features/session/session"',
        ),
        (
            "frontend/src/shared/ui/Button.tsx",
            'import { layout } from "../../app/layout"',
        ),
        (
            "frontend/src/features/projects/project.ts",
            'import { route } from "../../app/router"',
        ),
    ],
)
def test_frontend_lower_layers_cannot_import_application_layers(
    tmp_path, path, statement
):
    source(tmp_path, path, statement)
    assert any("cannot depend on" in error for error in CHECKER["violations"](tmp_path))


def test_support_and_service_dependencies_are_allowed(tmp_path):
    source(
        tmp_path,
        "tests/integration/test_projects.py",
        "from tests.support.administration import sign_in",
    )
    source(
        tmp_path,
        "backend/app/features/templates/router.py",
        "from .service import preview",
    )
    source(
        tmp_path,
        "backend/app/features/templates/service.py",
        "from ..projects.service import visible_projects",
    )
    source(
        tmp_path,
        "frontend/src/features/projects/project.ts",
        'import { request } from "../../shared/api/client"',
    )
    assert CHECKER["violations"](tmp_path) == []


@pytest.mark.parametrize("filename", ["notifications.py", "models.py", "access.py"])
def test_flat_application_modules_are_rejected(tmp_path, filename):
    source(tmp_path, f"backend/app/{filename}", "")
    assert any(
        "flat application modules are forbidden" in error
        for error in CHECKER["violations"](tmp_path)
    )


@pytest.mark.parametrize(
    "statement",
    [
        "from fastapi import Request",
        "import fastapi",
        "from fastapi.responses import JSONResponse",
    ],
)
def test_business_services_cannot_depend_on_http_framework(tmp_path, statement):
    source(tmp_path, "backend/app/features/templates/service.py", statement)
    assert any(
        "business services cannot depend on HTTP framework" in error
        for error in CHECKER["violations"](tmp_path)
    )


def test_infrastructure_cannot_import_feature_services(tmp_path):
    source(
        tmp_path,
        "backend/app/infrastructure/resources.py",
        "from backend.app.features.identity.service import digest",
    )
    assert any(
        "infrastructure cannot depend on feature" in error
        for error in CHECKER["violations"](tmp_path)
    )


def test_model_registry_is_an_explicit_infrastructure_composition_point(tmp_path):
    source(
        tmp_path,
        "backend/app/infrastructure/model_registry.py",
        "from backend.app.features.notifications.models import Notification",
    )
    source(
        tmp_path,
        "backend/app/main.py",
        "from backend.app.features.notifications.router import router",
    )
    source(tmp_path, "backend/app/__init__.py", "")
    assert CHECKER["violations"](tmp_path) == []
