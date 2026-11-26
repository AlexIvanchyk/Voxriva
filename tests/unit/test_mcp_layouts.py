import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.features.management import authoring_service as management
from backend.app.features.management.schemas import ChangeSet
from backend.app.features.management.service import Author
from backend.app.features.projects.models import Project
from backend.app.features.templates import layouts
from backend.app.features.templates import service as templates
from backend.app.features.templates import versions_service as versions
from backend.app.features.templates.composition import BODY_SLOT
from backend.app.features.templates.models import (
    Template,
    TemplateBranch,
    TemplateVersion,
)
from backend.app.features.templates.rendering import DraftContent
from backend.app.features.templates.versions_schemas import PublishInput
from backend.app.infrastructure.errors import ApplicationError
from backend.mcp_server import create_server


@pytest.fixture
def authoring(monkeypatch):
    db = Mock(spec=AsyncSession)

    @asynccontextmanager
    async def session():
        yield db

    project_id = uuid4()
    account = SimpleNamespace(id=uuid4(), platform_admin=True)
    principal = SimpleNamespace(account=account, project_ids=frozenset({project_id}))
    credential = SimpleNamespace(
        project_ids=[str(project_id)], scopes=["templates:read", "templates:write"]
    )
    author = Author(principal, credential)
    monkeypatch.setattr(management, "authenticate", AsyncMock(return_value=author))
    access = AsyncMock()
    monkeypatch.setattr(management, "template_access", access)
    runtime = SimpleNamespace(
        settings=None, preview_limits={}, preview_slots=asyncio.Semaphore(1)
    )
    return (
        create_server(management.Authoring(session, runtime), "test"),
        db,
        author,
        access,
        runtime,
    )


async def call(server, tool, **arguments):
    result = await server.call_tool(tool, arguments)
    assert not result.is_error
    return result.structured_content


def test_mcp_discovers_and_creates_layouts_under_existing_access_checks(
    monkeypatch, authoring
):
    server, db, author, access, _ = authoring
    layout_id, hidden_id, letter_id = uuid4(), uuid4(), uuid4()
    project_id = next(iter(author.project_ids))

    def item(identifier, name, is_layout):
        return templates.TemplateView(
            id=identifier,
            name=name,
            key=name.lower(),
            channel="email",
            is_layout=is_layout,
            draft=DraftContent(),
            draft_revision=1,
            updated_at=datetime.now(UTC),
            branch_id=uuid4(),
            branch_name="main",
            locale="en",
            fallback_locale="en",
            primary_locale="en",
            languages=["en"],
            has_published_versions=False,
            projects=[{"id": project_id, "name": "Allowed project"}],
            project_count=1,
            editable=True,
            manage_bindings=True,
        )

    layout = item(layout_id, "Layout", True)
    letter = item(letter_id, "Letter", False)
    catalog = AsyncMock(return_value=[item(hidden_id, "Hidden", True), layout, letter])
    monkeypatch.setattr(templates, "list_templates", catalog)
    create = AsyncMock(return_value=layout)
    monkeypatch.setattr(templates, "create_template", create)

    async def enforce_access(db, author, template_id, **kwargs):
        if template_id == hidden_id:
            raise ApplicationError(404, "Template not found in credential scope")

    access.side_effect = enforce_access

    async def scenario():
        tools = {tool.name: tool for tool in await server.list_tools()}
        assert {
            "list_versions",
            "get_version",
            "preview",
            "plan_changes",
            "apply_changes",
        } <= tools.keys()
        assert not {"publish", "deploy", "send"} & tools.keys()

        found = await call(
            server, "list_templates", is_layout=True, project_id=project_id, limit=1
        )
        catalog.assert_awaited_once_with(db, author.principal, project_id)
        assert found["result"]["total"] == 1
        assert found["result"]["items"][0]["id"] == str(layout_id)
        assert (await call(server, "list_templates", is_layout=False))["result"][
            "items"
        ][0]["id"] == str(letter_id)
        assert (await call(server, "list_templates"))["result"]["total"] == 2

        payload = {
            "name": "Layout",
            "key": "layout",
            "channel": "email",
            "project_ids": [project_id],
        }
        created = await call(
            server,
            "create_template",
            payload={**payload, "is_layout": True, "draft": {"html": BODY_SLOT}},
        )
        assert created["result"]["is_layout"] is True
        assert create.await_args.args[0].draft.html == BODY_SLOT
        assert create.await_args.args[0].is_layout is True

        denied = await call(
            server,
            "create_template",
            payload={**payload, "draft": {"layout": {"template_id": hidden_id}}},
        )
        assert denied["status"] == 404
        create.assert_awaited_once()

    asyncio.run(scenario())


