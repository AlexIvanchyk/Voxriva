"""Readable audit references resolved only through the reader's current access.

Historical IDs remain available; legacy metadata and credentials are never returned.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.features.identity.models import Account, AuditEvent
from backend.app.features.identity.schemas import Principal
from backend.app.features.management.models import ManagementCredential
from backend.app.features.notifications.models import Notification
from backend.app.features.projects.models import (
    DeliveryKey,
    Environment,
    Membership,
    Project,
)
from backend.app.features.providers.models import (
    ProviderBinding,
    ProviderConfiguration,
    ProviderRevision,
)
from backend.app.features.templates.models import (
    Template,
    TemplateBranch,
    TemplateProject,
    TemplateVersion,
)

ACTIONS = {
    "account.bootstrap": "Installation administrator created",
    "account.create": "Account created",
    "account.profile.update": "Member profile updated",
    "membership.create": "Project access granted",
    "membership.update": "Project role changed",
    "membership.delete": "Project access removed",
    "project.create": "Project created",
    "project.update": "Project renamed",
    "project.delete": "Project deleted",
    "environment.create": "Environment created",
    "environment.update": "Environment renamed",
    "environment.delete": "Environment deleted",
    "key.create": "Delivery API key created",
    "key.revoke": "Delivery API key revoked",
    "template.create": "Template created",
    "template.delete": "Template deleted",
    "template.projects.update": "Template connections updated",
    "template.draft.update": "Template draft saved",
    "template.publish": "Template version published",
    "template.language.create": "Template language added",
    "template.branch.create": "Template branch created",
    "template.deploy": "Template version deployed",
    "template.rollback": "Template deployment rolled back",
    "template.promote": "Template deployment promoted",
    "template.clear": "Deployment override cleared",
    "template.fallback.update": "Fallback language changed",
    "template.primary.update": "Primary language changed",
    "provider.create": "Provider created",
    "provider.revision.create": "Provider revision saved",
    "provider.binding.update": "Provider assignment changed",
    "provider.test_connection": "Provider connection tested",
    "provider.test_send": "Provider test message requested",
    "provider.test_validate": "Provider validation requested",
    "notification.replay": "Failed notification replayed",
    "management.credential.create": "Management credential created",
    "management.credential.revoke": "Management credential revoked",
    "mfa.setup": "MFA setup started",
    "mfa.replace_setup": "MFA replacement started",
    "mfa.enabled": "Multi-factor authentication enabled",
    "mfa.disabled": "Multi-factor authentication disabled",
    "mfa.replaced": "Authenticator replaced",
    "mfa.proof_failed": "MFA verification failed",
    "mfa.recovery_regenerated": "MFA recovery codes regenerated",
    "mfa.login": "Signed in with MFA",
    "account.mfa.enable": "Multi-factor authentication enabled",
    "account.mfa.disable": "Multi-factor authentication disabled",
}


def target_kind(action: str) -> str:
    if action.startswith(("account.", "membership.", "mfa.")):
        return "account"
    if action == "template.publish":
        return "version"
    if action in {"template.branch.create", "template.language.create"}:
        return "branch"
    if action.startswith("provider.test_"):
        return "provider revision"
    if action == "provider.binding.update":
        return "provider assignment"
    if action.startswith("provider."):
        return "provider"
    if action.startswith("management."):
        return "management credential"
    return {"key": "API key"}.get(action.split(".")[0], action.split(".")[0])


async def present_audit(
    db: AsyncSession, principal: Principal, rows: list[AuditEvent]
) -> list[dict[str, Any]]:
    if not rows:
        return []
    admin = principal.account.platform_admin
    visible = (
        select(Project.id)
        if admin
        else select(Membership.project_id).where(
            Membership.account_id == principal.account.id
        )
    )
    projects = {
        item.id: item.name
        for item in await db.scalars(select(Project).where(Project.id.in_(visible)))
    }
    account_ids = {row.actor_id for row in rows} | {
        row.target_id for row in rows if target_kind(row.action) == "account"
    }
    account_query = select(Account).where(Account.id.in_(account_ids))
    if not admin:
        account_query = account_query.where(
            or_(
                Account.id == principal.account.id,
                Account.platform_admin.is_(True),
                Account.id.in_(
                    select(Membership.account_id).where(
                        Membership.project_id.in_(visible)
                    )
                ),
            )
        )
    accounts = {
        item.id: item.display_name or item.email
        for item in await db.scalars(account_query)
    }
    targets: dict[tuple[str, UUID], dict[str, str]] = {}

    def put(kind: str, identifier: UUID, label: str, href: str) -> None:
        targets[kind, identifier] = {"label": label, "href": href}

    ids = {row.target_id for row in rows}
    for identifier, name in accounts.items():
        put("account", identifier, name, "/members")
    for identifier, name in projects.items():
        put("project", identifier, name, f"/projects?project={identifier}")
    for env in await db.scalars(
        select(Environment).where(
            Environment.id.in_(ids), Environment.project_id.in_(visible)
        )
    ):
        put(
            "environment",
            env.id,
            f"{projects[env.project_id]} / {env.name}",
            f"/environments?project={env.project_id}",
        )
    for key, env in await db.execute(
        select(DeliveryKey, Environment)
        .join(Environment)
        .where(DeliveryKey.id.in_(ids), Environment.project_id.in_(visible))
    ):
        put(
            "API key",
            key.id,
            key.name,
            f"/api-keys?project={env.project_id}&environment={env.id}",
        )
    readable_templates = select(Template.id)
    if not admin:
        readable_templates = readable_templates.where(
            Template.id.in_(
                select(TemplateProject.template_id).where(
                    TemplateProject.project_id.in_(visible)
                )
            )
        )
    for template in await db.scalars(
        select(Template).where(
            Template.id.in_(ids), Template.id.in_(readable_templates)
        )
    ):
        put("template", template.id, template.name, f"/templates/{template.id}")
    for branch, template in await db.execute(
        select(TemplateBranch, Template)
        .join(Template)
        .where(TemplateBranch.id.in_(ids), Template.id.in_(readable_templates))
    ):
        put(
            "branch",
            branch.id,
            f"{template.name} · {branch.name} · {branch.locale}",
            f"/templates/{template.id}?branch={branch.id}",
        )
    for version, branch, template in await db.execute(
        select(TemplateVersion, TemplateBranch, Template)
        .join(TemplateBranch, TemplateVersion.branch_id == TemplateBranch.id)
        .join(Template, TemplateVersion.template_id == Template.id)
        .where(TemplateVersion.id.in_(ids), Template.id.in_(readable_templates))
    ):
        put(
            "version",
            version.id,
            f"{template.name} · {branch.name} · v{version.number} · {version.locale}",
            f"/templates/{template.id}?tab=versions&branch={branch.id}",
        )
    readable_providers = select(ProviderConfiguration.id)
    if not admin:
        readable_providers = readable_providers.where(
            or_(
                ProviderConfiguration.project_id.is_(None),
                ProviderConfiguration.project_id.in_(visible),
            )
        )
    for provider in await db.scalars(
        select(ProviderConfiguration).where(
            ProviderConfiguration.id.in_(ids),
            ProviderConfiguration.id.in_(readable_providers),
        )
    ):
        put("provider", provider.id, provider.name, "/providers")
    for revision, provider in await db.execute(
        select(ProviderRevision, ProviderConfiguration)
        .join(ProviderConfiguration)
        .where(
            ProviderRevision.id.in_(ids),
            ProviderConfiguration.id.in_(readable_providers),
        )
    ):
        put(
            "provider revision",
            revision.id,
            f"{provider.name} · r{revision.number}",
            "/providers",
        )
    binding_query = select(ProviderBinding).where(ProviderBinding.id.in_(ids))
    if not admin:
        binding_query = binding_query.where(ProviderBinding.project_id.in_(visible))
    for binding in await db.scalars(binding_query):
        label = (
            projects.get(binding.project_id, "Global default")
            if binding.project_id
            else "Global default"
        )
        put(
            "provider assignment",
            binding.id,
            f"{label} · {binding.channel}",
            "/providers",
        )
    for notification in await db.scalars(
        select(Notification).where(
            Notification.id.in_(ids), Notification.project_id.in_(visible)
        )
    ):
        put(
            "notification",
            notification.id,
            f"{notification.channel.capitalize()} delivery",
            f"/notifications/{notification.id}",
        )
    if admin:
        for credential in await db.scalars(
            select(ManagementCredential).where(
                ManagementCredential.id.in_(ids),
                ManagementCredential.account_id == principal.account.id,
            )
        ):
            put(
                "management credential",
                credential.id,
                credential.name,
                "/account/security",
            )
    return [
        {
            "id": row.id,
            "actor_id": row.actor_id,
            "project_id": row.project_id,
            "action": row.action,
            "action_label": ACTIONS.get(row.action, "Other activity"),
            "target_id": row.target_id,
            "created_at": row.created_at,
            "project_name": projects.get(
                row.project_id, "Deleted or unavailable project"
            )
            if row.project_id
            else "Installation",
            "actor": {
                "label": accounts.get(row.actor_id, "Deleted or unavailable account"),
                "href": "/members" if row.actor_id in accounts else None,
            },
            "target": targets.get(
                (target_kind(row.action), row.target_id),
                {
                    "label": f"Deleted or unavailable {target_kind(row.action)}",
                    "href": None,
                },
            ),
        }
        for row in rows
    ]
