"""Real domain/DB tests plus official SDK client over authenticated HTTP."""

import asyncio
import json
import socket
from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import httpx2
import pytest
import uvicorn
from fastapi.testclient import TestClient
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import func, select

from backend.app.features.identity.models import Account, AuditEvent
from backend.app.features.identity.schemas import Principal
from backend.app.features.management.authoring_service import Authoring
from backend.app.features.management.models import ManagementCredential
from backend.app.features.management.schemas import ChangeSet
from backend.app.features.management.service import issue
from backend.app.features.notifications.models import Notification, NotificationOutbox
from backend.app.features.projects.models import Membership
from backend.app.features.templates.rendering import DraftContent
from backend.app.features.templates.schemas import PreviewInput, TemplateInput
from backend.app.features.templates.versions_schemas import LanguageInput
from backend.app.infrastructure.context import ApplicationContext
from backend.app.infrastructure.database import utcnow
from backend.app.infrastructure.errors import ApplicationError
from backend.app.infrastructure.settings import Settings
from backend.mcp_server import create_server, http_app
from tests.support.administration import PASSWORD, ROOT, application, create, sign_in
from tests.support.lifecycle import draft, publish

pytestmark = pytest.mark.integration


def runtime():
    return ApplicationContext(
        asyncio.Semaphore(2),
        Settings(),
        {},
        asyncio.Semaphore(2),
        {},
        asyncio.Semaphore(2),
        {},
    )


@pytest.fixture
def authoring_setup(store):
    with TestClient(application(store)) as client:
        sign_in(client)
        project = create(client, "/projects", name="Fictional Observatory")
        other = create(client, "/projects", name="Fictional Garden")
        template = create(
            client,
            "/templates",
            name="Welcome",
            key="mcp-welcome",
            channel="email",
            project_ids=[project["id"]],
            draft=draft().model_dump(),
        )
        outside = create(
            client,
            "/templates",
            name="Outside",
            key="outside",
            channel="email",
            project_ids=[other["id"]],
        )

        def credential(write=True, projects=None):
            return create(
                client,
                "/management-credentials",
                name="Synthetic MCP",
                project_ids=projects or [project["id"]],
                scopes=["templates:read", "templates:write"]
                if write
                else ["templates:read"],
            )

        issued, readonly = credential(), credential(False)
        yield {
            "client": client,
            "project": project,
            "other": other,
            "template": template,
            "outside": outside,
            "issued": issued,
            "readonly": readonly,
            "credential": credential,
            "factory": store[1],
        }


def changes_for(template, revision=1, subject="Updated {{ name }}"):
    return ChangeSet.model_validate(
        {
            "items": [
                {
                    "template_id": template["id"],
                    "branch_id": template["branch_id"],
                    "expected_revision": revision,
                    "draft": draft(subject).model_dump(),
                }
            ]
        }
    )


def test_credentials_require_dashboard_csrf_and_never_list_hash_or_token(
    authoring_setup,
):
    s = authoring_setup
    client = s["client"]
    listing = client.get(f"{ROOT}/management-credentials")
    assert listing.status_code == 200
    assert s["issued"]["token"] not in listing.text
    assert "token_hash" not in listing.text
    csrf = client.headers.pop("X-CSRF-Token")
    assert (
        client.delete(
            f"{ROOT}/management-credentials/{s['issued']['credential']['id']}"
        ).status_code
        == 403
    )
    client.headers["X-CSRF-Token"] = csrf
    client.cookies.clear()
    assert (
        client.get(
            f"{ROOT}/management-credentials",
            headers={"Authorization": "Bearer " + s["issued"]["token"]},
        ).status_code
        == 401
    )


