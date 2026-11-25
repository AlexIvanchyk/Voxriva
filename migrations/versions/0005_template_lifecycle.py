"""Branch drafts, immutable versions, and explicit deployment pointers."""
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0005_template_lifecycle"
down_revision = "0004_project_workspaces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.add_column("templates", sa.Column("fallback_locale", sa.String(35), nullable=False, server_default="en"))
    op.create_table("template_branches", sa.Column("id", sa.Uuid(), primary_key=True),
                    sa.Column("template_id", sa.Uuid(), sa.ForeignKey("templates.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("name", sa.String(64), nullable=False), sa.Column("locale", sa.String(35), nullable=False),
                    sa.Column("draft", sa.JSON(), nullable=False), sa.Column("draft_revision", sa.Integer(), nullable=False),
                    sa.Column("source_version_id", sa.Uuid(), nullable=True), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
                    sa.UniqueConstraint("template_id", "name", "locale"))
    op.create_index("ix_template_branches_template_id", "template_branches", ["template_id"])
    op.create_table("template_versions", sa.Column("id", sa.Uuid(), primary_key=True),
                    sa.Column("template_id", sa.Uuid(), sa.ForeignKey("templates.id", ondelete="RESTRICT"), nullable=False),
                    sa.Column("branch_id", sa.Uuid(), sa.ForeignKey("template_branches.id", ondelete="RESTRICT"), nullable=False),
                    sa.Column("number", sa.Integer(), nullable=False), sa.Column("locale", sa.String(35), nullable=False),
                    sa.Column("content", sa.JSON(), nullable=False), sa.Column("draft_revision", sa.Integer(), nullable=False),
                    sa.Column("parent_version_id", sa.Uuid(), sa.ForeignKey("template_versions.id", ondelete="RESTRICT")),
                    sa.Column("message", sa.String(500), nullable=False), sa.Column("actor_id", sa.Uuid(), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("branch_id", "number"))
    op.create_index("ix_template_versions_template_id", "template_versions", ["template_id"])
    op.create_index("ix_template_versions_branch_id", "template_versions", ["branch_id"])
    with op.batch_alter_table("template_branches") as batch:
        batch.create_foreign_key("fk_branch_source_version", "template_versions", ["source_version_id"], ["id"], ondelete="RESTRICT")
    op.create_table("template_deployments", sa.Column("id", sa.Uuid(), primary_key=True),
                    sa.Column("template_id", sa.Uuid(), sa.ForeignKey("templates.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("scope_key", sa.String(60), nullable=False), sa.Column("scope", sa.String(16), nullable=False),
                    sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE")),
                    sa.Column("environment_id", sa.Uuid(), sa.ForeignKey("environments.id", ondelete="CASCADE")),
                    sa.Column("locale", sa.String(35), nullable=False), sa.Column("version_id", sa.Uuid(), sa.ForeignKey("template_versions.id", ondelete="RESTRICT")),
                    sa.Column("generation", sa.Integer(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
                    sa.UniqueConstraint("template_id", "scope_key", "locale"))
    op.create_index("ix_template_deployments_template_id", "template_deployments", ["template_id"])
    op.create_index("ix_template_deployments_project_id", "template_deployments", ["project_id"])
    op.create_table("template_deployment_events", sa.Column("id", sa.Uuid(), primary_key=True),
                    sa.Column("template_id", sa.Uuid(), sa.ForeignKey("templates.id", ondelete="RESTRICT"), nullable=False),
                    sa.Column("scope_key", sa.String(60), nullable=False), sa.Column("project_id", sa.Uuid()), sa.Column("locale", sa.String(35), nullable=False),
                    sa.Column("from_version_id", sa.Uuid(), sa.ForeignKey("template_versions.id", ondelete="RESTRICT")),
                    sa.Column("to_version_id", sa.Uuid(), sa.ForeignKey("template_versions.id", ondelete="RESTRICT")),
                    sa.Column("action", sa.String(16), nullable=False), sa.Column("generation", sa.Integer(), nullable=False),
                    sa.Column("actor_id", sa.Uuid(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_template_deployment_events_template_id", "template_deployment_events", ["template_id"])
    op.create_index("ix_template_deployment_events_project_id", "template_deployment_events", ["project_id"])
    templates = sa.Table("templates", sa.MetaData(), autoload_with=bind)
    branches = sa.Table("template_branches", sa.MetaData(), autoload_with=bind)
    # Reflected SQLite UUIDs are strings; preserve the existing representation when copying.
    for row in bind.execute(sa.select(templates)).mappings():
        identifier = uuid4() if bind.dialect.name == "postgresql" else uuid4().hex
        bind.execute(branches.insert().values(id=identifier, template_id=row["id"], name="main", locale="en",
                                             draft=row["draft"], draft_revision=row["draft_revision"], source_version_id=None, updated_at=row["updated_at"]))
    op.drop_column("templates", "draft")
    op.drop_column("templates", "draft_revision")
    for table in ["template_versions", "template_deployment_events"]:
        if bind.dialect.name == "postgresql":
            op.execute("""CREATE OR REPLACE FUNCTION voxriva_reject_immutable_change() RETURNS trigger AS $$
                BEGIN RAISE EXCEPTION 'Published versions and deployment events are immutable'; END;
                $$ LANGUAGE plpgsql""")
            op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION voxriva_reject_immutable_change()")
        else:
            for action in ["UPDATE", "DELETE"]:
                op.execute(f"CREATE TRIGGER immutable_{table}_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'Immutable lifecycle record'); END")


def downgrade() -> None:
    raise RuntimeError("Restore the pre-lifecycle backup to remove published version history safely")
