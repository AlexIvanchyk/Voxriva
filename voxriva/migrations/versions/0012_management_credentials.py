"""Scoped, expiring, revocable authoring credentials separate from delivery keys."""

import sqlalchemy as sa
from alembic import op

revision = "0012_management_credentials"
down_revision = "0011_notification_recipients"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "management_credentials",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("project_ids", sa.JSON(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_management_credentials_account_id", "management_credentials", ["account_id"]
    )


def downgrade() -> None:
    op.drop_table("management_credentials")