def test_scopes_readonly_revocation_expiry_and_no_delivery_key_auth(authoring_setup):
    s = authoring_setup

    async def scenario():
        service = Authoring(s["factory"], runtime())
        token = s["issued"]["token"]
        readonly = s["readonly"]["token"]
        required = Authoring(
            s["factory"], replace(runtime(), settings=Settings(mfa_policy="required"))
        )
        assert (await required.call(token, "list_templates"))["status"] == 401
        inventory = await service.call(token, "list_templates")
        assert [item["id"] for item in inventory["result"]["items"]] == [
            s["template"]["id"]
        ]
        assert (
            await service.call(
                token,
                "get_template",
                template_id=UUID(s["outside"]["id"]),
                branch_id=None,
            )
        )["status"] == 404
        assert (
            await service.call(
                readonly, "plan_changes", changes=changes_for(s["template"])
            )
        )["items"][0]["status"] == 403
        assert (await service.call("vxk_" + "a" * 43, "list_templates"))[
            "status"
        ] == 401
        assert (
            await service.call(
                token,
                "get_template",
                template_id=UUID(s["template"]["id"]),
                branch_id=UUID(s["outside"]["branch_id"]),
            )
        )["status"] == 404
        assert (
            await service.call(
                token,
                "add_language",
                template_id=UUID(s["template"]["id"]),
                payload=LanguageInput(
                    locale="uk",
                    source_branch_id=s["template"]["branch_id"],
                    expected_revision=99,
                ),
            )
        )["status"] == 409
        assert (
            await service.call(
                readonly,
                "preview",
                template_id=UUID(s["template"]["id"]),
                payload=PreviewInput(),
                version_id=None,
            )
        )["ok"]
        async with s["factory"]() as db:
            item = await db.get(
                ManagementCredential, UUID(s["issued"]["credential"]["id"])
            )
            item.expires_at = utcnow() - timedelta(seconds=1)
            await db.commit()
        assert (await service.call(token, "list_templates"))["status"] == 401

    asyncio.run(scenario())
    identifier = s["readonly"]["credential"]["id"]
    assert (
        s["client"].delete(f"{ROOT}/management-credentials/{identifier}").status_code
        == 204
    )
    assert (
        asyncio.run(
            Authoring(s["factory"], runtime()).call(
                s["readonly"]["token"], "list_templates"
            )
        )["status"]
        == 401
    )


def test_batch_planning_is_readonly_explicit_apply_reports_conflicts_and_invalid(
    authoring_setup,
):
    s = authoring_setup

    async def scenario():
        service = Authoring(s["factory"], runtime())
        token = s["issued"]["token"]
        language = await service.call(
            token,
            "add_language",
            template_id=UUID(s["template"]["id"]),
            payload=LanguageInput(
                locale="uk",
                source_branch_id=s["template"]["branch_id"],
                expected_revision=1,
            ),
        )
        assert language["ok"]
        changes = changes_for(s["template"])
        second = changes.items[0].model_copy(
            update={"branch_id": UUID(language["result"]["id"])}
        )
        changes = ChangeSet(items=[changes.items[0], second])
        async with s["factory"]() as db:
            before = await db.scalar(select(func.count()).select_from(AuditEvent))
        planned = await service.call(token, "plan_changes", changes=changes)
        assert planned["ok"] and planned["atomic"] is False
        assert "Updated" in planned["items"][0]["diff"]
        async with s["factory"]() as db:
            assert (
                await db.scalar(select(func.count()).select_from(AuditEvent)) == before
            )
            assert await db.scalar(select(func.count()).select_from(Notification)) == 0
            assert (
                await db.scalar(select(func.count()).select_from(NotificationOutbox))
                == 0
            )
        denied = await service.call(
            token,
            "apply_changes",
            changes=changes,
            confirmed_plan_hash=planned["plan_hash"],
        )
        assert denied["status"] == 422
        assert (
            await service.call(
                token,
                "apply_changes",
                changes=changes,
                confirmed_plan_hash="wrong",
                confirm=True,
            )
        )["status"] == 422
        # An independent editor saves one branch after review, making only that item stale.
        one = ChangeSet(items=[changes.items[0]])
        one_plan = await service.call(token, "plan_changes", changes=one)
        assert (
            await service.call(
                token,
                "apply_changes",
                changes=one,
                confirmed_plan_hash=one_plan["plan_hash"],
                confirm=True,
            )
        )["ok"]
        result = await service.call(
            token,
            "apply_changes",
            changes=changes,
            confirmed_plan_hash=planned["plan_hash"],
            confirm=True,
        )
        assert [item["state"] for item in result["items"]] == ["conflict", "saved"]
        assert result["ok"] is False
        invalid = ChangeSet(
            items=[
                second.model_copy(
                    update={
                        "expected_revision": 2,
                        "draft": DraftContent(subject="{{ missing }}", text="Hi"),
                    }
                )
            ]
        )
        invalid_plan = await service.call(token, "plan_changes", changes=invalid)
        assert not invalid_plan["ok"]
        result = await service.call(
            token,
            "apply_changes",
            changes=invalid,
            confirmed_plan_hash=invalid_plan["plan_hash"],
            confirm=True,
        )
        assert result["items"][0]["state"] == "invalid"

    asyncio.run(scenario())


