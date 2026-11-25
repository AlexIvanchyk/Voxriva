import asyncio
import re
import secrets
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.features.identity.models import Account
from backend.app.features.identity.schemas import Principal
from backend.app.features.identity.service import audit, commit, digest, hash_password
from backend.app.features.projects.models import (
    DeliveryKey,
    Environment,
    Membership,
    Project,
)
from backend.app.features.projects.schemas import (
    DeliveryScope,
    EnvironmentInventory,
    InventoryKey,
    IssuedKey,
    KeyEnvironment,
    KeyInput,
    KeyInventory,
    KeyView,
    MemberInput,
    MemberView,
    NamedInput,
    NamedResource,
    ProjectView,
    RoleInput,
    environments,
)
from backend.app.infrastructure.context import ApplicationContext
from backend.app.infrastructure.database import utcnow
from backend.app.infrastructure.errors import ApplicationError

environment = f"{environments}/{{environment_id}}"
KEY_FORMAT = re.compile("vxk_[a-zA-Z0-9_-]{43}")


async def project_access(
    db: AsyncSession, principal: Principal, project_id: UUID, write: bool = False
) -> tuple[Project, str]:
    item = await db.get(Project, project_id)
    if item is not None:
        if principal.account.platform_admin:
            return (item, "platform_admin")
        member = await db.get(Membership, (project_id, principal.account.id))
        if member is not None:
            if write and member.role != "project_admin":
                raise ApplicationError(403, "Project administrator access required")
            return (item, member.role)
    raise ApplicationError(404, "Project not found")


async def scoped_environment(
    db: AsyncSession, project_id: UUID, environment_id: UUID
) -> Environment:
    item = await db.scalar(
        select(Environment).where(
            Environment.id == environment_id, Environment.project_id == project_id
        )
    )
    if item is None:
        raise ApplicationError(404, "Environment not found")
    return item


async def list_projects(principal: Principal, db: AsyncSession) -> list[ProjectView]:
    query = select(Project).order_by(Project.name, Project.id)
    if principal.account.platform_admin:
        return [
            ProjectView(id=item.id, name=item.name, role="platform_admin")
            for item in await db.scalars(query)
        ]
    rows = await db.execute(
        query.add_columns(Membership.role)
        .join(Membership)
        .where(Membership.account_id == principal.account.id)
    )
    return [ProjectView(id=item.id, name=item.name, role=role) for item, role in rows]


async def add_project(
    payload: NamedInput, principal: Principal, db: AsyncSession
) -> ProjectView:
    item = Project(id=uuid4(), name=payload.name)
    db.add(item)
    audit(db, principal.account.id, "project.create", item.id, item.id)
    await commit(db)
    return ProjectView(id=item.id, name=item.name, role="platform_admin")


async def get_project(
    project_id: UUID, principal: Principal, db: AsyncSession
) -> ProjectView:
    item, role = await project_access(db, principal, project_id)
    return ProjectView(id=item.id, name=item.name, role=role)


async def edit_project(
    project_id: UUID, payload: NamedInput, principal: Principal, db: AsyncSession
) -> ProjectView:
    item, role = await project_access(db, principal, project_id, True)
    item.name = payload.name
    audit(db, principal.account.id, "project.update", item.id, item.id)
    await commit(db)
    return ProjectView(id=item.id, name=item.name, role=role)


async def delete_project(
    project_id: UUID, principal: Principal, db: AsyncSession
) -> None:
    item, _ = await project_access(db, principal, project_id, True)
    audit(db, principal.account.id, "project.delete", item.id, item.id)
    await db.delete(item)
    await commit(db)


async def list_envs(
    project_id: UUID, principal: Principal, db: AsyncSession
) -> list[Environment]:
    await project_access(db, principal, project_id)
    return list(
        await db.scalars(
            select(Environment)
            .where(Environment.project_id == project_id)
            .order_by(Environment.name, Environment.id)
        )
    )


