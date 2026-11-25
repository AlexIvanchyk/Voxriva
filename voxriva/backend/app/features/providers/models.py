from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.infrastructure.database import Base, utcnow


class ProviderConfiguration(Base):
    __tablename__ = "provider_configurations"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100))
    provider_type: Mapped[str] = mapped_column(String(64))
    project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), index=True
    )
    revision: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class ProviderRevision(Base):
    __tablename__ = "provider_revisions"
    __table_args__ = (UniqueConstraint("configuration_id", "number"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    configuration_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_configurations.id", ondelete="RESTRICT"), index=True
    )
    number: Mapped[int]
    public_config: Mapped[dict[str, object]] = mapped_column(JSON)
    encrypted_secrets: Mapped[str]
    actor_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class ProviderBinding(Base):
    __tablename__ = "provider_bindings"
    __table_args__ = (UniqueConstraint("scope_key", "channel"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    scope_key: Mapped[str] = mapped_column(String(60))
    scope: Mapped[str] = mapped_column(String(16))
    project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    environment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("environments.id", ondelete="CASCADE")
    )
    channel: Mapped[str] = mapped_column(String(16))
    revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_revisions.id", ondelete="RESTRICT")
    )
    generation: Mapped[int]
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class ProviderEvent(Base):
    """Verified, normalized events only; never store a raw SNS/SES payload."""

    __tablename__ = "provider_events"
    __table_args__ = (UniqueConstraint("configuration_id", "external_id"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    configuration_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_configurations.id", ondelete="RESTRICT"), index=True
    )
    external_id: Mapped[str] = mapped_column(String(200))
    topic_arn: Mapped[str] = mapped_column(String(256))
    provider_message_id: Mapped[str] = mapped_column(String(200), index=True)
    event: Mapped[str] = mapped_column(String(24))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    notification_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("notifications.id", ondelete="RESTRICT"), index=True
    )
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