def test_shared_template_scopes_and_live_role_removal(authoring_setup):
    s = authoring_setup
    client = s["client"]
    shared = create(
        client,
        "/templates",
        name="Shared",
        key="mcp-shared",
        channel="email",
        project_ids=[s["project"]["id"], s["other"]["id"]],
        draft=draft().model_dump(),
    )
    create(
        client,
        "/members",
        email="mcp-editor@example.test",
        display_name="Synthetic Editor",
        password=PASSWORD,
        projects=[
            {"project_id": project["id"], "role": "template_editor"}
            for project in [s["project"], s["other"]]
        ],
    )

    async def scenario():
        service = Authoring(s["factory"], runtime())
        # Even a platform admin's credential cannot edit beyond its project scope.
        result = await service.call(
            s["issued"]["token"], "plan_changes", changes=changes_for(shared)
        )
        assert result["items"][0]["status"] == 404
        visible = await service.call(
            s["issued"]["token"],
            "get_template",
            template_id=UUID(shared["id"]),
            branch_id=None,
        )
        assert (
            len(visible["result"]["projects"]) == 1
            and not visible["result"]["editable"]
        )
        async with s["factory"]() as db:
            account = await db.scalar(
                select(Account).where(Account.email == "mcp-editor@example.test")
            )
            from backend.app.features.management.schemas import CredentialInput

            issued = await issue(
                CredentialInput(
                    name="Live roles",
                    project_ids=[s["project"]["id"], s["other"]["id"]],
                    scopes=["templates:read", "templates:write"],
                ),
                db,
                Principal(account, ""),
            )
            account_id = account.id
        assert (
            await service.call(
                issued.token, "plan_changes", changes=changes_for(shared)
            )
        )["ok"]
        async with s["factory"]() as db:
            membership = await db.get(Membership, (UUID(s["other"]["id"]), account_id))
            membership.role = "viewer"
            await db.commit()
        assert (
            await service.call(
                issued.token, "plan_changes", changes=changes_for(shared)
            )
        )["items"][0]["status"] == 403
        # Keep an out-of-scope membership while removing the only in-scope one.
        async with s["factory"]() as db:
            account = await db.get(Account, account_id)
            from backend.app.features.management.schemas import CredentialInput

            narrow = await issue(
                CredentialInput(name="Narrow", project_ids=[s["project"]["id"]]),
                db,
                Principal(account, ""),
            )
            membership = await db.get(
                Membership, (UUID(s["project"]["id"]), account_id)
            )
            await db.delete(membership)
            await db.commit()
        assert (
            await service.call(
                narrow.token,
                "get_template",
                template_id=UUID(shared["id"]),
                branch_id=None,
            )
        )["status"] == 404
        assert (await service.call(narrow.token, "list_templates"))["result"][
            "total"
        ] == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("fault_kind", ["unexpected", "domain_after_commit"])
