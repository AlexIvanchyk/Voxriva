"""Synthetic push credentials and deployment scenario builders."""

from tests.support.administration import ROOT, create, sign_in
from tests.support.lifecycle import mutate, publish, target
from tests.support.providers import enable_crypto

DEVICE = "synthetic-device-token-never-visible"


def push_setup(client, app):
    enable_crypto(app)
    sign_in(client)
    project = create(client, "/projects", name="Push project")
    env = create(client, f"/projects/{project['id']}/environments", name="dev")
    template = create(
        client,
        "/templates",
        name="Push welcome",
        key="push-welcome",
        channel="push",
        project_ids=[project["id"]],
        draft={
            "title": "Hello {{ name }}",
            "body": "Welcome {{ name }}",
            "data": {"screen": "home"},
            "variable_schema": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            "preview_context": {"name": "PreviewOnly"},
        },
    )
    version = publish(client, template)
    assert (
        mutate(
            client, template, **target(project, env), version_id=version["id"]
        ).status_code
        == 200
    )
    provider = create(
        client,
        "/providers",
        name="Firebase",
        provider_type="firebase_fcm",
        project_id=project["id"],
        config={"project_id": "firebase-demo", "auth_mode": "default"},
    )
    assert (
        client.put(
            f"{ROOT}/providers/bindings",
            json={
                "scope": "project",
                "project_id": project["id"],
                "channel": "push",
                "revision_id": provider["latest"]["id"],
                "expected_generation": 0,
            },
        ).status_code
        == 200
    )
    key = create(
        client,
        f"/projects/{project['id']}/environments/{env['id']}/keys",
        name="Push key",
    )
    return template, {
        "Authorization": f"Bearer {key['key']}",
        "Idempotency-Key": "push-request",
    }
