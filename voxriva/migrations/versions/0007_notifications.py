"""Pinned notification requests, transactional outbox, and delivery attempts."""
import sqlalchemy as sa
from alembic import op

revision = "0007_notifications"
down_revision = "0006_providers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("notifications", sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("environment_id", sa.Uuid(), sa.ForeignKey("environments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("delivery_key_id", sa.Uuid(), sa.ForeignKey("delivery_keys.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("template_id", sa.Uuid(), sa.ForeignKey("templates.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("template_version_id", sa.Uuid(), sa.ForeignKey("template_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("provider_revision_id", sa.Uuid(), sa.ForeignKey("provider_revisions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False), sa.Column("locale", sa.String(35), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False), sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("recipient_mask", sa.String(30), nullable=False), sa.Column("encrypted_payload", sa.Text()),
        sa.Column("resolution", sa.JSON(), nullable=False), sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(64)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("environment_id", "idempotency_key"))
    for column in ["project_id", "environment_id", "status", "created_at"]:
        op.create_index(f"ix_notifications_{column}", "notifications", [column])
    op.create_table("notification_outbox", sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("notification_id", sa.Uuid(), sa.ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("published_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_notification_outbox_pending", "notification_outbox", ["published_at", "created_at"])
    op.create_table("notification_attempts", sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("notification_id", sa.Uuid(), sa.ForeignKey("notifications.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False), sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(64)), sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("provider_message_id", sa.String(200)), sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)), sa.UniqueConstraint("notification_id", "number"))
    op.create_index("ix_notification_attempts_notification_id", "notification_attempts", ["notification_id"])


def downgrade() -> None:
    op.drop_table("notification_attempts")
    op.drop_table("notification_outbox")
    op.drop_table("notifications")
