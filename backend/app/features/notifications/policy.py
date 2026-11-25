"""Deterministic retry scheduling with injectable jitter for isolated policy tests."""

import math
import random
from collections.abc import Callable

from backend.app.infrastructure.settings import Settings


def retry_delay(
    config: Settings,
    attempt_count: int,
    retry_after: float | None,
    *,
    jitter: Callable[[float, float], float] = random.uniform,
) -> float:
    delay = min(
        config.delivery_retry_max_seconds,
        config.delivery_retry_base_seconds * 2 ** (attempt_count - 1),
    )
    scheduled = jitter(delay / 2, delay)
    if retry_after is not None and math.isfinite(retry_after):
        scheduled = max(scheduled, min(3600, max(0, retry_after)))
    return scheduled
