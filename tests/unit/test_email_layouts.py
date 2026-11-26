import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from backend.app.features.deployments.layout_contracts import check_contracts
from backend.app.features.deployments.schemas import ScopeInput
from backend.app.features.templates import layouts
from backend.app.features.templates.composition import (
    BODY_SLOT,
    compose,
    layout_parts,
    validate_kind,
)
from backend.app.features.templates.layouts import (
    pinned_layout,
    render_version,
    resolve_layout,
)
from backend.app.features.templates.rendering import DraftContent, LayoutReference
from backend.app.infrastructure.errors import ApplicationError
from scripts.demo.fixtures import layout_demo


def draft(**fields):
    return DraftContent.model_validate(fields)


def version(content, **fields):
    return SimpleNamespace(id=uuid4(), content=content.model_dump(), **fields)


def test_composition_escapes_each_source_once_and_never_evaluates_payload_as_source():
    letter = draft(
        subject="Order {{ name }}",
        html="<b>{{ name }}</b>",
        text="Plain {{ name }}",
        variable_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    )
    layout = draft(
        html="<header>{{ brand }}</header>" + BODY_SLOT + "<footer>Shop</footer>",
        runtime_defaults={"brand": "Default"},
        variable_schema={
            "type": "object",
            "properties": {"brand": {"type": "string"}},
            "required": ["brand"],
        },
    )
    context = {"name": "<Ann> {{ brand }}", "brand": "A&B"}
    rendered = asyncio.run(
        render_version("email", letter, version(layout), context)
    ).rendered
    assert rendered == {
        "html": "<header>A&amp;B</header><b>&lt;Ann&gt; {{ brand }}</b><footer>Shop</footer>",
        "subject": "Order <Ann> {{ brand }}",
        "text": "Plain <Ann> {{ brand }}",
    }
    layout.html = ""
    layout.text = "Header\n" + BODY_SLOT + "\nFooter"
    rendered = asyncio.run(
        render_version("email", letter, version(layout), context)
    ).rendered
    assert rendered["text"] == "Header\nPlain <Ann> {{ brand }}\nFooter"
    assert rendered["html"] == "<b>&lt;Ann&gt; {{ brand }}</b>"


@pytest.mark.parametrize(
    "layout",
    [
        {"html": "missing"},
        {"text": BODY_SLOT * 2},
        {"html": f'<a title="{BODY_SLOT}">Hi</a>'},
        {"html": BODY_SLOT, "text": "missing"},
        {},
    ],
)
def test_each_defined_layout_format_has_exactly_one_slot(layout):
    with pytest.raises(ApplicationError):
        layout_parts(draft(**layout))


@pytest.mark.parametrize(
    "channel,is_layout", [("email", True), ("push", False), ("push", True)]
)
def test_only_letters_can_reference_layouts(channel, is_layout):
    with pytest.raises(ApplicationError):
        validate_kind(channel, is_layout, draft(layout={"template_id": str(uuid4())}))


def test_composed_contract_rejects_root_constraints_and_overlapping_names():
    letter = draft(runtime_defaults={"brand": "local"})
    with pytest.raises(ApplicationError, match="brand"):
        compose(
            letter,
            draft(
                variable_schema={
                    "type": "object",
                    "properties": {"brand": {"type": "string"}},
                }
            ),
        )
    with pytest.raises(ApplicationError, match="root constraints"):
        compose(letter, draft(variable_schema={"type": "object", "oneOf": [{}]}))


def test_northstar_previews_both_editions_with_real_images_and_only_runtime_inputs_at_delivery():
    letter, day, evening = (draft(**item) for item in layout_demo())
    results = []
    for layout in (day, evening):
        saved = version(layout)
        preview = asyncio.run(
            render_version("email", letter, saved, letter.preview_context)
        )
        assert not preview.errors
        rendered = preview.rendered
        assert "Alex" in rendered["subject"] and "Alex" in rendered["html"]
        assert all(
            "cid:" + image["cid"] in rendered["html"] for image in rendered["images"]
        )
        assert len(rendered["images"]) == 2 and BODY_SLOT not in str(rendered)
        results.append(rendered)
        assert (
            asyncio.run(render_version("email", letter, saved, {})).errors[0].code
            == "required"
        )
        invalid = {**letter.preview_context, "phone": "invalid"}
        assert asyncio.run(render_version("email", letter, saved, invalid)).errors[
            0
        ].path == ["context", "phone"]
    assert (
        "EVENING EDITION" not in results[0]["html"]
        and "EVENING EDITION" in results[1]["html"]
    )
    assert results[0]["images"] != results[1]["images"]


