from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.infrastructure.database import Base, utcnow


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("environment_id", "idempotency_key"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), index=True
    )
    environment_id: Mapped[UUID] = mapped_column(
        ForeignKey("environments.id", ondelete="RESTRICT"), index=True
    )
    delivery_key_id: Mapped[UUID] = mapped_column(
        ForeignKey("delivery_keys.id", ondelete="RESTRICT")
    )
    template_id: Mapped[UUID] = mapped_column(
        ForeignKey("templates.id", ondelete="RESTRICT")
    )
    template_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("template_versions.id", ondelete="RESTRICT")
    )
    provider_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_revisions.id", ondelete="RESTRICT")
    )
    channel: Mapped[str] = mapped_column(String(16))
    locale: Mapped[str] = mapped_column(String(35))
    attempt_count: Mapped[int] = mapped_column(default=0)
    lease_token: Mapped[UUID | None]
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    send_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replay_of_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("notifications.id", ondelete="RESTRICT")
    )
    initiated_by: Mapped[UUID | None]
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    recipient_mask: Mapped[str] = mapped_column(String(30))
    encrypted_recipient: Mapped[str | None]
    encrypted_payload: Mapped[str | None]
    resolution: Mapped[dict[str, object]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), index=True)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"
    __table_args__ = (
        Index("ix_notification_outbox_pending", "published_at", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    notification_id: Mapped[UUID] = mapped_column(
        ForeignKey("notifications.id", ondelete="CASCADE"), unique=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class NotificationAttempt(Base):
    __tablename__ = "notification_attempts"
    __table_args__ = (UniqueConstraint("notification_id", "number"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    notification_id: Mapped[UUID] = mapped_column(
        ForeignKey("notifications.id", ondelete="RESTRICT"), index=True
    )
    number: Mapped[int]
    status: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(64))
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    node: Mapped[str] = mapped_column(String(200), primary_key=True)
    state: Mapped[str] = mapped_column(String(16))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class WorkerEvent(Base):
    __tablename__ = "worker_events"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    node: Mapped[str] = mapped_column(String(200))
    event: Mapped[str] = mapped_column(String(32))
    notification_id: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
