"""Disposable Compose smoke: fictional data, real SDK over HTTP, no providers."""

import asyncio
import json
import os
import sys
import tempfile

import httpx
import httpx2
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.features.identity.bootstrap import bootstrap
from backend.app.features.identity.schemas import NewAccount
from backend.app.features.notifications.models import Notification, NotificationOutbox
from backend.app.infrastructure.settings import Settings


async def main():
    # Bootstrap fails on an existing installation: this script is intentionally
    # usable only on the disposable smoke stack, never an existing dashboard.
    database_url = Settings().database_url
    account = NewAccount(
        email="mcp-demo@example.test", password="Fictional MCP demo password"
    )
    await bootstrap(database_url, account)
    async with httpx.AsyncClient(
        base_url="http://api:8000",
        timeout=20,
        headers={"X-Voxriva-Client": "dashboard"},
    ) as dashboard:

        async def post(path, payload):
            response = await dashboard.post("/api/v1" + path, json=payload)
            assert response.is_success, (path, response.status_code, response.text)
            return response.json()

        session = await post(
            "/auth/login", {"email": account.email, "password": account.password}
        )
        dashboard.headers["X-CSRF-Token"] = session["csrf_token"]
        project = await post("/projects", {"name": "Fictional Lighthouse"})
        issued = await post(
            "/management-credentials",
            {
                "name": "Disposable MCP smoke",
                "project_ids": [project["id"]],
                "scopes": ["templates:read", "templates:write"],
            },
        )
        async with httpx2.AsyncClient(
            headers={"Authorization": "Bearer " + issued["token"]}
        ) as http:
            async with Client(
                streamable_http_client("http://mcp:8001/mcp", http_client=http)
            ) as client:
                discovery = await client.list_tools()
                names = sorted(tool.name for tool in discovery.tools)
                assert len(names) == 12 and "publish" not in names

                async def call(name, **arguments):
                    response = await client.call_tool(name, arguments)
                    assert not response.is_error, name
                    return response.structured_content

                draft = {
                    "subject": "Welcome {{ name }}",
                    "text": "Hello {{ name }}",
                    "html": '<img src="https://example.invalid/fictional-logo.png"><h1>{{ name }}</h1>',
                    "variable_schema": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                        "required": ["name"],
                        "additionalProperties": False,
                    },
                    "preview_context": {"name": "Synthetic Visitor"},
                    "runtime_defaults": {},
                    "scenarios": {"long": {"name": "Synthetic Long Name"}},
                }
                created = await call(
                    "create_template",
                    payload={
                        "name": "Fictional Welcome",
                        "key": "mcp-smoke-welcome",
                        "channel": "email",
                        "project_ids": [project["id"]],
                        "draft": draft,
                    },
                )
                assert created["ok"]
                template = created["result"]
                assert (await call("list_templates", query="welcome"))["result"][
                    "total"
                ] == 1
                read = await call(
                    "get_template",
                    template_id=template["id"],
                    branch_id=template["branch_id"],
                )
                assert read["result"]["draft_revision"] == 1
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
                # Publishing is a separate authorized dashboard operation to set up
                # a historical source, never an MCP tool or automatic side effect.
                version = await post(
                    f"/templates/{template['id']}/publish",
                    {"branch_id": template["branch_id"], "expected_revision": 1},
                )
                branch = await call(
                    "create_branch",
                    template_id=template["id"],
                    payload={"name": "new-logo", "source_version_id": version["id"]},
                )
                assert branch["result"]["source_version_id"] == version["id"]
                assert (await call("list_branches", template_id=template["id"]))["ok"]
                assert (await call("list_versions", template_id=template["id"]))["ok"]
                assert (
                    await call(
                        "get_version",
                        template_id=template["id"],
                        version_id=version["id"],
                    )
                )["result"]["content"]["subject"] == draft["subject"]
                preview = await call(
                    "preview", template_id=template["id"], payload={"scenario": "long"}
                )
                assert (
                    preview["result"]["rendered"]["subject"]
                    == "Welcome Synthetic Long Name"
                )
                layout = (
                    await call(
                        "create_template",
                        payload={
                            "name": "Fictional Lighthouse layout",
                            "key": "mcp-smoke-layout",
                            "channel": "email",
                            "is_layout": True,
                            "project_ids": [project["id"]],
                            "draft": {
                                "html": "<header>Lighthouse</header><!-- voxriva:body -->"
                            },
                        },
                    )
                )["result"]
                found = await call(
                    "list_templates", is_layout=True, project_id=project["id"]
                )
                assert [item["id"] for item in found["result"]["items"]] == [
                    layout["id"]
                ]
                assert found["result"]["items"][0]["is_layout"]
                layout_path = f"/templates/{layout['id']}"
                published_layout = await post(
                    layout_path + "/publish",
                    {"branch_id": layout["branch_id"], "expected_revision": 1},
                )
                project_path = f"/projects/{project['id']}"
                environment = await post(
                    project_path + "/environments", {"name": "layout-mcp"}
                )
                empty = await post(
                    project_path + "/environments", {"name": "without-layout"}
                )
                target = {
                    "project_id": project["id"],
                    "environment_id": environment["id"],
                }
                await post(
                    layout_path + "/deployments/deploy",
                    {
                        **target,
                        "scope": "environment",
                        "locale": "en",
                        "expected_generation": 0,
                        "version_id": published_layout["id"],
                    },
                )
                proposal = {**draft, "layout": {"template_id": layout["id"]}}
                explicit = await call(
                    "preview",
                    template_id=template["id"],
                    payload={
                        **target,
                        "draft": proposal,
                        "branch_id": template["branch_id"],
                    },
                )
                assert (
                    explicit["result"]["layout"]["version_id"] == published_layout["id"]
                )
                assert (
                    "<header>Lighthouse</header>"
                    in explicit["result"]["rendered"]["html"]
                )
                missing = await call(
                    "preview",
                    template_id=template["id"],
                    payload={
                        **target,
                        "environment_id": empty["id"],
                        "draft": proposal,
                    },
                )
                assert missing["status"] == 422 and not missing["ok"]
                changed = {
                    **draft,
                    "html": draft["html"].replace(
                        "fictional-logo.png", "new-fictional-logo.png"
                    ),
                }
                changes = {
                    "items": [
                        {
                            "template_id": template["id"],
                            "branch_id": identifier,
                            "expected_revision": 1,
                            "draft": changed,
                        }
                        for identifier in [
                            template["branch_id"],
                            language["result"]["id"],
                        ]
                    ]
                }
                plan = await call("plan_changes", changes=changes)
                assert plan["ok"] and len(plan["items"]) == 2
                assert all(
                    "new-fictional-logo.png" in item["diff"] for item in plan["items"]
                )
                # Another editor saves the first branch after review.
                one = {"items": [changes["items"][0]]}
                single = await call("plan_changes", changes=one)
                saved = await call(
                    "apply_changes",
                    changes=one,
                    confirmed_plan_hash=single["plan_hash"],
                    confirm=True,
                )
                assert saved["items"][0]["state"] == "saved"
                applied = await call(
                    "apply_changes",
                    changes=changes,
                    confirmed_plan_hash=plan["plan_hash"],
                    confirm=True,
                )
                assert [item["state"] for item in applied["items"]] == [
                    "conflict",
                    "saved",
                ]
                concurrent = {
                    "items": [
                        {
                            **changes["items"][0],
                            "expected_revision": 2,
                            "draft": {**changed, "subject": "Concurrent {{ name }}"},
                        }
                    ]
                }
                concurrent_plan = await call("plan_changes", changes=concurrent)
                raced = await asyncio.gather(
                    *[
                        call(
                            "apply_changes",
                            changes=concurrent,
                            confirmed_plan_hash=concurrent_plan["plan_hash"],
                            confirm=True,
                        )
                        for _ in range(2)
                    ]
                )
                concurrency = sorted(result["items"][0]["state"] for result in raced)
                assert concurrency == ["conflict", "saved"]
                immutable = await call(
                    "get_version", template_id=template["id"], version_id=version["id"]
                )
                assert immutable["result"]["content"]["html"] == draft["html"]
                invalid = await client.call_tool(
                    "create_template",
                    {
                        "payload": {
                            "key": "INVALID",
                            "password": "synthetic-secret-must-be-redacted",
                        }
                    },
                )
                assert (
                    invalid.is_error
                    and "synthetic-secret-must-be-redacted" not in str(invalid)
                )
        with tempfile.NamedTemporaryFile(mode="w", dir="/tmp") as token_file:
            token_file.write(issued["token"])
            token_file.flush()
            parameters = StdioServerParameters(
                command=sys.executable,
                args=["-m", "backend.mcp_server", "--transport", "stdio"],
                env={**os.environ, "VOXRIVA_MCP_TOKEN_FILE": token_file.name},
            )
            async with Client(parameters) as local:
                response = await local.call_tool("list_templates", {"query": "welcome"})
                assert response.structured_content["result"]["total"] == 1
        response = await dashboard.delete(
            "/api/v1/management-credentials/" + issued["credential"]["id"]
        )
        assert response.status_code == 204
        async with httpx.AsyncClient() as raw:
            assert (
                await raw.post(
                    "http://mcp:8001/mcp",
                    headers={"Authorization": "Bearer " + issued["token"]},
                    json={},
                )
            ).status_code == 401
            assert (await raw.post("http://mcp:8001/mcp", json={})).status_code == 401
        await dashboard.post("/api/v1/auth/logout")
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        async with async_sessionmaker(engine)() as db:
            assert await db.scalar(select(func.count()).select_from(Notification)) == 0
            assert (
                await db.scalar(select(func.count()).select_from(NotificationOutbox))
                == 0
            )
    finally:
        await engine.dispose()
    print(
        json.dumps(
            {
                "sdk": "mcp 2.3.0",
                "transport": "Streamable HTTP",
                "stdio_read": "passed",
                "database": "PostgreSQL",
                "tools": names,
                "read_create_language_branch_preview": "passed",
                "batch": ["conflict", "saved"],
                "layout_discovery_and_environment_preview": "passed",
                "postgres_concurrent_saves": concurrency,
                "immutable_version": "unchanged",
                "secret_redaction": "passed",
                "revocation": "401",
                "notifications": 0,
                "outbox": 0,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
