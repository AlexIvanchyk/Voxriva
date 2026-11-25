"""Verified delivery event inbox for cloud providers."""
import sqlalchemy as sa
from alembic import op

revision = "0009_cloud_providers"
down_revision = "0008_delivery_recovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("provider_events", sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("configuration_id", sa.Uuid(), sa.ForeignKey("provider_configurations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False), sa.Column("topic_arn", sa.String(256), nullable=False),
        sa.Column("provider_message_id", sa.String(200), nullable=False), sa.Column("event", sa.String(24), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notification_id", sa.Uuid(), sa.ForeignKey("notifications.id", ondelete="RESTRICT")), sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("configuration_id", "external_id"))
    for name in ["configuration_id", "provider_message_id", "notification_id", "applied_at"]:
        op.create_index("ix_provider_events_"+name, "provider_events", [name])


def downgrade() -> None:
    op.drop_table("provider_events")