def test_active_layout_tracks_environment_but_pin_and_queue_keep_immutable_versions(
    monkeypatch,
):
    layout = SimpleNamespace(id=uuid4(), fallback_locale="en")
    dev = ScopeInput(
        scope="environment", project_id=uuid4(), environment_id=uuid4(), locale="uk"
    )
    ref = LayoutReference(template_id=layout.id)
    first, second = [
        version(draft(), template_id=layout.id, locale="en") for _ in range(2)
    ]
    active = AsyncMock(
        side_effect=[
            (first, "project", True),
            (second, "environment", True),
            (first, "project", True),
        ]
    )
    monkeypatch.setattr(layouts, "effective", active)
    db = AsyncMock()
    db.scalar.return_value = layout
    db.get.return_value = True
    accepted = asyncio.run(resolve_layout(db, ref, dev))
    assert asyncio.run(resolve_layout(db, ref, dev)).id == second.id
    assert asyncio.run(resolve_layout(db, ref, dev)).id == first.id
    active.assert_awaited_with(db, layout, dev)
    ref.version_id = first.id
    db.get.side_effect = [True, first, first, second]
    assert asyncio.run(resolve_layout(db, ref, dev)) == first
    assert asyncio.run(pinned_layout(db, ref, accepted.id)) == first
    with pytest.raises(ApplicationError):
        asyncio.run(pinned_layout(db, ref, second.id))
    assert active.await_count == 3


def test_layout_resolution_requires_project_binding_and_matching_published_language():
    layout = SimpleNamespace(id=uuid4(), fallback_locale="en")
    scope = ScopeInput(scope="project", project_id=uuid4(), locale="uk")
    ref = LayoutReference(template_id=layout.id, version_id=uuid4())
    db = AsyncMock()
    db.scalar.return_value = layout
    db.get.side_effect = [
        None,
        True,
        version(draft(), template_id=layout.id, locale="de"),
        True,
        version(draft(), template_id=uuid4(), locale="uk"),
    ]
    for status in (404, 422, 422):
        with pytest.raises(ApplicationError) as error:
            asyncio.run(resolve_layout(db, ref, scope))
        assert error.value.status_code == status


def test_dependent_contract_protects_active_letters_from_default_removal_and_tightened_types():
    key = (uuid4(), uuid4(), uuid4(), "en")
    schema = {
        "type": "object",
        "properties": {"n": {"type": "number"}},
        "required": ["n"],
    }
    letter = draft()
    previous = compose(letter, draft(variable_schema=schema, runtime_defaults={"n": 0}))
    snapshot = {key: (uuid4(), previous)}
    for layout in (
        draft(variable_schema=schema),
        draft(
            variable_schema={**schema, "properties": {"n": {"type": "integer"}}},
            runtime_defaults={"n": 0},
        ),
    ):
        with pytest.raises(ApplicationError, match="depends on the previous contract"):
            check_contracts(
                snapshot, {key: (snapshot[key][0], compose(letter, layout))}
            )
    check_contracts(snapshot, snapshot)


