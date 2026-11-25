"""Account directory and atomic grants to multiple explicitly selected projects."""

import asyncio
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.features.identity.models import Account
from backend.app.features.identity.schemas import Principal
from backend.app.features.identity.service import audit, commit, hash_password
from backend.app.features.projects.members_schemas import (
    DirectoryMember,
    GrantView,
    MemberCreate,
    MemberUpdate,
)
from backend.app.features.projects.models import Membership, Project
from backend.app.features.projects.service import project_access
from backend.app.infrastructure.context import ApplicationContext
from backend.app.infrastructure.database import utcnow
from backend.app.infrastructure.errors import ApplicationError


async def directory(db: AsyncSession, principal: Principal) -> list[DirectoryMember]:
    own = {
        member.project_id: member.role
        for member in await db.scalars(
            select(Membership).where(Membership.account_id == principal.account.id)
        )
    }
    if not principal.account.platform_admin and (not own):
        return []
    projects = (
        select(Project.id)
        if principal.account.platform_admin
        else select(Project.id).where(Project.id.in_(own))
    )
    rows = await db.execute(
        select(Account, Membership, Project)
        .select_from(Account)
        .outerjoin(
            Membership,
            and_(
                Membership.account_id == Account.id, Membership.project_id.in_(projects)
            ),
        )
        .outerjoin(Project, Project.id == Membership.project_id)
        .where(or_(Membership.project_id.is_not(None), Account.platform_admin))
        .order_by(Account.email, Project.name)
    )
    members: dict[UUID, DirectoryMember] = {}
    for account, membership, project in rows:
        item = members.setdefault(
            account.id,
            DirectoryMember(
                account_id=account.id,
                email=account.email,
                display_name=account.display_name,
                inherited=account.platform_admin,
                created_at=account.created_at,
                projects=[],
            ),
        )
        if membership and project:
            item.projects.append(
                GrantView(
                    project_id=project.id,
                    project_name=project.name,
                    role=membership.role,
                    created_at=membership.created_at,
                    editable=not account.platform_admin
                    and account.id != principal.account.id
                    and (
                        principal.account.platform_admin
                        or own.get(project.id) == "project_admin"
                    ),
                )
            )
    all_memberships = list(
        await db.scalars(select(Membership).where(Membership.account_id.in_(members)))
    )
    for member in members.values():
        grants = [
            grant for grant in all_memberships if grant.account_id == member.account_id
        ]
        member.can_edit_name = (
            principal.account.platform_admin
            or member.account_id == principal.account.id
            or (
                not member.inherited
                and bool(grants)
                and all(
                    own.get(grant.project_id) == "project_admin" for grant in grants
                )
            )
        )
    return list(members.values())


async def add_member(
    payload: MemberCreate,
    runtime: ApplicationContext,
    db: AsyncSession,
    principal: Principal,
) -> DirectoryMember:
    for grant in payload.projects:
        await project_access(db, principal, grant.project_id, True)
    account = await db.scalar(
        select(Account).where(Account.email == payload.email).with_for_update()
    )
    if account:
        if account.platform_admin:
            raise ApplicationError(
                409, "This user already has installation administrator access"
            )
        if payload.password:
            raise ApplicationError(
                409,
                "This account already exists. Leave the initial password empty to grant project access.",
            )
        if await db.scalar(
            select(Membership.project_id)
            .where(
                Membership.account_id == account.id,
                Membership.project_id.in_(
                    [grant.project_id for grant in payload.projects]
                ),
            )
            .limit(1)
        ):
            raise ApplicationError(
                409,
                "This user already belongs to a selected project. Change their existing role from the directory.",
            )
    else:
        if not payload.password:
            raise ApplicationError(
                422,
                "Set an initial password for this new user (at least 12 characters)",
            )
        slots: asyncio.Semaphore = runtime.password_slots
        async with slots:
            encoded = await hash_password(payload.password)
        account = Account(
            id=uuid4(),
            email=payload.email,
            display_name=payload.display_name,
            password_hash=encoded,
            platform_admin=False,
            created_at=utcnow(),
        )
        db.add(account)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            raise ApplicationError(
                409,
                "This account was created concurrently. Try adding the existing user without an initial password.",
            ) from None
        audit(db, principal.account.id, "account.create", account.id)
    for grant in payload.projects:
        db.add(
            Membership(
                project_id=grant.project_id,
                account_id=account.id,
                role=grant.role,
                created_at=utcnow(),
            )
        )
        audit(
            db, principal.account.id, "membership.create", account.id, grant.project_id
        )
    await commit(
        db,
        "Project access changed concurrently. No selected access was partially saved.",
    )
    return next(
        item for item in await directory(db, principal) if item.account_id == account.id
    )


