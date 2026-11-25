from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, cast

from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from backend.app.infrastructure.settings import Settings

DependencyStatus = Literal["ready", "unavailable", "unconfigured"]


class Readiness(BaseModel):
    status: Literal["ready", "unavailable"]
    checks: dict[str, DependencyStatus]


@dataclass
class Dependencies:
    database: AsyncEngine | None = None
    redis: Redis | None = None
    timeout: float = 2

    @classmethod
    def from_settings(cls, settings: Settings) -> Dependencies:
        return cls(
            database=create_async_engine(
                settings.database_url, pool_pre_ping=True, hide_parameters=True
            )
            if settings.database_url
            else None,
            redis=Redis.from_url(settings.redis_url) if settings.redis_url else None,
            timeout=settings.dependency_timeout,
        )

    async def close(self) -> None:
        if self.database is not None:
            await self.database.dispose()
        if self.redis is not None:
            await self.redis.aclose()

    async def _check(self, probe: Callable[[], Awaitable[None]]) -> DependencyStatus:
        try:
            async with asyncio.timeout(self.timeout):
                await probe()
        except (TimeoutError, OSError, SQLAlchemyError, RedisError):
            return "unavailable"
        return "ready"

    async def database_status(self) -> DependencyStatus:
        if self.database is None:
            return "unconfigured"
        engine = self.database

        async def probe() -> None:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))

        return await self._check(probe)

    async def redis_status(self) -> DependencyStatus:
        if self.redis is None:
            return "unconfigured"
        redis = self.redis

        async def probe() -> None:
            if not await cast(Awaitable[bool], redis.ping()):
                raise RedisError("Redis did not acknowledge the probe")

        return await self._check(probe)

    async def readiness(self) -> Readiness:
        postgres, redis = await asyncio.gather(
            self.database_status(), self.redis_status()
        )
        checks: dict[str, DependencyStatus] = {
            "api": "ready",
            "postgres": postgres,
            "redis": redis,
        }
        status: Literal["ready", "unavailable"] = (
            "ready" if postgres == redis == "ready" else "unavailable"
        )
        return Readiness(status=status, checks=checks)
