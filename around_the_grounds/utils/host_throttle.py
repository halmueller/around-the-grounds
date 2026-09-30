"""Space out requests to the same host.

Several venues can share one upstream host (every Untappd venue page lives on
untappd.com, every published sheet on docs.google.com), and the coordinator
scrapes venues concurrently. Parsers for shared hosts wait on this throttle so
that host sees at most one request per interval from this process.
"""

import asyncio
import time
from typing import Callable, Dict
from urllib.parse import urlparse

DEFAULT_MIN_INTERVAL = 5.0


class HostThrottle:
    def __init__(
        self,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.min_interval = min_interval
        self._clock = clock
        self._locks: Dict[str, asyncio.Lock] = {}
        self._last: Dict[str, float] = {}

    async def wait(self, url: str) -> None:
        """Return once a request to *url*'s host is allowed, and claim it."""
        host = urlparse(url).netloc.lower()
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            last = self._last.get(host)
            if last is not None:
                delay = last + self.min_interval - self._clock()
                if delay > 0:
                    await asyncio.sleep(delay)
            self._last[host] = self._clock()


# Shared by all listing parsers in this process.
listing_throttle = HostThrottle()
