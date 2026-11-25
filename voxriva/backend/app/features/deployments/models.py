from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.infrastructure.database import Base, utcnow


class TemplateDeployment(Base):
    __tablename__ = "template_deployments"
    __table_args__ = (UniqueConstraint("template_id", "scope_key", "locale"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    template_id: Mapped[UUID] = mapped_column(
        ForeignKey("templates.id", ondelete="CASCADE"), index=True
    )
    scope_key: Mapped[str] = mapped_column(String(60))
    scope: Mapped[str] = mapped_column(String(16))
    project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    environment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("environments.id", ondelete="CASCADE")
    )
    locale: Mapped[str] = mapped_column(String(35))
    version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("template_versions.id", ondelete="RESTRICT")
    )
    generation: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class DeploymentEvent(Base):
    __tablename__ = "template_deployment_events"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    template_id: Mapped[UUID] = mapped_column(
        ForeignKey("templates.id", ondelete="RESTRICT"), index=True
    )
    scope_key: Mapped[str] = mapped_column(String(60))
    project_id: Mapped[UUID | None] = mapped_column(index=True)
    locale: Mapped[str] = mapped_column(String(35))
    from_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("template_versions.id", ondelete="RESTRICT")
    )
    to_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("template_versions.id", ondelete="RESTRICT")
    )
    action: Mapped[str] = mapped_column(String(16))
    generation: Mapped[int]
    actor_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
