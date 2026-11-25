"""Synthetic acceptance requests and deployed notification scenario builders."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.support.administration import ROOT, create, sign_in
from tests.support.lifecycle import mutate, publish, setup, target
from tests.support.providers import enable_crypto, provider


def prepare(client, app):
    enable_crypto(app)
    sign_in(client)
    project, dev, prod, template = setup(client)
    version = publish(client, template)
    assert (
        mutate(
            client, template, **target(project, dev), version_id=version["id"]
        ).status_code
        == 200
    )
    smtp = provider(client, project["id"])
    assert (
        client.put(
            f"{ROOT}/providers/bindings",
            json={
                "scope": "environment",
                "project_id": project["id"],
                "environment_id": dev["id"],
                "channel": "email",
                "revision_id": smtp["latest"]["id"],
                "expected_generation": 0,
            },
        ).status_code
        == 200
    )
    key = create(
        client,
        f"/projects/{project['id']}/environments/{dev['id']}/keys",
        name="Delivery test",
    )
    return (
        project,
        dev,
        prod,
        template,
        version,
        smtp,
        {
            "Authorization": f"Bearer {key['key']}",
            "Idempotency-Key": "synthetic-request-1",
        },
    )


def body(template, **changes):
    return {
        "template_key": template["key"],
        "recipient": "recipient.private@example.test",
        "context": {"name": "RuntimeOnly"},
        **changes,
    }


def count(engine, model):
    with Session(engine) as db:
        return db.scalar(select(func.count()).select_from(model))
