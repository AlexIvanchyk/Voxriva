"""Management credential lifecycle and the additional MCP project boundary."""

import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.features.identity.models import Account, AccountMFA
from backend.app.features.identity.schemas import Principal
from backend.app.features.identity.service import audit, commit, digest
from backend.app.features.management.models import ManagementCredential
from backend.app.features.management.schemas import (
    CredentialInput,
    CredentialView,
    IssuedCredential,
)
from backend.app.features.projects.service import project_access
from backend.app.features.templates.models import TemplateProject
from backend.app.features.templates.service import lookup
from backend.app.infrastructure.database import utcnow
from backend.app.infrastructure.errors import ApplicationError
from backend.app.infrastructure.settings import Settings


async def issue(
    payload: CredentialInput, db: AsyncSession, principal: Principal
) -> IssuedCredential:
    for identifier in payload.project_ids:
        _, role = await project_access(db, principal, identifier)
        if "templates:write" in payload.scopes and role not in {
            "platform_admin",
            "project_admin",
            "template_editor",
        }:
            raise ApplicationError(
                403, "Template editor access required for write credentials"
            )
    token = "vxm_" + secrets.token_urlsafe(32)
    item = ManagementCredential(
        account_id=principal.account.id,
        token_hash=digest(token),
        name=payload.name,
        project_ids=[str(key) for key in payload.project_ids],
        scopes=payload.scopes,
        expires_at=utcnow() + timedelta(days=payload.expires_in_days),
    )
    db.add(item)
    await db.flush()
    audit(db, principal.account.id, "management.credential.create", item.id)
    await commit(db)
    return IssuedCredential(credential=CredentialView.model_validate(item), token=token)


async def credentials(db: AsyncSession, principal: Principal) -> list[CredentialView]:
    return [
        CredentialView.model_validate(item)
        for item in await db.scalars(
            select(ManagementCredential)
            .where(ManagementCredential.account_id == principal.account.id)
            .order_by(ManagementCredential.created_at.desc())
        )
    ]


async def revoke(identifier: UUID, db: AsyncSession, principal: Principal) -> None:
    item = await db.get(ManagementCredential, identifier)
    if item is None or (
        item.account_id != principal.account.id and not principal.account.platform_admin
    ):
        raise ApplicationError(404, "Management credential not found")
    item.revoked_at = utcnow()
    audit(db, principal.account.id, "management.credential.revoke", item.id)
    await commit(db)


@dataclass(frozen=True)
class Author:
    principal: Principal
    credential: ManagementCredential

    @property
    def project_ids(self) -> set[UUID]:
        return {UUID(value) for value in self.credential.project_ids}

    def require_write(self) -> None:
        if "templates:write" not in self.credential.scopes:
            raise ApplicationError(403, "Credential requires templates:write")


async def authenticate(
    token: str, db: AsyncSession, settings: Settings | None = None
) -> Author:
    if not re.fullmatch(r"vxm_[A-Za-z0-9_-]{43}", token):
        raise ApplicationError(401, "Invalid management credential")
    item = await db.scalar(
        select(ManagementCredential).where(
            ManagementCredential.token_hash == digest(token),
            ManagementCredential.revoked_at.is_(None),
            ManagementCredential.expires_at > utcnow(),
        )
    )
    account = await db.get(Account, item.account_id) if item else None
    if item is None or account is None or "templates:read" not in item.scopes:
        raise ApplicationError(401, "Invalid management credential")
    if settings is not None and settings.mfa_policy == "required":
        factor = await db.get(AccountMFA, account.id)
        if factor is None or not factor.enabled:
            raise ApplicationError(401, "MFA enrollment required")
    # Reloaded on every call: membership removal, demotion and revocation take effect
    # without terminating an MCP connection. Never elevate the account's live role.
    return Author(
        Principal(account, "", frozenset(UUID(value) for value in item.project_ids)),
        item,
    )


async def template_access(
    db: AsyncSession, author: Author, template_id: UUID, write: bool = False
) -> None:
    if write:
        author.require_write()
    # Domain writes and binding changes lock the template row. Acquire that lock
    # before reading its connections so credential scope cannot race a rebind.
    await lookup(db, author.principal, template_id, write=write)
    connected = set(
        await db.scalars(
            select(TemplateProject.project_id).where(
                TemplateProject.template_id == template_id
            )
        )
    )
    allowed = connected & author.project_ids
    if not allowed or (write and not connected <= author.project_ids):
        raise ApplicationError(404, "Template not found in credential scope")
    # A shared template visible through another membership must not make a revoked
    # in-scope membership sufficient. Check the intersection against live RBAC too.
    accessible = False
    for identifier in allowed:
        try:
            await project_access(db, author.principal, identifier)
            accessible = True
        except ApplicationError as error:
            if error.status_code not in {403, 404}:
                raise
    if not accessible:
        raise ApplicationError(404, "Template not found in credential scope")
