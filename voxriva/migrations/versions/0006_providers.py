"""Versioned provider configuration and pinned scope bindings."""
import sqlalchemy as sa
from alembic import op

revision = "0006_providers"
down_revision = "0005_template_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("provider_configurations", sa.Column("id", sa.Uuid(), primary_key=True),
                    sa.Column("name", sa.String(100), nullable=False), sa.Column("provider_type", sa.String(64), nullable=False),
                    sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="RESTRICT")),
                    sa.Column("revision", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_provider_configurations_project_id", "provider_configurations", ["project_id"])
    op.create_table("provider_revisions", sa.Column("id", sa.Uuid(), primary_key=True),
                    sa.Column("configuration_id", sa.Uuid(), sa.ForeignKey("provider_configurations.id", ondelete="RESTRICT"), nullable=False),
                    sa.Column("number", sa.Integer(), nullable=False), sa.Column("public_config", sa.JSON(), nullable=False),
                    sa.Column("encrypted_secrets", sa.Text(), nullable=False), sa.Column("actor_id", sa.Uuid(), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("configuration_id", "number"))
    op.create_index("ix_provider_revisions_configuration_id", "provider_revisions", ["configuration_id"])
    op.create_table("provider_bindings", sa.Column("id", sa.Uuid(), primary_key=True),
                    sa.Column("scope_key", sa.String(60), nullable=False), sa.Column("scope", sa.String(16), nullable=False),
                    sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE")),
                    sa.Column("environment_id", sa.Uuid(), sa.ForeignKey("environments.id", ondelete="CASCADE")),
                    sa.Column("channel", sa.String(16), nullable=False), sa.Column("revision_id", sa.Uuid(), sa.ForeignKey("provider_revisions.id", ondelete="RESTRICT"), nullable=False),
                    sa.Column("generation", sa.Integer(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
                    sa.UniqueConstraint("scope_key", "channel"))
    op.create_index("ix_provider_bindings_project_id", "provider_bindings", ["project_id"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""CREATE TRIGGER immutable_provider_revisions BEFORE UPDATE OR DELETE ON provider_revisions
                   FOR EACH ROW EXECUTE FUNCTION voxriva_reject_immutable_change()""")
    elif op.get_bind().dialect.name == "sqlite":
        for action in ["UPDATE", "DELETE"]:
            op.execute(f"CREATE TRIGGER immutable_provider_revisions_{action.lower()} BEFORE {action} ON provider_revisions BEGIN SELECT RAISE(ABORT, 'Provider revisions are immutable'); END")


def downgrade() -> None:
    op.drop_table("provider_bindings")
    op.drop_table("provider_revisions")
    op.drop_table("provider_configurations")
