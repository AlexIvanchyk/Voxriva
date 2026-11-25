"""Organization templates and mutable draft content."""
import sqlalchemy as sa
from alembic import op

revision = "0003_templates"
down_revision = "0002_dashboard_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "templates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("draft", sa.JSON(), nullable=False),
        sa.Column("draft_revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "key"),
        sa.CheckConstraint("channel IN ('email', 'push')", name="template_channel"),
    )
    op.create_index("ix_templates_organization_id", "templates", ["organization_id"])


def downgrade() -> None:
    op.drop_table("templates")
