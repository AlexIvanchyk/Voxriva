import asyncio
import base64
from contextlib import contextmanager
from email import policy
from email.parser import BytesParser

import pytest
from botocore.session import Session
from botocore.validate import validate_parameters
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from backend.app.features.notifications.schemas import NotificationInput
from backend.app.features.providers.adapters.ses import SESConfig, SESProvider
from backend.app.features.providers.adapters.smtp import SMTPConfig, SMTPProvider
from backend.app.features.templates.images import (
    ImageContent,
    bounded_images,
    image_schema,
)
from backend.app.features.templates.rendering import (
    DraftContent,
    _render,
    render_message,
)
from backend.app.shared.provider_contract import EmailMessage
from tests.support.images import image_value


def draft():
    return DraftContent(
        subject="Images",
        html='<img src="voxriva-image:logo"><img src="{{ banner }}" alt="{{ alt }}">',
        images={"logo": image_value()},
        variable_schema={
            "type": "object",
            "properties": {"banner": image_schema(), "alt": {"type": "string"}},
            "required": ["banner"],
        },
        runtime_defaults={"banner": image_value("blue")},
        preview_context={"banner": image_value("green"), "alt": ""},
    )


def test_raster_allowlist_actual_decode_mime_limits():
    Draft202012Validator.check_schema(image_schema())
    for fmt in ("PNG", "JPEG", "WEBP"):
        assert ImageContent.model_validate(image_value(format=fmt)).cid.endswith(
            "@images.voxriva"
        )
    for value in (
        {
            "media_type": "image/png",
            "content_base64": base64.b64encode(b'<svg onload="alert(1)"/>').decode(),
        },
        {**image_value(), "media_type": "image/jpeg"},
        {**image_value(), "content_base64": "!"},
        {**image_value(), "content_base64": "a" * 349529},
        image_value(size=(4097, 1)),
        image_value(size=(2100, 2100)),
        {**image_value(), "filename": "../../private"},
    ):
        with pytest.raises(ValidationError):
            ImageContent.model_validate(value)
    with pytest.raises(ValueError, match="Combined"):
        bounded_images([image_value()] * 20000)


def test_static_and_payload_images_are_escaped_deduplicated_and_defaults_override():
    value = draft()
    report = _render("email", value, {"alt": '<script>"'})
    assert not report.errors
    rendered = report.rendered
    assert "&lt;script&gt;&#34;" in rendered["html"]
    assert len(rendered["images"]) == 2
    assert (
        rendered["images"][0]["content_base64"] == image_value("blue")["content_base64"]
    )
    overridden = _render(
        "email", value, {"banner": image_value("green"), "alt": ""}
    ).rendered
    assert (
        overridden["images"][0]["content_base64"]
        == image_value("green")["content_base64"]
    )
    assert value.runtime_defaults["banner"] == image_value("blue")
    value.runtime_defaults = {}
    assert _render("email", value, {}).errors[0].code == "required"
    assert _render(
        "email",
        value,
        {"banner": {"media_type": "image/png", "content_base64": "AAAA"}},
    ).errors
    value.html = '<img src="voxriva-image:missing">'
    assert _render("email", value, {"banner": image_value()}).errors


def test_binary_budget_is_separate_from_text_budget_and_child_process_works():
    image = image_value(size=(300, 300))
    value = draft()
    result = asyncio.run(
        render_message("email", value, {"alt": "Fictional"}, authoring=True)
    )
    assert not result.errors
    assert (
        result.rendered["images"][1]["content_base64"]
        == image_value()["content_base64"]
    )
    NotificationInput(
        template_key="images", recipient="test@example.test", context={"banner": image}
    )
    with pytest.raises(ValidationError):
        NotificationInput(
            template_key="images",
            recipient="test@example.test",
            context={"banner": {"media_type": "image/png", "content_base64": "AAAA"}},
        )