def test_batch_retains_results_after_lost_save_acknowledgement(
    authoring_setup, monkeypatch, fault_kind
):
    from backend.app.features.templates import service as templates

    s = authoring_setup

    async def scenario():
        service = Authoring(s["factory"], runtime())
        token = s["issued"]["token"]
        language = await service.call(
            token,
            "add_language",
            template_id=UUID(s["template"]["id"]),
            payload=LanguageInput(
                locale="uk",
                source_branch_id=s["template"]["branch_id"],
                expected_revision=1,
            ),
        )
        first = changes_for(s["template"]).items[0]
        second = first.model_copy(update={"branch_id": UUID(language["result"]["id"])})
        changes = ChangeSet(items=[first, second])
        plan = await service.call(token, "plan_changes", changes=changes)
        original = templates.save_draft

        async def lost_ack(*args, **kwargs):
            result = await original(*args, **kwargs)
            if result.branch_id == first.branch_id:
                if fault_kind == "domain_after_commit":
                    raise ApplicationError(
                        403, "synthetic secret must not be reflected"
                    )
                raise RuntimeError("synthetic secret must not be reflected")
            return result

        monkeypatch.setattr(templates, "save_draft", lost_ack)
        applied = await service.call(
            token,
            "apply_changes",
            changes=changes,
            confirmed_plan_hash=plan["plan_hash"],
            confirm=True,
        )
        assert [item["state"] for item in applied["items"]] == ["unknown", "saved"]
        assert "synthetic secret" not in str(applied)
        read = await service.call(
            token,
            "get_template",
            template_id=first.template_id,
            branch_id=first.branch_id,
        )
        assert read["result"]["draft_revision"] == 2

    asyncio.run(scenario())


def test_real_sdk_streamable_http_discovery_authoring_preview_and_batch(
    authoring_setup,
):
    s = authoring_setup
    s["version"] = publish(s["client"], s["template"])

    async def scenario():
        # A real TCP server and the official MCP client's real Streamable HTTP
        # transport, not an in-memory Client(server) bypass of authorization.
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}/mcp"
        server = uvicorn.Server(
            uvicorn.Config(
                http_app(
                    create_server(Authoring(s["factory"], runtime())), s["factory"], url
                ),
                log_level="error",
                lifespan="on",
            )
        )
        task = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    if task.done():
                        await task
                    await asyncio.sleep(0.01)
            async with httpx2.AsyncClient(
                headers={"Authorization": "Bearer " + s["issued"]["token"]}
            ) as http:
                async with Client(
                    streamable_http_client(url, http_client=http)
                ) as client:
                    tools = await client.list_tools()
                    names = {tool.name for tool in tools.tools}
                    assert {
                        "get_template",
                        "create_template",
                        "preview",
                        "plan_changes",
                        "apply_changes",
                    } <= names
                    assert not names & {"publish", "send", "deploy", "replay"}

                    async def call(name, **args):
                        response = await client.call_tool(name, args)
                        assert not response.is_error, response
                        return response.structured_content

                    found = await call("list_templates", query="welcome")
                    assert found["result"]["total"] == 1
                    created = await call(
                        "create_template",
                        payload=TemplateInput(
                            name="Synthetic MCP Demo",
                            key="mcp-demo",
                            channel="email",
                            project_ids=[UUID(s["project"]["id"])],
                            draft=draft(),
                        ).model_dump(mode="json"),
                    )
                    assert created["ok"]
                    template = created["result"]
                    current = await call(
                        "get_template",
                        template_id=template["id"],
                        branch_id=template["branch_id"],
                    )
                    assert current["result"]["draft_revision"] == 1
                    preview = await call(
                        "preview",
                        template_id=template["id"],
                        payload={"branch_id": template["branch_id"]},
                    )
                    assert preview["result"]["errors"] == []
                    assert (
                        preview["result"]["rendered"]["subject"]
                        == "Hello Synthetic Example"
                    )
                    language = await call(
                        "add_language",
                        template_id=template["id"],
                        payload={
                            "locale": "uk",
                            "source_branch_id": template["branch_id"],
                            "expected_revision": 1,
                        },
                    )
                    assert language["ok"]
                    forked = await call(
                        "create_branch",
                        template_id=s["template"]["id"],
                        payload={
                            "name": "logo-refresh",
                            "source_version_id": s["version"]["id"],
                        },
                    )
                    assert forked["result"]["source_version_id"] == s["version"]["id"]
                    changes = changes_for(template).model_dump(mode="json")
                    plan = await call("plan_changes", changes=changes)
                    assert plan["ok"] and plan["items"][0]["diff"]
                    applied = await call(
                        "apply_changes",
                        changes=changes,
                        confirmed_plan_hash=plan["plan_hash"],
                        confirm=True,
                    )
                    assert applied["items"][0]["state"] == "saved"
                    repeated = await call(
                        "apply_changes",
                        changes=changes,
                        confirmed_plan_hash=plan["plan_hash"],
                        confirm=True,
                    )
                    assert repeated["items"][0]["state"] == "conflict"
                    invalid = await client.call_tool(
                        "create_template",
                        {
                            "payload": {
                                "key": "BAD",
                                "password": "never-echo-this-synthetic-secret",
                            }
                        },
                    )
                    assert invalid.is_error
                    assert "never-echo-this-synthetic-secret" not in str(invalid)
                    print(
                        json.dumps(
                            {
                                "transport": "streamable-http",
                                "tools": sorted(names),
                                "read_create_language_branch_preview": "passed",
                                "save": "saved",
                                "repeat": "conflict",
                            }
                        )
                    )
            async with httpx2.AsyncClient() as raw:
                assert (await raw.post(url, json={})).status_code == 401
                headers = {
                    "Authorization": "Bearer " + s["issued"]["token"],
                    "Origin": "https://evil.invalid",
                }
                assert (
                    await raw.post(url, headers=headers, json={})
                ).status_code == 403
                headers = {
                    "Authorization": "Bearer " + s["issued"]["token"],
                    "Host": "evil.invalid",
                }
                assert (
                    await raw.post(url, headers=headers, json={})
                ).status_code == 421
        finally:
            server.should_exit = True
            await task
            sock.close()

    asyncio.run(scenario())


