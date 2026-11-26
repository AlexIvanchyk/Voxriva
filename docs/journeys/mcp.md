# Edit templates with an AI client

Ask an AI client to find a template, adjust wording or languages, and show diffs
and rendered previews before saving. Voxriva's self-hosted MCP service gives the
client scoped access to drafts, typed variables and version history. Your client
provides the AI model; publish and deploy remain explicit dashboard actions.

## 1. Start the local MCP service

This walkthrough uses the **persistent local installation**, separate from the
isolated first-email example. Follow [persistent local configuration](../configuration.md#deployment-modes)
to start that stack and bootstrap an administrator. In the dashboard, create a
project and connect a template to it; the [dashboard guide](../dashboard.md) and
[workspace setup](workspace.md) explain these tasks.

From the repository root, add MCP to that same stack:

```sh
docker compose -f compose.yaml -f compose.mcp.yaml up -d --build api mcp
```

The default HTTP endpoint is `http://127.0.0.1:8001/mcp`. If you set
`VOXRIVA_MCP_PORT`, use the matching port. The API and MCP must use the same
database and migration revision. Credentials from the isolated example belong
to its separate database and cannot authorize this installation.

For a prebuilt deployment, the [operator download](https://github.com/AlexIvanchyk/Voxriva/releases/tag/v0.1.1)
also includes `compose.mcp.production.yaml`. Its matching image is
`ghcr.io/alexivanchyk/voxriva-mcp:0.1.1`; select it with `VOXRIVA_MCP_IMAGE` and
set `VOXRIVA_MCP_PUBLIC_URL` for that installation. Follow the
[self-hosting guide](../self-hosting.md); no checkout or image build is needed.

## 2. Create an authoring credential

In **API keys**, select **Purpose → Template / MCP**. Name the credential, select
the template's project and an expiry, and start with `templates:read`. Copy the
one-time secret into your client's secret store. Use **Connect** for endpoint
instructions. Add `templates:write` when you are ready to save changes and your
project roles permit them.

A Delivery key is for notification requests; it cannot authorize MCP. MFA-required
installations also require the authoring account to complete enrollment. See
[credential scopes](../credentials.md) for shared-template access and revocation.

## 3. Make a first read with the tested client

The project's protocol tests use the **official Python MCP SDK 2.3.0** over
Streamable HTTP with a custom bearer header. With Python 3.12+, create a separate
client environment:

```sh
python3 -m venv /tmp/voxriva-mcp-client
/tmp/voxriva-mcp-client/bin/python -m pip install 'mcp==2.3.0'
```

Save this as `mcp-read.py` and run it with that environment's Python. It prompts
for your Template / MCP credential without echoing it, lists available tools and
reads template metadata. It makes no changes:

```python
import asyncio
from getpass import getpass

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


async def main(token):
    async with httpx2.AsyncClient(
        headers={"Authorization": "Bearer " + token}
    ) as http:
        async with Client(streamable_http_client(
            "http://127.0.0.1:8001/mcp", http_client=http
        )) as client:
            tools = await client.list_tools()
            print([tool.name for tool in tools.tools])
            result = await client.call_tool("list_templates", {"limit": 5})
            if result.is_error:
                raise RuntimeError("Template listing failed; check credential scope and roles")
            print(result.structured_content)


asyncio.run(main(getpass("Template / MCP credential: ")))
```

Expect authoring tools such as `list_templates`, `get_template` and `preview`.
The template listing is scoped to your selected projects and current roles. An
empty list means no visible templates; check the project's template connections.

Other clients must support Streamable HTTP and custom Authorization headers,
or launch the [documented stdio transport](../../MCP.md#production-and-stdio).
OAuth-only connectors cannot connect to this static-bearer service. No broader
AI-client compatibility is claimed by the Python protocol tests.

## 4. Preview a proposed edit, then save deliberately

Once your AI client is connected, try a read-only request:

> Find my welcome template, read its exact saved draft and render a preview with
> fictional test data. Show any validation errors. Do not save changes.

For an editing session with a write credential:

> Propose clearer welcome-email wording in the existing languages. Preserve the
> variables, runtime defaults and image references. Show the diffs and previews,
> and wait for my approval before saving the drafts.

The client should read exact branch revisions, call `plan_changes`, show each
diff/preview, and use `apply_changes` only for the approved identical proposal.
Review every batch result; partial saves and revision conflicts are possible.
Then open the dashboard to inspect, publish and deploy the saved content.

See the [complete MCP tools and workflow](../../MCP.md#tools-and-editing-workflow)
for layout discovery, scoped previews, payloads, concurrency and limits. An authoring preview
does not send a notification; runtime sending uses the [Delivery API](../api.md).
