"""Email layouts and the immutable layout version chosen at acceptance."""

import sqlalchemy as sa
from alembic import op

revision = "0014_email_layouts"
down_revision = "0013_account_mfa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "templates",
        sa.Column("is_layout", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            "ALTER TABLE notifications ADD COLUMN layout_version_id CHAR(32) REFERENCES template_versions(id) ON DELETE RESTRICT"
        )
        return
    op.add_column(
        "notifications",
        sa.Column(
            "layout_version_id",
            sa.Uuid(),
            sa.ForeignKey("template_versions.id", ondelete="RESTRICT"),
        ),
    )


def downgrade() -> None:
    op.drop_column("notifications", "layout_version_id")
    op.drop_column("templates", "is_layout")
