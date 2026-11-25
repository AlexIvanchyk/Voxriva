"""Retain encrypted email recipients independently of disposable runtime payloads."""
import sqlalchemy as sa
from alembic import op

revision = "0011_notification_recipients"
down_revision = "0010_template_languages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("encrypted_recipient", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("notifications", "encrypted_recipient")
