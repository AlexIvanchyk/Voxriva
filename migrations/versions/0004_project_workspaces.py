"""Replace organizations with projects and a shared template library, preserving configuration."""
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from alembic import op

revision = "0004_project_workspaces"
down_revision = "0003_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    names = ["accounts", "dashboard_sessions", "organizations", "projects", "environments", "memberships", "delivery_keys", "templates"]
    # This milestone has configuration/session tables only. Snapshot before replacing FK roots.
    old = {name: [dict(row) for row in bind.execute(sa.select(sa.Table(name, metadata, autoload_with=bind))).mappings()] for name in names}
    now = datetime.now(UTC)

    def uid(value: Any) -> UUID:
        return value if isinstance(value, UUID) else UUID(str(value))

    for rows in old.values():
        for row in rows:
            for key in ["id", "account_id", "organization_id", "project_id", "environment_id"]:
                if key in row and row[key] is not None:
                    row[key] = uid(row[key])
    project_map: dict[UUID, list[UUID]] = {}
    used_names = set()
    for row in old["projects"]:
        project_map.setdefault(row["organization_id"], []).append(row["id"])
        candidate = row["name"]
        if candidate in used_names:
            candidate = f"{candidate[:85]} · {row['id'].hex[:10]}"
        used_names.add(candidate)
        row["name"] = candidate
    occupied = {row["organization_id"] for row in [*old["templates"], *old["memberships"]]}
    for org in old["organizations"]:
        if org["id"] not in project_map and org["id"] in occupied:
            candidate = org["name"]
            if candidate in used_names:
                candidate = f"{candidate[:85]} · {org['id'].hex[:10]}"
            used_names.add(candidate)
            identifier = uuid4()
            old["projects"].append({"id": identifier, "name": candidate, "organization_id": org["id"]})
            project_map[org["id"]] = [identifier]

    for name in ["dashboard_sessions", "delivery_keys", "environments", "memberships", "templates", "projects", "accounts", "organizations"]:
        op.drop_table(name)
    op.create_table("accounts", sa.Column("id", sa.Uuid(), primary_key=True),
                    sa.Column("email", sa.String(254), nullable=False, unique=True),
                    sa.Column("password_hash", sa.String(200), nullable=False),
                    sa.Column("platform_admin", sa.Boolean(), nullable=False),
                    sa.Column("display_name", sa.String(100), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("dashboard_sessions", sa.Column("token_hash", sa.String(64), primary_key=True),
                    sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_dashboard_sessions_account_id", "dashboard_sessions", ["account_id"])
    op.create_index("ix_dashboard_sessions_expires_at", "dashboard_sessions", ["expires_at"])
    op.create_table("projects", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("name", sa.String(100), nullable=False, unique=True))
    op.create_table("environments", sa.Column("id", sa.Uuid(), primary_key=True),
                    sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("name", sa.String(100), nullable=False), sa.UniqueConstraint("project_id", "name"))
    op.create_table("memberships", sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
                    sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True),
                    sa.Column("role", sa.String(24), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_memberships_account_id", "memberships", ["account_id"])
    op.create_table("delivery_keys", sa.Column("id", sa.Uuid(), primary_key=True),
                    sa.Column("environment_id", sa.Uuid(), sa.ForeignKey("environments.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("name", sa.String(100), nullable=False), sa.Column("prefix", sa.String(16), nullable=False),
                    sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                    sa.Column("expires_at", sa.DateTime(timezone=True)), sa.Column("revoked_at", sa.DateTime(timezone=True)))
    op.create_index("ix_delivery_keys_environment_id", "delivery_keys", ["environment_id"])
    op.create_table("templates", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("key", sa.String(100), nullable=False, unique=True),
                    sa.Column("name", sa.String(100), nullable=False), sa.Column("channel", sa.String(10), nullable=False),
                    sa.Column("draft", sa.JSON(), nullable=False), sa.Column("draft_revision", sa.Integer(), nullable=False),
                    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
                    sa.CheckConstraint("channel IN ('email', 'push')", name="template_channel"))
    op.create_table("template_projects", sa.Column("template_id", sa.Uuid(), sa.ForeignKey("templates.id", ondelete="CASCADE"), primary_key=True),
                    sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True))
    op.create_index("ix_template_projects_project_id", "template_projects", ["project_id"])
    fresh = sa.MetaData()

    def insert(name: str, rows: list[dict[str, Any]]) -> None:
        if rows:
            table = sa.Table(name, fresh, autoload_with=bind)
            for column in table.c:
                if any(isinstance(row.get(column.name), UUID) for row in rows):
                    column.type = sa.Uuid()
            bind.execute(table.insert(), rows)

    insert("accounts", [{**row, "display_name": "", "created_at": now} for row in old["accounts"]])
    insert("dashboard_sessions", old["dashboard_sessions"])
    insert("projects", [{"id": row["id"], "name": row["name"]} for row in old["projects"]])
    insert("environments", old["environments"])
    insert("delivery_keys", old["delivery_keys"])
    insert("memberships", [{"project_id": project_id, "account_id": row["account_id"],
                            "role": "project_admin" if row["role"] == "org_admin" else row["role"], "created_at": now}
                           for row in old["memberships"] for project_id in project_map[row["organization_id"]]])
    bindings: list[dict[str, Any]] = []
    used_keys = set()
    templates = []
    for row in old["templates"]:
        org_id = row.pop("organization_id")
        if row["key"] in used_keys:
            row["key"] = f"{row['key'][:87]}-{row['id'].hex[:12]}"
        used_keys.add(row["key"])
        templates.append(row)
        bindings.extend({"template_id": row["id"], "project_id": identifier} for identifier in project_map[org_id])
    insert("templates", templates)
    insert("template_projects", bindings)
    op.add_column("audit_events", sa.Column("project_id", sa.Uuid(), nullable=True))
    op.add_column("audit_events", sa.Column("legacy_scope", sa.JSON(), nullable=True))
    audit = sa.Table("audit_events", sa.MetaData(), autoload_with=bind)
    org_names = {org["id"]: org["name"] for org in old["organizations"]}
    for identifier, name in org_names.items():
        # Reflected SQLite UUID columns are strings; explicit UUID typing keeps both dialects consistent.
        typed_id = sa.bindparam("legacy_id", type_=sa.Uuid())
        bind.execute(audit.update().where(audit.c.organization_id == typed_id).values(
            legacy_scope={"organization_id": str(identifier), "organization_name": name},
        ), {"legacy_id": identifier})
    op.drop_index("ix_audit_events_organization_id", table_name="audit_events")
    op.drop_column("audit_events", "organization_id")
    op.create_index("ix_audit_events_project_id", "audit_events", ["project_id"])


def downgrade() -> None:
    raise RuntimeError("Restore the pre-migration database backup to recover the former organization structure")
