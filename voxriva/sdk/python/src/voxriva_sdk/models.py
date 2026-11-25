from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from .errors import ProtocolError

JsonValue = bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"] | None
Channel = Literal["email", "push"]


class NotificationStatus(str, Enum):
    QUEUED = "queued"
    RETRYING = "retrying"
    PROCESSING = "processing"
    SENT = "sent"
    DELIVERED = "delivered"
    BOUNCED = "bounced"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Accepted:
    id: UUID
    status: NotificationStatus
    environment_id: UUID
    template_version_id: UUID
    provider_revision_id: UUID
    replayed: bool
    status_url: str
    idempotency_key: str
    dashboard_url: str


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    project_id: UUID
    environment_id: UUID
    channel: Channel
    locale: str
    resolved_locale: str
    fallback_used: bool
    template_version_id: UUID
    provider_revision_id: UUID


@dataclass(frozen=True)
class Resolution:
    project_name: str
    environment_name: str
    template_name: str
    template_key: str
    branch_name: str
    template_version: int
    resolved_locale: str
    fallback_used: bool
    provider_name: str
    provider_type: str
    provider_revision: int
    provider_scope: str | None


@dataclass(frozen=True)
class Attempt:
    number: int
    status: str
    error_code: str | None
    error_message: str | None
    retryable: bool
    provider_message_id: str | None
    started_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True)
class ProviderEvent:
    id: UUID
    event: str
    occurred_at: datetime
    received_at: datetime


@dataclass(frozen=True)
class Notification:
    id: UUID
    project_id: UUID
    environment_id: UUID
    template_version_id: UUID
    provider_revision_id: UUID
    channel: Channel
    locale: str
    recipient_mask: str
    status: NotificationStatus
    resolution: Resolution
    error_code: str | None
    error_message: str | None
    attempt_count: int
    next_attempt_at: datetime | None
    expires_at: datetime | None
    replay_of_id: UUID | None
    payload_available: bool
    created_at: datetime
    updated_at: datetime
    attempts: tuple[Attempt, ...]
    provider_events: tuple[ProviderEvent, ...]
    dashboard_url: str


@dataclass(frozen=True)
class Liveness:
    status: Literal["live"]


@dataclass(frozen=True)
class Readiness:
    status: Literal["ready", "unavailable"]
    checks: dict[str, str]


def obj(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError("The API response must be a JSON object.")
    return value


def text(row: dict[str, Any], key: str) -> str:
    value = row[key]
    if not isinstance(value, str):
        raise ValueError("Expected string")
    return value


def optional_text(row: dict[str, Any], key: str) -> str | None:
    return None if row.get(key) is None else text(row, key)


def boolean(row: dict[str, Any], key: str) -> bool:
    value = row[key]
    if not isinstance(value, bool):
        raise ValueError("Expected boolean")
    return value


def integer(row: dict[str, Any], key: str) -> int:
    value = row[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("Expected nonnegative integer")
    return value


def timestamp(row: dict[str, Any], key: str) -> datetime:
    return datetime.fromisoformat(text(row, key).replace("Z", "+00:00"))


def optional_time(row: dict[str, Any], key: str) -> datetime | None:
    return None if row.get(key) is None else timestamp(row, key)


def channel(row: dict[str, Any]) -> Channel:
    value = text(row, "channel")
    if value not in {"email", "push"}:
        raise ValueError("Unexpected channel")
    return "email" if value == "email" else "push"


def parse_accepted(row: dict[str, Any], key: str, dashboard_url: str) -> Accepted:
    return Accepted(UUID(text(row, "id")), NotificationStatus(row["status"]), UUID(text(row, "environment_id")), UUID(text(row, "template_version_id")),
                    UUID(text(row, "provider_revision_id")), boolean(row, "replayed"), text(row, "status_url"), key, dashboard_url)


def parse_validation(row: dict[str, Any]) -> ValidationResult:
    if not boolean(row, "valid"):
        raise ValueError("Unexpected validation result")
    return ValidationResult(True, UUID(text(row, "project_id")), UUID(text(row, "environment_id")), channel(row), text(row, "locale"), text(row, "resolved_locale"),
                            boolean(row, "fallback_used"), UUID(text(row, "template_version_id")), UUID(text(row, "provider_revision_id")))


def parse_notification(row: dict[str, Any], dashboard_url: str) -> Notification:
    resolved = obj(row["resolution"])
    resolution = Resolution(project_name=text(resolved, "project_name"), environment_name=text(resolved, "environment_name"),
                            template_name=text(resolved, "template_name"), template_key=text(resolved, "template_key"), branch_name=text(resolved, "branch_name"),
                            template_version=integer(resolved, "template_version"), resolved_locale=text(resolved, "resolved_locale"), fallback_used=boolean(resolved, "fallback_used"),
                            provider_name=text(resolved, "provider_name"), provider_type=text(resolved, "provider_type"), provider_revision=integer(resolved, "provider_revision"), provider_scope=optional_text(resolved, "provider_scope"))
    if not isinstance(row["attempts"], list) or not isinstance(row.get("provider_events", []), list):
        raise ValueError("Expected history lists")
    attempts = []
    for value in row["attempts"]:
        entry = obj(value)
        attempts.append(Attempt(integer(entry, "number"), text(entry, "status"), optional_text(entry, "error_code"), optional_text(entry, "error_message"),
                                boolean(entry, "retryable"), optional_text(entry, "provider_message_id"), timestamp(entry, "started_at"), optional_time(entry, "finished_at")))
    events = []
    for value in row.get("provider_events", []):
        entry = obj(value)
        events.append(ProviderEvent(UUID(text(entry, "id")), text(entry, "event"), timestamp(entry, "occurred_at"), timestamp(entry, "received_at")))
    return Notification(UUID(text(row, "id")), UUID(text(row, "project_id")), UUID(text(row, "environment_id")), UUID(text(row, "template_version_id")),
                        UUID(text(row, "provider_revision_id")), channel(row), text(row, "locale"), text(row, "recipient_mask"), NotificationStatus(row["status"]), resolution,
                        optional_text(row, "error_code"), optional_text(row, "error_message"), integer(row, "attempt_count"), optional_time(row, "next_attempt_at"), optional_time(row, "expires_at"),
                        UUID(text(row, "replay_of_id")) if row.get("replay_of_id") else None, boolean(row, "payload_available"), timestamp(row, "created_at"), timestamp(row, "updated_at"), tuple(attempts), tuple(events), dashboard_url)
