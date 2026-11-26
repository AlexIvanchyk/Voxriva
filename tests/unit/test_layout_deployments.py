"""Deployment service decisions with in-memory versions and mocked persistence."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.features.deployments import layout_contracts, service
from backend.app.features.deployments.schemas import ChangeInput
from backend.app.features.templates import layouts
from backend.app.features.templates.composition import BODY_SLOT
from backend.app.features.templates.models import (
    Template,
    TemplateProject,
    TemplateVersion,
)
from backend.app.features.templates.rendering import DraftContent, LayoutReference
from backend.app.infrastructure.errors import ApplicationError


def published(template, **fields):
    return TemplateVersion(
        id=uuid4(),
        template_id=template.id,
        locale="en",
        content=DraftContent(**fields).model_dump(),
    )


@pytest.fixture
def deployment(monkeypatch):
    scope = ChangeInput(
        scope="environment",
        project_id=uuid4(),
        environment_id=uuid4(),
        locale="en",
        expected_generation=1,
    )
    db = AsyncMock(spec=AsyncSession)
    db.add = Mock()
    # Both contract snapshots enumerate the letter's deployed languages and projects.
    db.scalars.side_effect = [["en"], [scope.project_id], ["en"], [scope.project_id]]
    monkeypatch.setattr(service, "authorize_scope", AsyncMock())
    return db, scope, SimpleNamespace(account=SimpleNamespace(id=uuid4()))


@pytest.mark.parametrize(
    "pinned", [False, True], ids=["active-letter", "pinned-letter"]
)
def test_deploy_checks_effective_letter_even_when_layout_change_is_acknowledged(
    deployment, monkeypatch, pinned
):
    db, scope, principal = deployment
    scope.allow_breaking = True
    layout = Template(id=uuid4(), is_layout=True, fallback_locale="en")
    letter = Template(id=uuid4(), is_layout=False)
    previous = published(layout, html=BODY_SLOT)
    candidate = published(
        layout,
        html=BODY_SLOT,
        variable_schema={
            "type": "object",
            "properties": {"tracking": {"type": "integer"}},
            "required": ["tracking"],
        },
    )
    reference = LayoutReference(
        template_id=layout.id, version_id=previous.id if pinned else None
    )
    child = published(letter, subject="Welcome", html="Hello", layout=reference)
    pointer = SimpleNamespace(version_id=previous.id, generation=1)
    versions = {v.id: v for v in (previous, candidate)}

    async def effective(_db, item, target):
        assert (target.project_id, target.environment_id, target.locale) == (
            scope.project_id,
            scope.environment_id,
            "en",
        )
        saved = child if item.id == letter.id else versions[pointer.version_id]
        return saved, "environment", False

    db.scalar.return_value = layout
    db.get.side_effect = lambda model, key: (
        key == (layout.id, scope.project_id)
        if model is TemplateProject
        else versions[key]
    )
    for module in (service, layout_contracts, layouts):
        monkeypatch.setattr(module, "effective", effective)
    monkeypatch.setattr(service, "slot", AsyncMock(return_value=pointer))
    dependents = AsyncMock(return_value=[letter])
    monkeypatch.setattr(service, "dependent_letters", dependents)

    change = service.change(db, principal, layout, scope, candidate, "deploy")
    if pinned:
        result = asyncio.run(change)
        assert (result.version_id, result.generation) == (candidate.id, 2)
        db.get.assert_any_await(TemplateVersion, previous.id)
        db.commit.assert_awaited_once()
    else:
        with pytest.raises(ApplicationError) as failure:
            asyncio.run(change)
        assert failure.value.status_code == 409
        assert failure.value.detail["code"] == "dependent_template_incompatible"
        assert failure.value.detail["issues"][0]["path"] == "tracking"
        db.commit.assert_not_awaited()
    dependents.assert_awaited_once_with(db, layout.id)


@pytest.mark.parametrize("action", ["deploy", "rollback"])
def test_moving_a_variable_between_letter_and_layout_preserves_sender_contract(
    deployment, monkeypatch, action
):
    db, scope, principal = deployment
    schema = {
        "type": "object",
        "properties": {"brand": {"type": "string"}},
        "required": ["brand"],
        "additionalProperties": False,
    }
    layout = Template(id=uuid4(), is_layout=True)
    letter = Template(id=uuid4(), is_layout=False)
    shell = published(layout, html=BODY_SLOT, variable_schema=schema)
    standalone = published(
        letter, html="Welcome to {{ brand }}", variable_schema=schema
    )
    attached = published(
        letter,
        html="Welcome to {{ brand }}",
        layout=LayoutReference(template_id=layout.id),
    )
    old, new = (standalone, attached) if action == "deploy" else (attached, standalone)
    pointer = SimpleNamespace(version_id=old.id, generation=1)

    async def effective_letter(_db, item, target):
        assert item.id == letter.id and target.environment_id == scope.environment_id
        return (old if pointer.version_id == old.id else new), "environment", False

    monkeypatch.setattr(service, "slot", AsyncMock(return_value=pointer))
    monkeypatch.setattr(service, "effective", effective_letter)
    monkeypatch.setattr(layout_contracts, "effective", effective_letter)
    resolve = AsyncMock(return_value=shell)
    monkeypatch.setattr(layout_contracts, "resolve_layout", resolve)
    result = asyncio.run(service.change(db, principal, letter, scope, new, action))
    assert result.version_id == new.id
    resolve.assert_awaited_once()
    db.commit.assert_awaited_once()
