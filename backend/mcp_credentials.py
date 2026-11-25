"""Manage your MCP credentials using dashboard login + CSRF (password is prompted)."""

import argparse
import getpass
import json
import os
from urllib.parse import urlsplit

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Dashboard base URL")
    parser.add_argument("--email", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    issue = commands.add_parser("issue")
    issue.add_argument("--name", required=True)
    issue.add_argument("--project", action="append", required=True)
    issue.add_argument("--write", action="store_true")
    issue.add_argument("--days", type=int, default=30)
    issue.add_argument(
        "--output",
        required=True,
        help="New token file (0600); existing files are never overwritten",
    )
    commands.add_parser("list")
    revoke = commands.add_parser("revoke")
    revoke.add_argument("id")
    args = parser.parse_args()
    url = urlsplit(args.url)
    if url.scheme != "https" and not (
        url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost", "::1"}
    ):
        parser.error("Use HTTPS, or loopback HTTP for local development")
    if url.username or url.query or url.fragment:
        parser.error("Do not put credentials or query strings in the URL")
    password = getpass.getpass("Dashboard password: ")
    try:
        with httpx.Client(base_url=args.url.rstrip("/"), timeout=15) as client:
            response = client.post(
                "/api/v1/auth/login",
                headers={"X-Voxriva-Client": "dashboard"},
                json={"email": args.email, "password": password},
            )
            response.raise_for_status()
            login = response.json()
            if login.get("mfa_required"):
                if login.get("enrollment_required"):
                    parser.exit(
                        1,
                        "Complete MFA enrollment in the dashboard, then retry credential management.\n",
                    )
                code = getpass.getpass("Authenticator or recovery code: ")
                response = client.post(
                    "/api/v1/auth/mfa/verify",
                    headers={"X-Voxriva-Client": "dashboard"},
                    json={"challenge": login["challenge"], "code": code},
                )
                response.raise_for_status()
                login = response.json()
            client.headers["X-CSRF-Token"] = login["csrf_token"]
            try:
                root = "/api/v1/management-credentials"
                if args.command == "issue":
                    # Reserve a private output before creating a server credential.
                    descriptor = os.open(
                        args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                    )
                    try:
                        response = client.post(
                            root,
                            json={
                                "name": args.name,
                                "project_ids": args.project,
                                "scopes": ["templates:read", "templates:write"]
                                if args.write
                                else ["templates:read"],
                                "expires_in_days": args.days,
                            },
                        )
                        response.raise_for_status()
                        result = response.json()
                        with os.fdopen(descriptor, "w") as stream:
                            descriptor = -1
                            stream.write(result["token"] + "\n")
                        print(json.dumps(result["credential"], indent=2))
                    finally:
                        if descriptor != -1:
                            os.close(descriptor)
                elif args.command == "list":
                    response = client.get(root)
                    response.raise_for_status()
                    print(json.dumps(response.json(), indent=2))
                else:
                    response = client.delete(f"{root}/{args.id}")
                    response.raise_for_status()
                    print("Credential revoked")
            finally:
                client.post("/api/v1/auth/logout")
    except httpx.HTTPStatusError as error:
        # Deliberately omit request bodies, passwords, bearer values and response echo.
        parser.exit(
            1, f"Management request rejected (HTTP {error.response.status_code})\n"
        )
    except (OSError, httpx.RequestError):
        parser.exit(
            1, "Credential operation failed; check endpoint/output path and retry.\n"
        )


if __name__ == "__main__":
    main()
