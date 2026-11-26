"""Small resumable first-email fixture, using public APIs and local Mailpit only."""

import base64
import http.cookiejar
import json
import sys
import time
import urllib.error
import urllib.request
from email import policy
from email.parser import BytesParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))
from fixtures import email_draft, layout_demo  # noqa: E402

FIXTURE = json.loads(Path(__file__).with_name("fixture.json").read_text())


class ExampleError(RuntimeError):
    pass


class API:
    def __init__(self, base, credentials=None):
        self.base = base
        self.csrf = ""
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
        )
        if credentials:
            self.csrf = self.call("POST", "/auth/login", credentials)["csrf_token"]

    def call(self, method, path, data=None, headers=None):
        request = urllib.request.Request(
            self.base + "/api/v1" + path,
            data=json.dumps(data).encode() if data is not None else None,
            method=method,
            headers={
                "Content-Type": "application/json",
                "X-Voxriva-Client": "dashboard",
                "X-CSRF-Token": self.csrf,
                **(headers or {}),
            },
        )
        try:
            with self.opener.open(request, timeout=40) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            # Validation responses may echo sensitive input. Never log their bodies.
            raise ExampleError(
                f"{method} {path} returned HTTP {error.code}. "
                "Check the owned example in the dashboard; your data was preserved."
            ) from None


def prepare_layout(api, named, pid):
    letter, day, evening = layout_demo()
    layout = named(
        "/templates",
        "northstar-brand",
        {
            "name": "Northstar brand layout",
            "key": "northstar-brand",
            "channel": "email",
            "is_layout": True,
            "project_ids": [pid],
            "draft": day,
        },
        field="key",
    )
    if not layout.get("is_layout") or [p["id"] for p in layout["projects"]] != [pid]:
        raise ExampleError("The Northstar layout key is already in use.")
    base = f"/templates/{layout['id']}"
    versions = api.call("GET", base + "/versions")
    for number, (draft, message) in enumerate(
        ((day, "Market daylight"), (evening, "Evening edition")), 1
    ):
        if any(v["number"] == number and v["message"] == message for v in versions):
            continue
        if number == 2 and layout["draft_revision"] == 1:
            layout = api.call(
                "PUT", base + "/draft", {"expected_revision": 1, "draft": draft}
            )
        if layout["draft_revision"] != number or any(
            layout["draft"].get(k) != v for k, v in draft.items()
        ):
            raise ExampleError("The layout draft changed. Your edits were preserved.")
        versions.append(
            api.call(
                "POST",
                base + "/publish",
                {
                    "branch_id": layout["branch_id"],
                    "expected_revision": number,
                    "message": message,
                },
            )
        )
    target = next(
        row
        for row in api.call("GET", base + "/deployments")["rows"]
        if row["scope"] == "project" and row["project_id"] == pid
    )
    if not target["version"] and target["generation"] == 0:
        day_version = next(v for v in versions if v["number"] == 1)
        api.call(
            "POST",
            base + "/deployments/deploy",
            {
                "scope": "project",
                "project_id": pid,
                "expected_generation": 0,
                "version_id": day_version["id"],
            },
        )
    letter["layout"] = {"template_id": layout["id"], "version_id": None}
    return letter


def prepare(api, state, save):
    """Resume incomplete setup without replacing any saved draft or active binding."""

    def named(path, name, payload=None, field="name"):
        matches = [item for item in api.call("GET", path) if item[field] == name]
        if len(matches) > 1:
            raise ExampleError(
                f"Ambiguous fixture resource at {path}; inspect the dashboard."
            )
        return (
            matches[0] if matches else api.call("POST", path, payload or {"name": name})
        )

    project = named("/projects", FIXTURE["project"])
    pid = project["id"]
    environment = named(f"/projects/{pid}/environments", FIXTURE["environment"])
    eid = environment["id"]
    state.update(project_id=pid, environment_id=eid)
    save()
    draft = (
        prepare_layout(api, named, pid)
        if state.get("layout_preview")
        else email_draft(FIXTURE["locale"])
    )
    template = named(
        "/templates",
        FIXTURE["template_key"],
        {
            "name": FIXTURE["template_name"],
            "key": FIXTURE["template_key"],
            "channel": "email",
            "project_ids": [pid],
            "draft": draft,
        },
        field="key",
    )
    base = f"/templates/{template['id']}"
    versions = api.call("GET", base + "/versions")
    if versions:
        if len(versions) != 1 or versions[0]["message"] != FIXTURE["dataset"]:
            raise ExampleError(
                "The example template was changed during setup; inspect it before continuing."
            )
        version = versions[0]
    else:
        version = api.call(
            "POST",
            base + "/publish",
            {
                "branch_id": template["branch_id"],
                "expected_revision": template["draft_revision"],
                "message": FIXTURE["dataset"],
            },
        )
    provider = named(
        "/providers",
        "Mailpit · first local email",
        {
            "name": "Mailpit · first local email",
            "provider_type": "smtp",
            "project_id": pid,
            "config": {
                "host": "mailpit",
                "port": 1025,
                "tls": "none",
                "sender": "hello@northstar.example.test",
            },
        },
    )
    if (
        provider["latest"]["config"].get("host") != "mailpit"
        or provider["latest"]["config"].get("port") != 1025
    ):
        raise ExampleError(
            "The example provider was changed; refusing to send outside local Mailpit."
        )
    target = {"scope": "environment", "project_id": pid, "environment_id": eid}
    rows = api.call("GET", "/providers/bindings")
    binding = next(
        (
            row
            for row in rows
            if row["scope"] == "environment"
            and row["environment_id"] == eid
            and row["channel"] == "email"
        ),
        None,
    )
    if not binding or not binding["direct"]:
        api.call(
            "PUT",
            "/providers/bindings",
            {
                **target,
                "channel": "email",
                "expected_generation": binding["generation"] if binding else 0,
                "revision_id": provider["latest"]["id"],
            },
        )
    elif binding["direct"]["revision_id"] != provider["latest"]["id"]:
        raise ExampleError(
            "An email binding already exists; it was preserved. Inspect the example dashboard."
        )
    rows = api.call("GET", base + "/deployments")["rows"]
    deployment = next(
        row
        for row in rows
        if row["scope"] == "environment" and row["environment_id"] == eid
    )
    if not deployment["version"]:
        api.call(
            "POST",
            base + "/deployments/deploy",
            {
                **target,
                "locale": FIXTURE["locale"],
                "expected_generation": deployment["generation"],
                "version_id": version["id"],
            },
        )
    elif deployment["version"]["id"] != version["id"]:
        raise ExampleError("An active deployment already exists; it was preserved.")
    if "delivery_key" not in state:
        # An interrupted one-time issuance can leave an unused key. No existing key is revoked.
        state["delivery_key"] = api.call(
            "POST",
            f"/projects/{pid}/environments/{eid}/keys",
            {
                "name": "First-email local integration",
                "expires_in_days": 90,
            },
        )["key"]
    state.update(
        template_id=template["id"],
        provider_revision_id=provider["latest"]["id"],
        configured=True,
    )
    save()