async def add_env(
    project_id: UUID, payload: NamedInput, principal: Principal, db: AsyncSession
) -> Environment:
    await project_access(db, principal, project_id, True)
    item = Environment(id=uuid4(), project_id=project_id, name=payload.name)
    db.add(item)
    audit(db, principal.account.id, "environment.create", item.id, project_id)
    await commit(db)
    return item


async def get_env(
    project_id: UUID, environment_id: UUID, principal: Principal, db: AsyncSession
) -> Environment:
    await project_access(db, principal, project_id)
    return await scoped_environment(db, project_id, environment_id)


async def edit_env(
    project_id: UUID,
    environment_id: UUID,
    payload: NamedInput,
    principal: Principal,
    db: AsyncSession,
) -> Environment:
    await project_access(db, principal, project_id, True)
    item = await scoped_environment(db, project_id, environment_id)
    item.name = payload.name
    audit(db, principal.account.id, "environment.update", item.id, project_id)
    await commit(db)
    return item


async def delete_env(
    project_id: UUID, environment_id: UUID, principal: Principal, db: AsyncSession
) -> None:
    await project_access(db, principal, project_id, True)
    item = await scoped_environment(db, project_id, environment_id)
    audit(db, principal.account.id, "environment.delete", item.id, project_id)
    await db.delete(item)
    await commit(db)


def member_view(account: Account, member: Membership | None) -> MemberView:
    return MemberView.model_validate(
        {
            "account_id": account.id,
            "email": account.email,
            "display_name": account.display_name,
            "role": "platform_admin"
            if account.platform_admin
            else member.role
            if member
            else "viewer",
            "created_at": member.created_at if member else account.created_at,
            "inherited": account.platform_admin,
        }
    )


async def list_members(
    project_id: UUID, principal: Principal, db: AsyncSession
) -> list[MemberView]:
    await project_access(db, principal, project_id)
    rows = await db.execute(
        select(Account, Membership)
        .outerjoin(
            Membership,
            and_(
                Membership.account_id == Account.id, Membership.project_id == project_id
            ),
        )
        .where(or_(Membership.project_id == project_id, Account.platform_admin))
        .order_by(Account.email)
    )
    return [member_view(account, member) for account, member in rows]


