"""Retry scheduling rules are deterministic when the jitter source is supplied."""

from unittest.mock import Mock

import pytest

from backend.app.features.notifications.policy import retry_delay
from backend.app.infrastructure.settings import Settings


@pytest.fixture
def retry_settings():
    return Settings(delivery_retry_base_seconds=10, delivery_retry_max_seconds=35)


@pytest.mark.parametrize(
    "attempt,expected_bounds",
    [(1, (5, 10)), (2, (10, 20)), (3, (17.5, 35)), (10, (17.5, 35))],
)
def test_exponential_backoff_caps_before_jitter(
    retry_settings, attempt, expected_bounds
):
    jitter = Mock(side_effect=lambda lower, upper: (lower + upper) / 2)
    delay = retry_delay(retry_settings, attempt, None, jitter=jitter)
    jitter.assert_called_once_with(*expected_bounds)
    assert delay == sum(expected_bounds) / 2


@pytest.mark.parametrize("fraction", [0, 0.5, 1])
def test_jitter_can_choose_the_whole_bounded_window(retry_settings, fraction):
    def jitter(lower, upper):
        return lower + fraction * (upper - lower)

    assert retry_delay(retry_settings, 2, None, jitter=jitter) == 10 + fraction * 10


@pytest.mark.parametrize(
    "retry_after,expected",
    [
        (-100, 5),
        (0, 5),
        (2, 5),
        (12.5, 12.5),
        (3600, 3600),
        (7200, 3600),
        (float("nan"), 5),
        (float("inf"), 5),
        (float("-inf"), 5),
    ],
)
def test_provider_retry_after_is_finite_bounded_and_never_shortens_backoff(
    retry_settings, retry_after, expected
):
    assert (
        retry_delay(retry_settings, 1, retry_after, jitter=lambda lower, upper: lower)
        == expected
    )