def send_and_wait(state, save, timeout=120):
    # Deliberately no dashboard session: acceptance and status use the environment key.
    runtime = API(state["base_url"])
    headers = {"Authorization": "Bearer " + state["delivery_key"]}
    if "notification_id" not in state:
        payload = {
            key: FIXTURE[key]
            for key in ("template_key", "recipient", "locale", "context")
        }
        checked = runtime.call("POST", "/notifications/validate", payload, headers)
        if checked["provider_revision_id"] != state["provider_revision_id"]:
            raise ExampleError(
                "The active provider changed. The launcher sends only through its original local Mailpit revision."
            )
        accepted = runtime.call(
            "POST",
            "/notifications",
            payload,
            {
                **headers,
                "Idempotency-Key": FIXTURE["dataset"],
            },
        )
        state["notification_id"] = accepted["id"]
        save()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        detail = runtime.call(
            "GET", "/notifications/" + state["notification_id"], headers=headers
        )
        if detail["status"] == "sent":
            return detail
        if detail["status"] in {"failed", "unknown", "expired", "cancelled"}:
            raise ExampleError(
                f"Sample notification is {detail['status']}; inspect Notifications before replaying."
            )
        time.sleep(1)
    raise ExampleError(
        "The sample is still pending. Rerun to continue waiting; no duplicate will be sent."
    )


def verify_receipt(state, detail, timeout=30):
    """Match provider Message-ID, then verify actual MIME bytes and CID references."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = state["mailpit_url"]
    message_id = detail["attempts"][-1]["provider_message_id"]
    draft = email_draft()
    expected = {
        base64.b64decode(draft["images"]["logo"]["content_base64"]),
        base64.b64decode(draft["runtime_defaults"]["banner"]["content_base64"]),
    }
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with opener.open(base + "/api/v1/messages?limit=100", timeout=10) as response:
            inbox = json.load(response)
        messages = inbox["messages"]
        if state.get("mailpit_id"):
            # Keep repeat verification working after more than 100 later messages.
            messages = [{"ID": state["mailpit_id"], "MessageID": message_id}]
        for item in messages:
            # Mailpit exposes MessageID without angle brackets.
            if item.get("MessageID", "").strip("<>") != message_id.strip("<>"):
                continue
            with opener.open(
                base + "/api/v1/message/" + item["ID"] + "/raw", timeout=10
            ) as response:
                raw = response.read()
            mime = BytesParser(policy=policy.default).parsebytes(raw)
            if str(mime["Message-ID"]).strip("<>") != message_id.strip("<>"):
                raise ExampleError(
                    "The saved Mailpit receipt does not match this notification."
                )
            html = mime.get_body(preferencelist=("html",)).get_content()
            images = [
                part for part in mime.walk() if part.get_content_maintype() == "image"
            ]
            if (
                len(images) != 2
                or {part.get_payload(decode=True) for part in images} != expected
            ):
                raise ExampleError(
                    "Mailpit received the message, but inline image bytes do not match the fixture."
                )
            for part in images:
                cid = str(part["Content-ID"])
                if (
                    ("cid:" + cid.strip("<>")) not in html
                    or ("Content-ID: " + cid + "\r\n").encode() not in raw
                    or part.get_content_disposition() != "inline"
                ):
                    raise ExampleError(
                        "Mailpit received the message, but an inline MIME reference is invalid."
                    )
            if "Sofia" not in html or "voxriva-image:" in html or "{{" in html:
                raise ExampleError("The received template did not render completely.")
            return {
                "notification_id": detail["id"],
                "status": detail["status"],
                "attempts": len(detail["attempts"]),
                "mailpit_id": item["ID"],
                "inline_images": len(images),
                "image_bytes_match": True,
                "mailpit_receipts": inbox["total"],
            }
        time.sleep(1)
    raise ExampleError(
        "SMTP accepted the sample, but its Mailpit receipt was not found. Check Mailpit; no duplicate was sent."
    )