def test_smtp_mime_and_ses_official_sdk_contract_use_identical_bytes(monkeypatch):
    result = _render("email", draft(), {"alt": "Logo"}).rendered
    message = EmailMessage(recipient="test@example.test", **result)
    captured = []

    class Client:
        def send_message(self, email, **kwargs):
            captured.append(email.as_bytes(policy=policy.SMTP))
            return {}

    @contextmanager
    def connection(self):
        yield Client()

    monkeypatch.setattr(SMTPProvider, "connection", connection)
    SMTPProvider(
        SMTPConfig(host="mailpit", tls="none", sender="sender@example.test")
    ).send(message)
    # Parsing with Python's default policy decodes encoded words, which can hide
    # invalid RFC 2047 encoding in a Content-ID. Check the actual wire headers.
    for image in result["images"]:
        assert ("Content-ID: <" + image["cid"] + ">\r\n").encode() in captured[0]
    mime = BytesParser(policy=policy.default).parsebytes(captured[0])
    html = mime.get_body(preferencelist=("html",)).get_content()
    parts = {
        part["Content-ID"].strip("<>"): part
        for part in mime.walk()
        if part.get_content_maintype() == "image"
    }
    for image in result["images"]:
        assert "cid:" + image["cid"] in html
        assert parts[image["cid"]].get_payload(decode=True) == base64.b64decode(
            image["content_base64"]
        )
        assert parts[image["cid"]].get_content_disposition() == "inline"
    args = {}

    def invoke(self, method, **kwargs):
        assert method == "send_email"
        args.update(kwargs)
        return {"MessageId": "synthetic-id"}

    monkeypatch.setattr(SESProvider, "invoke", invoke)
    SESProvider(SESConfig(sender="sender@example.test")).send(message)
    shape = (
        Session().get_service_model("sesv2").operation_model("SendEmail").input_shape
    )
    validate_parameters(args, shape)
    for source, sent in zip(
        result["images"], args["Content"]["Simple"]["Attachments"], strict=True
    ):
        assert sent["ContentId"] == source["cid"]
        assert sent["RawContent"] == parts[source["cid"]].get_payload(decode=True)
        assert sent["ContentDisposition"] == "INLINE"


def test_image_generation_utf8_and_combined_effective_budgets():
    import io
    import random

    from PIL import Image

    from backend.app.features.templates.examples import example_value

    assert (
        ImageContent.model_validate(example_value(image_schema())).media_type
        == "image/png"
    )
    with pytest.raises(ValidationError, match="100 KB"):
        DraftContent(subject="я" * 20000, html="я" * 30000, text="я" * 30000)
    stream = io.BytesIO()
    Image.frombytes("RGB", (256, 256), random.Random(42).randbytes(256 * 256 * 3)).save(
        stream, format="PNG"
    )
    image = {
        "media_type": "image/png",
        "content_base64": base64.b64encode(stream.getvalue()).decode(),
    }
    draft = DraftContent(
        subject="Combined",
        html='<img src="voxriva-image:one">',
        images={name: image for name in ("one", "two", "three")},
        variable_schema={
            "type": "object",
            "properties": {name: image_schema() for name in ("a", "b", "c")},
        },
    )
    report = _render("email", draft, {name: image for name in ("a", "b", "c")})
    assert report.errors[0].code == "image"
    assert _render(
        "email",
        DraftContent(
            subject="Boolean schema",
            html="{{ value }}",
            variable_schema={"type": "object", "properties": {"value": True}},
        ),
        {"value": {"label": "Fictional"}},
    ).rendered


def test_legacy_plain_content_base64_values_remain_ordinary_bounded_context():
    payload = NotificationInput(
        template_key="legacy",
        recipient="fictional@example.test",
        context={
            "content_base64": "ordinary application text",
            "other": {"media_type": "document", "content_base64": "ordinary text"},
        },
    )
    assert payload.context["content_base64"] == "ordinary application text"
    with pytest.raises(ValidationError, match="100 KB"):
        NotificationInput(
            template_key="legacy",
            recipient="fictional@example.test",
            context={"content_base64": "x" * 100001},
        )
