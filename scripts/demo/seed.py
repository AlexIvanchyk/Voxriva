"""Seed an EMPTY, already bootstrapped local demo via supported HTTP endpoints.

Run with --state pointing to a private JSON containing email/password/base_url.
This script never resets Docker, never contacts cloud providers and never prints keys.
"""

import argparse
import base64
import copy
import hashlib
import hmac
import http.cookiejar
import json
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from fixtures import email_draft, image


class API:
    def __init__(self, state):
        self.base = state["base_url"].rstrip("/")
        parsed = urllib.parse.urlsplit(self.base)
        if parsed.hostname not in {"localhost", "127.0.0.1"}:
            raise SystemExit("Demo seed requires a loopback service URL.")
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        self.csrf = ""
        view = self.call(
            "POST",
            "/auth/login",
            {"email": state["email"], "password": state["password"]},
        )
        self.csrf = view["csrf_token"]

    def call(self, method, path, data=None, headers=None, expected=None):
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
            body = error.read().decode()
            if expected == error.code:
                return {"expected_status": error.code, "problem": json.loads(body)}
            raise RuntimeError(f"{method} {path}: {error.code}: {body[:800]}") from None

    def post(self, path, data):
        return self.call("POST", path, data)


def totp(secret):
    value = hmac.new(
        base64.b32decode(secret),
        struct.pack(">Q", int(time.time()) // 30),
        hashlib.sha1,
    ).digest()
    offset = value[-1] & 15
    return f"{(struct.unpack('>I', value[offset : offset + 4])[0] & 0x7FFFFFFF) % 1000000:06d}"


def wait_status(api, identifier, status, timeout=80):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        detail = api.call("GET", f"/notifications/{identifier}")
        if detail["status"] == status:
            return detail
        time.sleep(1)
    raise RuntimeError(f"Notification did not reach {status}")


def seed(api, state, save):
    if api.call("GET", "/projects"):
        raise SystemExit(
            "Refusing seed: workspace must be empty. This script does not reset data."
        )
    shop = api.post("/projects", {"name": "Northstar Market"})
    studio = api.post("/projects", {"name": "Orbit Studio"})
    state["project"] = shop
    state["environments"] = {
        name: api.post(f"/projects/{shop['id']}/environments", {"name": name})
        for name in ["dev", "staging", "production"]
    }
    api.post(f"/projects/{studio['id']}/environments", {"name": "dev"})
    state["member_password"] = state["password"]
    for email, name, role in [
        ("maya@example.test", "Maya Chen", "template_editor"),
        ("leon@example.test", "Leon Brooks", "operator"),
        ("nora@example.test", "Nora Silva", "viewer"),
    ]:
        api.post(
            f"/projects/{shop['id']}/members",
            {
                "email": email,
                "display_name": name,
                "role": role,
                "password": state["member_password"],
            },
        )
    draft = email_draft()
    template = api.post(
        "/templates",
        {
            "name": "Welcome to Northstar",
            "key": "northstar-welcome",
            "channel": "email",
            "project_ids": [shop["id"]],
            "draft": draft,
        },
    )
    state["welcome"] = template["id"]
    base = f"/templates/{template['id']}"
    version1 = api.post(
        base + "/publish",
        {
            "branch_id": template["branch_id"],
            "expected_revision": 1,
            "message": "Welcome email with brand assets and validated payload",
        },
    )
    draft2 = copy.deepcopy(draft)
    draft2["subject"] = "Your Northstar story starts here, {{ first_name }}"
    api.call("PUT", base + "/draft", {"draft": draft2, "expected_revision": 1})
    version2 = api.post(
        base + "/publish",
        {
            "branch_id": template["branch_id"],
            "expected_revision": 2,
            "message": "Refine welcome subject for the next release",
        },
    )
    api.post(
        base + "/branches",
        {"name": "seasonal-campaign", "source_version_id": version2["id"]},
    )
    ukrainian = api.post(
        base + "/languages",
        {
            "locale": "uk",
            "source_branch_id": template["branch_id"],
            "expected_revision": 2,
        },
    )
    api.call(
        "PUT",
        base + "/draft",
        {
            "branch_id": ukrainian["id"],
            "expected_revision": 1,
            "draft": email_draft("uk"),
        },
    )
    uk_version = api.post(
        base + "/publish",
        {
            "branch_id": ukrainian["id"],
            "expected_revision": 2,
            "message": "Ukrainian welcome ready for local preview and send",
        },
    )
    provider = api.post(
        "/providers",
        {
            "name": "Mailpit · local SMTP",
            "provider_type": "smtp",
            "project_id": shop["id"],
            "config": {
                "host": "mailpit",
                "port": 1025,
                "tls": "none",
                "sender": "hello@northstar.example.test",
            },
        },
    )
    api.call(
        "PUT",
        "/providers/bindings",
        {
            "scope": "project",
            "project_id": shop["id"],
            "channel": "email",
            "expected_generation": 0,
            "revision_id": provider["latest"]["id"],
        },
    )
    state["delivery_keys"] = {}
    for name, env in state["environments"].items():
        target = {
            "scope": "environment",
            "project_id": shop["id"],
            "environment_id": env["id"],
            "locale": "en",
        }
        chosen = version1 if name == "production" else version2
        api.post(
            base + "/deployments/deploy",
            {**target, "expected_generation": 0, "version_id": chosen["id"]},
        )
        api.post(
            base + "/deployments/deploy",
            {
                **target,
                "locale": "uk",
                "expected_generation": 0,
                "version_id": uk_version["id"],
            },
        )
        if name == "production":
            api.post(
                base + "/deployments/deploy",
                {**target, "expected_generation": 1, "version_id": version2["id"]},
            )
            api.post(
                base + "/deployments/rollback",
                {**target, "expected_generation": 2, "version_id": version1["id"]},
            )
        state["delivery_keys"][name] = api.post(
            f"/projects/{shop['id']}/environments/{env['id']}/keys",
            {"name": f"Northstar {name} service", "expires_in_days": 90},
        )
    state["management"] = api.post(
        "/management-credentials",
        {
            "name": "Local assistant · template authoring",
            "project_ids": [shop["id"]],
            "scopes": ["templates:read", "templates:write"],
            "expires_in_days": 30,
        },
    )
    push = api.post(
        "/templates",
        {
            "name": "Your order is on its way",
            "key": "northstar-order-shipped",
            "channel": "push",
            "project_ids": [shop["id"]],
            "draft": {
                "title": "Good things are on their way 📦",
                "body": "{{ first_name }}, order {{ order_number }} has shipped. Track your delivery in the app.",
                "data": {"route": "/orders/{{ order_number }}"},
                "variable_schema": {
                    "type": "object",
                    "properties": {
                        "first_name": {"type": "string"},
                        "order_number": {"type": "string"},
                    },
                    "required": ["first_name", "order_number"],
                    "additionalProperties": False,
                },
                "preview_context": {"first_name": "Sofia", "order_number": "NS-1048"},
            },
        },
    )
    state["push"] = push["id"]
    rendered = api.post(f"/templates/{push['id']}/preview", {})
    assert rendered["rendered"] and not rendered["errors"]
    state["notifications"] = []
    save()
    for index, (name, locale, env_name, override) in enumerate(
        [
            ("Sofia", "en", "production", False),
            ("Jordan", "en", "dev", True),
            ("Софія", "uk", "staging", False),
            ("Maya", "en", "dev", False),
        ]
    ):
        context = {
            "first_name": name,
            "account_url": "https://northstar.example.test/account",
        }
        if override:
            context["banner"] = image("northstar-seasonal.png")
        key = state["delivery_keys"][env_name]["key"]
        request = {
            "template_key": "northstar-welcome",
            "recipient": f"customer{index + 1}@example.test",
            "locale": locale,
            "context": context,
        }
        accepted = api.call(
            "POST",
            "/notifications",
            request,
            {
                "Authorization": "Bearer " + key,
                "Idempotency-Key": f"demo-welcome-{index + 1}",
            },
        )
        detail = wait_status(api, accepted["id"], "sent")
        assert len(detail["attempts"]) == 1
        state["notifications"].append(accepted["id"])
        if index == 0:
            duplicate = api.call(
                "POST",
                "/notifications",
                request,
                {"Authorization": "Bearer " + key, "Idempotency-Key": "demo-welcome-1"},
            )
            assert duplicate["id"] == accepted["id"] and duplicate["replayed"]
    key = state["delivery_keys"]["dev"]["key"]
    state["invalid_phone"] = api.call(
        "POST",
        "/notifications/validate",
        {
            "template_key": "northstar-welcome",
            "recipient": "invalid@example.test",
            "context": {
                "first_name": "Alex",
                "account_url": "https://northstar.example.test/account",
                "phone": "not-a-phone",
            },
        },
        {"Authorization": "Bearer " + key},
        expected=422,
    )
    assert state["invalid_phone"].get("expected_status") == 422
    # A controlled closed LOCAL port exercises real retries without external delivery.
    env = state["environments"]["dev"]
    target = {
        "scope": "environment",
        "project_id": shop["id"],
        "environment_id": env["id"],
    }
    recovery = api.post(
        "/providers",
        {
            "name": "Recovery drill · local SMTP",
            "provider_type": "smtp",
            "project_id": shop["id"],
            "config": {
                "host": "mailpit",
                "port": 1,
                "tls": "none",
                "sender": "hello@northstar.example.test",
                "timeout": 1,
            },
        },
    )
    api.call(
        "PUT",
        "/providers/bindings",
        {
            **target,
            "channel": "email",
            "expected_generation": 0,
            "revision_id": recovery["latest"]["id"],
        },
    )
    accepted = api.call(
        "POST",
        "/notifications",
        {
            "template_key": "northstar-welcome",
            "recipient": "recovery@example.test",
            "context": {
                "first_name": "Taylor",
                "account_url": "https://northstar.example.test/account",
            },
        },
        {"Authorization": "Bearer " + key, "Idempotency-Key": "demo-controlled-retry"},
    )
    state["failed"] = accepted["id"]
    save()
    failed = wait_status(api, accepted["id"], "failed")
    assert len(failed["attempts"]) == 3
    fixed = api.post(
        f"/providers/{recovery['id']}/revisions",
        {"expected_revision": 1, "config": {"port": 1025}},
    )
    api.call(
        "PUT",
        "/providers/bindings",
        {
            **target,
            "channel": "email",
            "expected_generation": 1,
            "revision_id": fixed["latest"]["id"],
        },
    )
    replay = api.post(
        f"/notifications/{failed['id']}/replay",
        {
            "replay_key": "demo-recovery-replay",
            "expected_updated_at": failed["updated_at"],
            "use_current_deployments": True,
        },
    )
    wait_status(api, replay["id"], "sent")
    state["replay"] = replay["id"]
    # Enroll only a fictional editor; leave the installation administrator usable.
    member = API(
        {**state, "email": "maya@example.test", "password": state["member_password"]}
    )
    setup = member.post("/auth/mfa/setup", {"password": state["member_password"]})
    codes = member.post("/auth/mfa/confirm", {"code": totp(setup["secret"])})
    assert member.call("GET", "/auth/mfa")["enabled"]
    state["mfa_member"] = {
        "email": "maya@example.test",
        "secret": setup["secret"],
        "recovery_codes": codes["recovery_codes"],
    }
    save()
    print(
        "Seeded fictional projects, environments, roles, email/push, EN/UK releases, rollback, scoped keys, five local deliveries and a real failed/replayed recovery drill."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, type=Path)
    options = parser.parse_args()
    state = json.loads(options.state.read_text())

    def save():
        options.state.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")
        options.state.chmod(0o600)

    seed(API(state), state, save)


if __name__ == "__main__":
    main()