def test_mcp_plans_active_layout_then_saves_pin_for_dashboard_publication(
    monkeypatch, authoring
):
    server, db, author, access, runtime = authoring
    project_id = next(iter(author.project_ids))
    layout_id, template_id, branch_id, environment_id = (uuid4() for _ in range(4))
    layout = SimpleNamespace(id=layout_id, is_layout=True, fallback_locale="en")
    letter = SimpleNamespace(id=template_id, is_layout=False, channel="email")
    branch = SimpleNamespace(
        id=branch_id, name="main", locale="en", draft_revision=1, source_version_id=None
    )
    shell_branch = SimpleNamespace(name="main")
    body = DraftContent(subject="Hello", html="<p>Letter</p>")
    branch.draft = body.model_dump()

    def version(number, header):
        return TemplateVersion(
            id=uuid4(),
            template_id=layout_id,
            branch_id=uuid4(),
            number=number,
            locale="en",
            parent_version_id=None,
            draft_revision=number,
            message=header,
            actor_id=author.principal.account.id,
            created_at=datetime.now(UTC),
            content=DraftContent(
                html=f"<header>{header}</header>" + BODY_SLOT
            ).model_dump(),
        )

    pinned, active = version(1, "Pinned"), version(2, "Active")

    def get(model, key):
        if model is TemplateBranch:
            return branch
        return pinned if key == pinned.id else True

    db.get.side_effect = get

    def scalars(statement):
        if statement.column_descriptions[0]["entity"] is TemplateVersion:
            return [active, pinned]
        return [project_id]

    db.scalars.side_effect = scalars

    async def scalar(statement):
        params = statement.compile().params
        if statement.is_update:
            branch.draft = params["draft"]
            branch.draft_revision += 1
            return branch_id
        selected = statement.column_descriptions[0]["entity"]
        if selected is Template:
            return layout
        if selected is Project:
            assert params["id_1"] == [project_id]
            if params["id_2"] != project_id:
                return None
        return project_id

    db.scalar.side_effect = scalar
    monkeypatch.setattr(layouts, "scoped_environment", AsyncMock())
    effective = AsyncMock(return_value=(active, "environment", True))
    monkeypatch.setattr(layouts, "effective", effective)
    get_branch = AsyncMock(
        side_effect=lambda db, identifier, selected: (
            branch if identifier == template_id else shell_branch
        )
    )
    lookup = AsyncMock(
        side_effect=lambda db, principal, identifier, **kwargs: (
            letter if identifier == template_id else layout
        )
    )
    for module in (templates, versions):
        monkeypatch.setattr(module, "lookup", lookup)
        monkeypatch.setattr(module, "get_branch", get_branch)
    monkeypatch.setattr(
        templates,
        "view",
        AsyncMock(
            side_effect=lambda *args: SimpleNamespace(
                draft=DraftContent.model_validate(branch.draft),
                draft_revision=branch.draft_revision,
            )
        ),
    )
    monkeypatch.setattr(versions, "head", AsyncMock(return_value=None))
    monkeypatch.setattr(versions, "author", AsyncMock(return_value="Editor"))

    target = {"project_id": project_id, "environment_id": environment_id}

    def change(version_id=None, **scope):
        return {
            "items": [
                {
                    "template_id": template_id,
                    "branch_id": branch_id,
                    "expected_revision": 1,
                    "draft": {
                        **body.model_dump(),
                        "layout": {"template_id": layout_id, "version_id": version_id},
                    },
                    **scope,
                }
            ]
        }

    async def scenario():
        proposed = change(**target)
        plan = await call(server, "plan_changes", changes=proposed)
        assert plan["ok"], plan
        preview = plan["items"][0]["preview"]
        assert preview["rendered"]["html"] == "<header>Active</header><p>Letter</p>"
        assert preview["layout"]["version_id"] == str(active.id)
        assert effective.await_args.args[2].environment_id == environment_id
        assert branch.draft["layout"] is None

        outside_scope = await call(
            server,
            "plan_changes",
            changes=change(project_id=uuid4(), environment_id=environment_id),
        )
        assert outside_scope["items"][0]["status"] == 404

        available = await call(server, "list_versions", template_id=layout_id)
        assert [version["id"] for version in available["result"]] == [
            str(active.id),
            str(pinned.id),
        ]
        pinned_change = change(available["result"][1]["id"], **target)
        direct = await call(
            server,
            "preview",
            template_id=template_id,
            payload={
                **target,
                "draft": pinned_change["items"][0]["draft"],
                "branch_id": branch_id,
            },
        )
        assert direct["result"]["layout"]["version_id"] == str(pinned.id)
        plan = await call(server, "plan_changes", changes=pinned_change)
        denied = await call(
            server,
            "apply_changes",
            changes=change(pinned.id, **{**target, "environment_id": uuid4()}),
            confirmed_plan_hash=plan["plan_hash"],
            confirm=True,
        )
        assert denied["status"] == 422
        applied = await call(
            server,
            "apply_changes",
            changes=pinned_change,
            confirmed_plan_hash=plan["plan_hash"],
            confirm=True,
        )
        assert applied["items"][0]["state"] == "saved"
        access.assert_awaited_with(db, author, template_id, write=True)
        assert effective.await_count == 1

        published = await versions.publish(
            template_id,
            PublishInput(branch_id=branch_id, expected_revision=2, **target),
            runtime,
            db,
            author.principal,
        )
        assert published.content.layout.version_id == pinned.id
        assert published.content.html == body.html

        immutable = next(
            call.args[0]
            for call in db.add.call_args_list
            if isinstance(call.args[0], TemplateVersion)
        )
        monkeypatch.setattr(versions, "version", AsyncMock(return_value=immutable))
        branch.draft = body.model_dump()
        published_preview = await call(
            server,
            "preview",
            template_id=template_id,
            version_id=published.id,
            payload=target,
        )
        assert published_preview["result"]["layout"]["version_id"] == str(pinned.id)
        assert published_preview["result"]["rendered"]["html"] == (
            "<header>Pinned</header><p>Letter</p>"
        )

    asyncio.run(scenario())

    changes = ChangeSet.model_validate(change())
    canonical = json.dumps(
        changes.model_dump(
            mode="json",
            exclude={"items": {"__all__": {"project_id", "environment_id"}}},
        ),
        sort_keys=True,
        separators=(",", ":"),
    )
    assert management.plan_hash(changes) == sha256(canonical.encode()).hexdigest()