async def update_member(
    account_id: UUID, payload: MemberUpdate, db: AsyncSession, principal: Principal
) -> dict[str, str]:
    account = await db.scalar(
        select(Account)
        .where(Account.id == account_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    visible = next(
        (
            item
            for item in await directory(db, principal)
            if item.account_id == account_id
        ),
        None,
    )
    if account is None or visible is None:
        raise ApplicationError(404, "Member not found")
    own = {
        member.project_id: member.role
        for member in await db.scalars(
            select(Membership).where(Membership.account_id == principal.account.id)
        )
    }
    managed = (
        set(await db.scalars(select(Project.id)))
        if principal.account.platform_admin
        else {identifier for identifier, role in own.items() if role == "project_admin"}
    )
    memberships = list(
        await db.scalars(select(Membership).where(Membership.account_id == account_id))
    )
    if account.display_name != payload.expected_display_name:
        raise ApplicationError(409, "This profile changed. Reload before saving.")
    if (
        payload.display_name is not None
        and payload.display_name != account.display_name
    ):
        if not (
            principal.account.platform_admin
            or account_id == principal.account.id
            or (
                not account.platform_admin
                and bool(memberships)
                and all(member.project_id in managed for member in memberships)
            )
        ):
            raise ApplicationError(
                403,
                "Changing this shared profile requires administrator access to all its projects",
            )
    if payload.projects is not None:
        if account.platform_admin or account_id == principal.account.id:
            raise ApplicationError(
                403, "Inherited or personal project permissions cannot be changed here"
            )
        if any(
            grant.project_id not in managed
            for grant in payload.projects + payload.expected_projects
        ):
            raise ApplicationError(
                403, "You can only change access in projects you administer"
            )
        current = {
            member.project_id: member.role
            for member in memberships
            if member.project_id in managed
        }
        expected = {grant.project_id: grant.role for grant in payload.expected_projects}
        if current != expected:
            raise ApplicationError(409, "Project access changed. Reload before saving.")
        desired = {grant.project_id: grant.role for grant in payload.projects}
        for member in memberships:
            if member.project_id not in managed:
                continue
            if member.project_id not in desired:
                await db.delete(member)
                audit(
                    db,
                    principal.account.id,
                    "membership.delete",
                    account_id,
                    member.project_id,
                )
            elif desired[member.project_id] != member.role:
                member.role = desired[member.project_id]
                audit(
                    db,
                    principal.account.id,
                    "membership.update",
                    account_id,
                    member.project_id,
                )
        for identifier, role in desired.items():
            if identifier not in current:
                db.add(
                    Membership(
                        project_id=identifier,
                        account_id=account_id,
                        role=role,
                        created_at=utcnow(),
                    )
                )
                audit(
                    db,
                    principal.account.id,
                    "membership.create",
                    account_id,
                    identifier,
                )
    if (
        payload.display_name is not None
        and payload.display_name != account.display_name
    ):
        account.display_name = payload.display_name
        audit(db, principal.account.id, "account.profile.update", account_id)
    await commit(db, "Member access changed concurrently. Reload before saving.")
    return {"status": "saved"}
