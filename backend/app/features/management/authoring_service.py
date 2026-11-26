"""Transport-independent MCP authoring workflows; writes use domain services."""

import difflib
import hashlib
import hmac
import json
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.features.management.schemas import ChangeSet
from backend.app.features.management.service import (
    Author,
    authenticate,
    template_access,
)
from backend.app.features.templates import service as templates
from backend.app.features.templates import versions_service as versions
from backend.app.features.templates.schemas import (
    DraftUpdate,
    PreviewInput,
    TemplateInput,
)
from backend.app.features.templates.versions_schemas import BranchInput, LanguageInput
from backend.app.infrastructure.context import ApplicationContext
from backend.app.infrastructure.errors import ApplicationError


def encoded(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [encoded(item) for item in value]
    return value


def failure(error: ApplicationError | ValidationError) -> dict[str, Any]:
    if isinstance(error, ValidationError):
        # Pydantic's default errors include the supplied input; never reflect it.
        return {
            "ok": False,
            "status": 422,
            "error": "Invalid tool input",
            "issues": [
                {"path": list(issue["loc"]), "type": issue["type"]}
                for issue in error.errors()
            ],
        }
    return {"ok": False, "status": error.status_code, "error": error.detail}


def plan_hash(changes: ChangeSet) -> str:
    canonical = json.dumps(
        changes.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class Authoring:
    def __init__(
        self, factory: async_sessionmaker[AsyncSession], runtime: ApplicationContext
    ):
        self.factory = factory
        self.runtime = runtime

    async def call(
        self, token: str, operation: str, **arguments: Any
    ) -> dict[str, Any]:
        try:
            if operation in {"plan_changes", "apply_changes"}:
                return await self.batch(
                    token, apply=operation == "apply_changes", **arguments
                )
            async with self.factory() as db:
                author = await authenticate(token, db, self.runtime.settings)
                return {
                    "ok": True,
                    "result": encoded(
                        await self.execute(db, author, operation, arguments)
                    ),
                }
        except (ApplicationError, ValidationError) as error:
            return failure(error)
        except SQLAlchemyError:
            return {
                "ok": False,
                "status": 503,
                "error": "Database unavailable; re-read before retrying a write",
            }

    async def execute(
        self, db: AsyncSession, author: Author, operation: str, args: dict[str, Any]
    ) -> Any:
        principal = author.principal
        if operation == "list_templates":
            requested = args.get("project_id")
            if requested is not None and requested not in author.project_ids:
                raise ApplicationError(403, "Project outside credential scope")
            results = await templates.list_templates(db, principal, requested)
            visible = []
            query = args.get("query", "").casefold()
            is_layout = args.get("is_layout")
            for item in results:
                if is_layout is not None and item.is_layout != is_layout:
                    continue
                try:
                    await template_access(db, author, item.id)
                except ApplicationError as error:
                    if error.status_code == 404:
                        continue
                    raise
                if query not in f"{item.name} {item.key}".casefold():
                    continue
                data = item.model_dump(mode="json", exclude={"draft"})
                data["projects"] = [
                    p for p in data["projects"] if UUID(p["id"]) in author.project_ids
                ]
                data["editable"] = (
                    item.editable
                    and "templates:write" in author.credential.scopes
                    and item.project_count == len(data["projects"])
                )
                visible.append(data)
            offset, limit = args.get("offset", 0), args.get("limit", 50)
            if not 0 <= offset or not 1 <= limit <= 100 or len(query) > 200:
                raise ApplicationError(
                    422, "Use offset >= 0, limit 1–100, query <= 200 characters"
                )
            return {
                "items": visible[offset : offset + limit],
                "total": len(visible),
                "offset": offset,
            }
        if operation == "create_template":
            author.require_write()
            payload = TemplateInput.model_validate(args["payload"])
            if (
                not payload.project_ids
                or not set(payload.project_ids) <= author.project_ids
            ):
                raise ApplicationError(403, "Connect only projects in credential scope")
            if payload.draft.layout:
                await template_access(db, author, payload.draft.layout.template_id)
            return await templates.create_template(payload, db, principal)
        template_id = args["template_id"]
        write = operation in {"add_language", "create_branch"} or (
            operation == "preview" and args["payload"].draft is not None
        )
        await template_access(db, author, template_id, write=write)
        if operation == "get_template":
            result = await templates.get_template(
                template_id, db, principal, args["branch_id"]
            )
            result.projects = [p for p in result.projects if p.id in author.project_ids]
            result.editable = (
                result.editable
                and "templates:write" in author.credential.scopes
                and result.project_count == len(result.projects)
            )
            result.manage_bindings = False
            return result
        if operation == "list_branches":
            return await versions.branches(template_id, db, principal)
        if operation == "list_versions":
            return await versions.versions(template_id, db, principal)
        if operation == "get_version":
            return await versions.get_version(
                template_id, args["version_id"], db, principal
            )
        if operation == "diff_versions":
            comparison = await versions.diff(
                template_id, args["before"], args["after"], db, principal
            )
            return {key: encoded(value) for key, value in comparison.items()}
        if operation == "add_language":
            return await versions.add_language(
                template_id,
                LanguageInput.model_validate(args["payload"]),
                db,
                principal,
            )
        if operation == "create_branch":
            return await versions.fork(
                template_id, BranchInput.model_validate(args["payload"]), db, principal
            )
        if operation == "preview":
            if args["version_id"] is not None:
                return await versions.version_preview(
                    template_id,
                    args["version_id"],
                    args["payload"],
                    self.runtime,
                    db,
                    principal,
                )
            return await templates.preview(
                template_id, args["payload"], self.runtime, db, principal
            )
        raise ApplicationError(422, "Unknown authoring operation")

    async def batch(
        self,
        token: str,
        changes: ChangeSet,
        apply: bool,
        confirmed_plan_hash: str = "",
        confirm: bool = False,
    ) -> dict[str, Any]:
        digest = plan_hash(changes)
        if apply and (
            not confirm or not hmac.compare_digest(digest, confirmed_plan_hash)
        ):
            raise ApplicationError(
                422, "Explicit confirmation and the unchanged plan hash are required"
            )
        # No batch-wide transaction: each item uses the same domain save transaction
        # as the dashboard. Results are ordered, explicit and never all-or-nothing.
        results = []
        for change in changes.items:
            writing = False
            identity = {
                "template_id": str(change.template_id),
                "branch_id": str(change.branch_id),
            }
            try:
                async with self.factory() as db:
                    author = await authenticate(token, db, self.runtime.settings)
                    await template_access(db, author, change.template_id, write=True)
                    current = await templates.get_template(
                        change.template_id, db, author.principal, change.branch_id
                    )
                    if current.draft_revision != change.expected_revision:
                        raise ApplicationError(
                            409,
                            "Draft revision conflict; read the branch and prepare a new plan",
                        )
                    report = await templates.preview(
                        change.template_id,
                        PreviewInput(
                            draft=change.draft,
                            branch_id=change.branch_id,
                            project_id=change.project_id,
                            environment_id=change.environment_id,
                        ),
                        self.runtime,
                        db,
                        author.principal,
                    )
                    if apply:
                        if report.errors:
                            results.append(
                                {
                                    **identity,
                                    "ok": False,
                                    "status": 422,
                                    "state": "invalid",
                                    "preview": encoded(report),
                                }
                            )
                            continue
                        writing = True
                        saved = await templates.save_draft(
                            change.template_id,
                            DraftUpdate(
                                draft=change.draft,
                                branch_id=change.branch_id,
                                expected_revision=change.expected_revision,
                            ),
                            db,
                            author.principal,
                        )
                        results.append(
                            {
                                **identity,
                                "ok": True,
                                "state": "saved",
                                "draft_revision": saved.draft_revision,
                            }
                        )
                    else:
                        before = json.dumps(
                            current.draft.model_dump(),
                            sort_keys=True,
                            indent=2,
                            ensure_ascii=False,
                        ).splitlines()
                        after = json.dumps(
                            change.draft.model_dump(),
                            sort_keys=True,
                            indent=2,
                            ensure_ascii=False,
                        ).splitlines()
                        results.append(
                            {
                                **identity,
                                "ok": not report.errors,
                                "state": "planned",
                                "expected_revision": change.expected_revision,
                                "diff": "\n".join(
                                    difflib.unified_diff(
                                        before,
                                        after,
                                        fromfile="saved",
                                        tofile="proposed",
                                    )
                                ),
                                "preview": encoded(report),
                            }
                        )
            except (ApplicationError, ValidationError) as error:
                if writing and not (
                    isinstance(error, ApplicationError) and error.status_code == 409
                ):
                    results.append(
                        {
                            **identity,
                            "ok": False,
                            "status": 500,
                            "state": "unknown",
                            "error": "Save outcome uncertain; re-read this branch before retrying",
                        }
                    )
                    continue
                results.append(
                    {
                        **identity,
                        **failure(error),
                        "state": "conflict"
                        if isinstance(error, ApplicationError)
                        and error.status_code == 409
                        else "error",
                    }
                )
            except SQLAlchemyError:
                # A lost commit acknowledgement cannot safely be reported as an
                # unsaved item. The caller must re-read the exact branch revision.
                results.append(
                    {
                        **identity,
                        "ok": False,
                        "status": 503,
                        "state": "unknown",
                        "error": "Database failure; re-read this branch before retrying",
                    }
                )
            except Exception:
                # Preserve earlier committed item results even if an unexpected
                # renderer/service failure happens here, including after commit.
                # Do not echo exception text or submitted values.
                results.append(
                    {
                        **identity,
                        "ok": False,
                        "status": 500,
                        "state": "unknown",
                        "error": "Authoring failed; re-read this branch before retrying",
                    }
                )
        return {
            "ok": all(item["ok"] for item in results),
            "mode": "apply" if apply else "plan",
            "plan_hash": digest,
            "atomic": False,
            "items": results,
        }