def test_enqueue_persists_the_pair_and_idempotent_retries_skip_resolution(monkeypatch):
    from unittest.mock import Mock

    from backend.app.features.notifications import service
    from backend.app.features.notifications.models import (
        Notification,
        NotificationOutbox,
    )
    from backend.app.features.notifications.schemas import NotificationInput, Prepared
    from backend.app.features.projects.schemas import DeliveryScope

    scope = DeliveryScope(key_id=uuid4(), project_id=uuid4(), environment_id=uuid4())
    prepared = Prepared(
        SimpleNamespace(id=uuid4(), channel="email"),
        SimpleNamespace(id=uuid4()),
        SimpleNamespace(id=uuid4()),
        {},
        uuid4(),
    )
    resolve = AsyncMock(return_value=prepared)
    monkeypatch.setattr(service, "prepare", resolve)
    monkeypatch.setattr(service, "fingerprints", lambda *_: ["hash"])
    monkeypatch.setattr(service, "encrypt", lambda *_: "ciphertext")
    db = AsyncMock()
    db.add = Mock()
    db.scalar.return_value = None
    payload = NotificationInput(template_key="welcome", recipient="user@example.test")
    runtime = SimpleNamespace(
        settings=SimpleNamespace(delivery_payload_ttl_seconds=600)
    )
    first = asyncio.run(service.accept(payload, runtime, db, scope, "key"))
    item, outbox = [call.args[0] for call in db.add.call_args_list]
    assert isinstance(item, Notification) and isinstance(outbox, NotificationOutbox)
    assert (item.template_version_id, item.layout_version_id) == (
        prepared.version.id,
        prepared.layout_version_id,
    )
    assert outbox.notification_id == first.id == item.id
    db.scalar.return_value = item
    retry = asyncio.run(service.accept(payload, runtime, db, scope, "key"))
    assert retry.id == first.id and retry.replayed
    resolve.assert_awaited_once()


def test_retrying_worker_renders_the_accepted_pair_without_a_deployment_lookup(
    monkeypatch,
):
    from unittest.mock import Mock

    from backend.app.features.notifications import delivery
    from backend.app.features.notifications.models import Notification
    from backend.app.features.providers.models import (
        ProviderConfiguration,
        ProviderRevision,
    )
    from backend.app.features.templates.models import TemplateVersion
    from backend.app.infrastructure.settings import Settings
    from backend.app.shared.provider_contract import ProviderConfig, ProviderResult

    layout_id = uuid4()
    saved_layout = version(
        draft(html="<main>Original " + BODY_SLOT + "</main>"), template_id=layout_id
    )
    saved_letter = version(
        draft(
            subject="Hello",
            html="Dear {{ name }}",
            layout={"template_id": layout_id},
            variable_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        )
    )
    provider = SimpleNamespace(id=uuid4(), project_id=None, provider_type="test")
    revision = SimpleNamespace(
        id=uuid4(),
        configuration_id=provider.id,
        public_config={},
        encrypted_secrets="settings",
    )
    item = Notification(
        id=uuid4(),
        status="retrying",
        project_id=uuid4(),
        channel="email",
        attempt_count=1,
        template_version_id=saved_letter.id,
        layout_version_id=saved_layout.id,
        provider_revision_id=revision.id,
        encrypted_payload="payload",
    )
    records = {
        (Notification, item.id): item,
        (ProviderRevision, revision.id): revision,
        (TemplateVersion, saved_letter.id): saved_letter,
        (TemplateVersion, saved_layout.id): saved_layout,
        (ProviderConfiguration, provider.id): provider,
    }
    db = AsyncMock()
    db.add = Mock()
    db.get.side_effect = lambda model, key: records[model, key]
    db.scalar.side_effect = [provider, item, 0, item]
    db.execute.return_value = SimpleNamespace(rowcount=1)
    manager = AsyncMock()
    manager.__aenter__.return_value = db
    provider_class = Mock(key="test", channel="email", config_model=ProviderConfig)
    provider_class.return_value.send.return_value = ProviderResult(
        status="accepted", message="synthetic"
    )
    monkeypatch.setattr(delivery, "renew", AsyncMock())
    monkeypatch.setattr(
        delivery,
        "decrypt",
        lambda _, key: (
            {}
            if key == "settings"
            else {"recipient": "user@example.test", "context": {"name": "Sofia"}}
        ),
    )
    asyncio.run(
        delivery.consume(lambda: manager, Settings(), {"test": provider_class}, item.id)
    )
    assert item.status == "sent" and item.attempt_count == 2
    message = provider_class.return_value.send.call_args.args[0]
    assert (
        message.subject == "Hello"
        and message.html == "<main>Original Dear Sofia</main>"
    )
