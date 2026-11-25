"""Synthetic template drafts and lifecycle HTTP scenario builders."""

from backend.app.features.templates.rendering import DraftContent
from tests.support.administration import ROOT, create


def draft(subject="Hello {{ name }}"):
    return DraftContent(
        subject=subject,
        html="<h1>{{ name }}</h1>",
        text="Hi {{ name }}",
        variable_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
        preview_context={"name": "Synthetic Example"},
    )


def setup(client):
    project = create(client, "/projects", name="Commerce")
    base = f"/projects/{project['id']}"
    dev = create(client, f"{base}/environments", name="dev")
    prod = create(client, f"{base}/environments", name="prod")
    template = create(
        client,
        "/templates",
        name="Welcome",
        key="welcome",
        channel="email",
        project_ids=[project["id"]],
        draft=draft().model_dump(),
    )
    return project, dev, prod, template


def publish(client, template, branch_id=None, revision=1):
    response = client.post(
        f"{ROOT}/templates/{template['id']}/publish",
        json={
            "branch_id": branch_id or template["branch_id"],
            "expected_revision": revision,
            "message": "Synthetic release",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def mutate(client, template, action="deploy", **payload):
    return client.post(
        f"{ROOT}/templates/{template['id']}/deployments/{action}", json=payload
    )


def target(project, env=None, generation=0, locale="en"):
    return {
        "scope": "environment" if env else "project",
        "project_id": project["id"],
        "environment_id": env["id"] if env else None,
        "locale": locale,
        "expected_generation": generation,
    }
