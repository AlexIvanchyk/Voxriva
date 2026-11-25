"""Optional account TOTP MFA. Existing accounts and sessions are preserved."""

import sqlalchemy as sa
from alembic import op

revision = "0013_account_mfa"
down_revision = "0012_management_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_mfa",
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("secret", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("setup_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_step", sa.Integer(), nullable=False),
        sa.Column("recovery_hashes", sa.JSON(), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "mfa_challenges",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_mfa_challenges_account_id", "mfa_challenges", ["account_id"])


def downgrade() -> None:
    op.drop_table("mfa_challenges")
    op.drop_table("account_mfa")