async def add_member(
    project_id: UUID,
    payload: MemberInput,
    runtime: ApplicationContext,
    principal: Principal,
    db: AsyncSession,
) -> MemberView:
    await project_access(db, principal, project_id, True)
    account = await db.scalar(
        select(Account).where(Account.email == payload.email).with_for_update()
    )
    if account is not None:
        if account.platform_admin:
            raise ApplicationError(
                409, "This user already has installation administrator access"
            )
        if payload.password:
            raise ApplicationError(
                409,
                "This account already exists. Leave the initial password empty to grant project access.",
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
        audit(db, principal.account.id, "account.create", account.id, project_id)
    member = Membership(
        project_id=project_id,
        account_id=account.id,
        role=payload.role,
        created_at=utcnow(),
    )
    db.add(member)
    audit(db, principal.account.id, "membership.create", account.id, project_id)
    await commit(db, "This user is already a member of the project")
    return member_view(account, member)


async def managed_membership(
    db: AsyncSession, principal: Principal, project_id: UUID, account_id: UUID
) -> tuple[Account, Membership]:
    await project_access(db, principal, project_id, True)
    if principal.account.id == account_id:
        raise ApplicationError(403, "You cannot change your own project membership")
    account = await db.scalar(
        select(Account).where(Account.id == account_id).with_for_update()
    )
    member = await db.get(Membership, (project_id, account_id))
    if account is None or member is None or account.platform_admin:
        raise ApplicationError(404, "Project member not found")
    return (account, member)


async def edit_member(
    project_id: UUID,
    account_id: UUID,
    payload: RoleInput,
    principal: Principal,
    db: AsyncSession,
) -> MemberView:
    account, member = await managed_membership(db, principal, project_id, account_id)
    member.role = payload.role
    audit(db, principal.account.id, "membership.update", account_id, project_id)
    await commit(db)
    return member_view(account, member)


async def delete_member(
    project_id: UUID, account_id: UUID, principal: Principal, db: AsyncSession
) -> None:
    _, member = await managed_membership(db, principal, project_id, account_id)
    audit(db, principal.account.id, "membership.delete", account_id, project_id)
    await db.delete(member)
    await commit(db)


async def key_inventory(principal: Principal, db: AsyncSession) -> KeyInventory:
    query = (
        select(Environment, Project, DeliveryKey)
        .select_from(Environment)
        .join(Project)
        .outerjoin(DeliveryKey, DeliveryKey.environment_id == Environment.id)
        .order_by(
            Project.name,
            Environment.name,
            DeliveryKey.created_at.desc(),
            DeliveryKey.id,
        )
    )
    if not principal.account.platform_admin:
        allowed = select(Membership.project_id).where(
            Membership.account_id == principal.account.id,
            Membership.role == "project_admin",
        )
        query = query.where(Project.id.in_(allowed))
    scopes: dict[UUID, KeyEnvironment] = {}
    keys = []
    for env, proj, key in await db.execute(query):
        scopes[env.id] = KeyEnvironment(
            id=env.id, name=env.name, project=NamedResource.model_validate(proj)
        )
        if key is not None:
            keys.append(InventoryKey.model_validate(key))
    return KeyInventory(environments=list(scopes.values()), keys=keys)


async def list_keys(
    project_id: UUID, environment_id: UUID, principal: Principal, db: AsyncSession
) -> list[DeliveryKey]:
    await project_access(db, principal, project_id, True)
    await scoped_environment(db, project_id, environment_id)
    return list(
        await db.scalars(
            select(DeliveryKey)
            .where(DeliveryKey.environment_id == environment_id)
            .order_by(DeliveryKey.created_at.desc())
        )
    )


async def issue_key(
    project_id: UUID,
    environment_id: UUID,
    payload: KeyInput,
    principal: Principal,
    db: AsyncSession,
) -> IssuedKey:
    await project_access(db, principal, project_id, True)
    await scoped_environment(db, project_id, environment_id)
    token = f"vxk_{secrets.token_urlsafe(32)}"
    now = utcnow()
    item = DeliveryKey(
        id=uuid4(),
        environment_id=environment_id,
        name=payload.name,
        prefix=token[:12],
        token_hash=digest(token),
        created_at=now,
        expires_at=now + timedelta(days=payload.expires_in_days)
        if payload.expires_in_days
        else None,
    )
    db.add(item)
    audit(db, principal.account.id, "key.create", item.id, project_id)
    await commit(db)
    return IssuedKey(**KeyView.model_validate(item).model_dump(), key=token)


async def revoke_key(
    project_id: UUID,
    environment_id: UUID,
    key_id: UUID,
    principal: Principal,
    db: AsyncSession,
) -> None:
    await project_access(db, principal, project_id, True)
    await scoped_environment(db, project_id, environment_id)
    item = await db.scalar(
        select(DeliveryKey)
        .where(DeliveryKey.id == key_id, DeliveryKey.environment_id == environment_id)
        .with_for_update()
    )
    if item is None:
        raise ApplicationError(404, "API key not found")
    if item.revoked_at is None:
        item.revoked_at = utcnow()
        audit(db, principal.account.id, "key.revoke", key_id, project_id)
        await commit(db)


async def get_key_scope(scope: DeliveryScope) -> DeliveryScope:
    return scope


async def environment_inventory(
    principal: Principal, db: AsyncSession
) -> list[EnvironmentInventory]:
    query = (
        select(Environment, Project)
        .select_from(Environment)
        .join(Project)
        .order_by(Project.name, Environment.name, Environment.id)
    )
    roles = {
        member.project_id: member.role
        for member in await db.scalars(
            select(Membership).where(Membership.account_id == principal.account.id)
        )
    }
    if not principal.account.platform_admin:
        query = query.where(Project.id.in_(roles))
    return [
        EnvironmentInventory(
            id=env.id,
            name=env.name,
            project_id=proj.id,
            project_name=proj.name,
            editable=principal.account.platform_admin
            or roles.get(proj.id) == "project_admin",
        )
        for env, proj in await db.execute(query)
    ]
