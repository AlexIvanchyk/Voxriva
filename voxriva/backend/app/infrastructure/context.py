"""Application resources passed explicitly to workflows, independent of HTTP."""

import asyncio
from collections import deque
from dataclasses import dataclass
from uuid import UUID

from backend.app.infrastructure.settings import Settings
from backend.app.shared.provider_contract import BaseProvider


@dataclass(frozen=True)
class ApplicationContext:
    password_slots: asyncio.Semaphore
    settings: Settings
    provider_registry: dict[str, type[BaseProvider]]
    preview_slots: asyncio.Semaphore
    preview_limits: dict[UUID, deque[float]]
    provider_slots: asyncio.Semaphore
    provider_limits: dict[UUID, deque[float]]
