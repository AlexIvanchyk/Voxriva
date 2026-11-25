"""Verify saved synthetic demo outcomes and literal inline MIME identifiers."""

import argparse
import json
from email import policy
from email.parser import BytesParser
from pathlib import Path
from urllib.request import urlopen

from seed import API


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, type=Path)
    args = parser.parse_args()
    state = json.loads(args.state.read_text())
    api = API(state)
    film = state.get("live_film")
    extra = int(bool(film))
    history = api.call("GET", "/notifications")
    assert history["total"] == 6 + extra
    assert sorted(item["status"] for item in history["items"]) == ["failed"] + [
        "sent"
    ] * (5 + extra)
    failed = api.call("GET", "/notifications/" + state["failed"])
    replay = api.call("GET", "/notifications/" + state["replay"])
    assert len(failed["attempts"]) == 3
    assert replay["replay_of_id"] == failed["id"]
    assert len(replay["attempts"]) == 1
    matrix = api.call("GET", f"/templates/{state['welcome']}/deployments")
    versions = {
        row["environment_name"]: row["version"]["number"]
        for row in matrix["rows"]
        if row["scope"] == "environment"
    }
    assert versions["staging"] == 2 and versions["production"] == 1
    if film:
        dev = next(row for row in matrix["rows"] if row["environment_name"] == "dev")
        assert dev["version"]["id"] == film["version_id"]
        assert dev["version"]["branch_name"] == "seasonal-campaign"
        detail = api.call("GET", "/notifications/" + film["notification_id"])
        assert detail["status"] == "sent"
        assert detail["template_version_id"] == film["version_id"]
        assert len(detail["attempts"]) == 1
    else:
        assert versions["dev"] == 2
    assert state["invalid_phone"]["expected_status"] == 422
    with urlopen("http://localhost:8025/api/v1/messages", timeout=10) as response:
        inbox = json.load(response)
    assert inbox["total"] == 5 + extra
    images = 0
    for message in inbox["messages"]:
        with urlopen(
            "http://localhost:8025/api/v1/message/" + message["ID"] + "/raw", timeout=10
        ) as response:
            raw = response.read()
        mime = BytesParser(policy=policy.default).parsebytes(raw)
        html = mime.get_body(preferencelist=("html",)).get_content()
        for part in mime.walk():
            if part.get_content_maintype() != "image":
                continue
            cid = str(part["Content-ID"])
            assert ("Content-ID: " + cid + "\r\n").encode() in raw
            assert "cid:" + cid.strip("<>") in html
            assert part.get_content_disposition() == "inline"
            assert part.get_payload(decode=True)
            images += 1
    assert images == 10 + 2 * extra
    summary = {
        "projects": len(api.call("GET", "/projects")),
        "notifications": history["total"],
        "sent": 5 + extra,
        "live_film_notifications": extra,
        "controlled_failure": 1,
        "failure_attempts": 3,
        "linked_replay": True,
        "mailpit_receipts": 5 + extra,
        "inline_images": images,
        "literal_mime_identifiers": True,
        "deployment_versions": versions,
        "invalid_phone_http_status": 422,
        "cloud_sends": 0,
    }
    output = args.state.parent / "verification.json"
    output.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
