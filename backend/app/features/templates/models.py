from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.infrastructure.database import Base, utcnow


class Template(Base):
    __tablename__ = "templates"
    __table_args__ = (
        CheckConstraint("channel IN ('email', 'push')", name="template_channel"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    key: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    channel: Mapped[str] = mapped_column(String(10))
    is_layout: Mapped[bool] = mapped_column(default=False, server_default=false())
    primary_locale: Mapped[str] = mapped_column(String(35), default="en")
    fallback_locale: Mapped[str] = mapped_column(String(35), default="en")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class TemplateProject(Base):
    __tablename__ = "template_projects"
    template_id: Mapped[UUID] = mapped_column(
        ForeignKey("templates.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class TemplateBranch(Base):
    __tablename__ = "template_branches"
    __table_args__ = (UniqueConstraint("template_id", "name", "locale"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    template_id: Mapped[UUID] = mapped_column(
        ForeignKey("templates.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    locale: Mapped[str] = mapped_column(String(35))
    draft: Mapped[dict[str, object]] = mapped_column(JSON)
    draft_revision: Mapped[int] = mapped_column(default=1)
    source_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "template_versions.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_branch_source_version",
        )
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class TemplateVersion(Base):
    __tablename__ = "template_versions"
    __table_args__ = (UniqueConstraint("branch_id", "number"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    template_id: Mapped[UUID] = mapped_column(
        ForeignKey("templates.id", ondelete="RESTRICT"), index=True
    )
    branch_id: Mapped[UUID] = mapped_column(
        ForeignKey("template_branches.id", ondelete="RESTRICT"), index=True
    )
    number: Mapped[int]
    locale: Mapped[str] = mapped_column(String(35))
    content: Mapped[dict[str, object]] = mapped_column(JSON)
    draft_revision: Mapped[int]
    parent_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("template_versions.id", ondelete="RESTRICT")
    )
    message: Mapped[str] = mapped_column(String(500), default="")
    actor_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
