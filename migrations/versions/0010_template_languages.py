"""Keep a template's primary editing language independent of its delivery fallback."""
import sqlalchemy as sa
from alembic import op

revision = "0010_template_languages"
down_revision = "0009_cloud_providers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("templates", sa.Column("primary_locale", sa.String(35), nullable=False, server_default="en"))


def downgrade() -> None:
    op.drop_column("templates", "primary_locale")
