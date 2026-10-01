"""Tests for the per-host request throttle."""

import asyncio
from typing import List
from unittest.mock import patch

import pytest

from around_the_grounds.utils.host_throttle import HostThrottle


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def sleeps(clock: FakeClock):  # type: ignore[no-untyped-def]
    recorded: List[float] = []

    async def fake_sleep(delay: float) -> None:
        recorded.append(delay)
        clock.now += delay

    with patch("around_the_grounds.utils.host_throttle.asyncio.sleep", fake_sleep):
        yield recorded


@pytest.mark.asyncio
async def test_first_request_does_not_wait(
    clock: FakeClock, sleeps: List[float]
) -> None:
    await HostThrottle(5.0, clock).wait("https://untappd.com/v/a/1")
    assert sleeps == []


@pytest.mark.asyncio
async def test_same_host_waits_out_the_interval(
    clock: FakeClock, sleeps: List[float]
) -> None:
    throttle = HostThrottle(5.0, clock)
    await throttle.wait("https://untappd.com/v/a/1")
    clock.now += 2.0
    await throttle.wait("https://UNTAPPD.com/v/b/2")
    assert sleeps == [pytest.approx(3.0)]


@pytest.mark.asyncio
async def test_other_hosts_are_independent(
    clock: FakeClock, sleeps: List[float]
) -> None:
    throttle = HostThrottle(5.0, clock)
    await throttle.wait("https://untappd.com/v/a/1")
    await throttle.wait("https://docs.google.com/spreadsheets/d/x")
    assert sleeps == []


@pytest.mark.asyncio
async def test_concurrent_requests_are_serialized(
    clock: FakeClock, sleeps: List[float]
) -> None:
    throttle = HostThrottle(5.0, clock)
    await asyncio.gather(
        *(throttle.wait(f"https://untappd.com/v/{i}") for i in range(3))
    )
    assert sleeps == [pytest.approx(5.0), pytest.approx(5.0)]


@pytest.mark.asyncio
async def test_zero_interval_never_waits(clock: FakeClock, sleeps: List[float]) -> None:
    throttle = HostThrottle(0, clock)
    for _ in range(3):
        await throttle.wait("https://untappd.com/")
    assert sleeps == []
