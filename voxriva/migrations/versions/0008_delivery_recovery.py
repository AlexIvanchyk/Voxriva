"""Fenced claims, retry schedules, payload retention and sanitized worker telemetry."""

from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0008_delivery_recovery"
down_revision = "0007_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns: list[sa.Column[Any]] = [
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_token", sa.Uuid()),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("send_started_at", sa.DateTime(timezone=True)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("replay_of_id", sa.Uuid()),
        sa.Column("initiated_by", sa.Uuid()),
    ]
    for column in columns:
        op.add_column("notifications", column)
    with op.batch_alter_table("notifications") as batch:
        batch.create_foreign_key(
            "fk_notification_replay",
            "notifications",
            ["replay_of_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index(
        "ix_notifications_lease_expires_at", "notifications", ["lease_expires_at"]
    )
    op.execute(
        "UPDATE notifications SET attempt_count=(SELECT count(*) FROM notification_attempts WHERE notification_attempts.notification_id=notifications.id)"
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "UPDATE notifications SET expires_at=created_at + INTERVAL '24 hours', next_attempt_at=created_at"
        )
        # Existing processing rows have no reliable send phase; recover conservatively.
        op.execute(
            "UPDATE notifications SET lease_expires_at=now(),send_started_at=updated_at WHERE status='processing'"
        )
    else:
        op.execute(
            "UPDATE notifications SET expires_at=datetime(created_at,'+1 day'),next_attempt_at=created_at"
        )
        op.execute(
            "UPDATE notifications SET lease_expires_at=CURRENT_TIMESTAMP,send_started_at=updated_at WHERE status='processing'"
        )
    op.create_table(
        "worker_heartbeats",
        sa.Column("node", sa.String(200), primary_key=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_worker_heartbeats_last_seen", "worker_heartbeats", ["last_seen"]
    )
    op.create_table(
        "worker_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("node", sa.String(200), nullable=False),
        sa.Column("event", sa.String(32), nullable=False),
        sa.Column("notification_id", sa.Uuid()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_worker_events_created_at", "worker_events", ["created_at"])


def downgrade() -> None:
    raise RuntimeError(
        "Restore the pre-upgrade backup to remove delivery recovery state"
    )