def test_mcp_image_draft_plan_apply_preview_and_schema_are_supported(authoring_setup):
    from backend.app.features.templates.images import image_schema
    from tests.support.images import image_value
    s = authoring_setup
    async def scenario():
        service = Authoring(s["factory"], runtime())
        token = s["issued"]["token"]
        content = draft().model_dump()
        content["images"] = {"logo": image_value()}
        content["html"] = '<img src="voxriva-image:logo"><img src="{{ banner }}">'
        content["variable_schema"]["properties"]["banner"] = image_schema()
        content["preview_context"]["banner"] = image_value("blue")
        changes = ChangeSet.model_validate({"items": [{"template_id": s["template"]["id"], "branch_id": s["template"]["branch_id"], "expected_revision": 1, "draft": content}]})
        planned = await service.call(token, "plan_changes", changes=changes)
        assert planned["ok"]
        applied = await service.call(token, "apply_changes", changes=changes, confirmed_plan_hash=planned["plan_hash"], confirm=True)
        assert applied["items"][0]["state"] == "saved"
        preview = await service.call(token, "preview", template_id=UUID(s["template"]["id"]), version_id=None, payload=PreviewInput())
        assert preview["ok"] and not preview["result"]["errors"]
        assert len(preview["result"]["rendered"]["images"]) == 2
        blocked = await service.call(s["readonly"]["token"], "apply_changes", changes=changes, confirmed_plan_hash=planned["plan_hash"], confirm=True)
        assert not blocked["items"][0]["ok"]
        invalid = content.copy()
        invalid["images"] = {"logo": {"media_type": "image/png", "content_base64": "AAAA"}}
        with pytest.raises(ValueError):
            DraftContent.model_validate(invalid)
    asyncio.run(scenario())
