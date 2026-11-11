"""Admission control for drawings: a memory budget and a download cap per process (Bulkhead).

Measured in the staging stress test (2026-11-10): with no limit, 100-200 concurrent cold requests
kept their files in memory at once (200 ephys files of staging are 1.7 GB, the largest 77 MB) and
the 2 GiB container was killed for memory, in the old service and the new one. A drawing now waits
for its turn before it downloads:

- **memory**: it reserves ``MEMORY_FACTOR`` times its file size (known from the asset's metadata,
  before the download) from the process budget, and gives it back when done. Small files go
  through in parallel; a large one waits until enough is free. A file larger than the whole budget
  runs alone, so nothing waits forever.
- **downloads**: at most ``downloads`` files are fetched at once, which also bounds the
  connections to entitycore and the storage.

Waiting is first come, first served (asyncio's Condition wakes waiters in order).
"""

import asyncio
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from app.timing import record

# File + parsed data + the figure: the bytes a drawing holds at its peak, per byte of file.
# ponytail: one factor for every type; measure per renderer if the budget is too tight or loose.
MEMORY_FACTOR = 3


class Admission:
    """The process's drawing budget.

    Examples:
        >>> async def demo() -> tuple[int, int]:
        ...     admission = Admission(memory_bytes=100, downloads=2)
        ...     async with admission.drawing(10):
        ...         inside = admission.in_use
        ...     return inside, admission.in_use
        >>> asyncio.run(demo())
        (30, 0)
    """

    def __init__(self, *, memory_bytes: int, downloads: int) -> None:
        """A budget of ``memory_bytes`` and ``downloads`` concurrent drawings."""
        self._budget = memory_bytes
        self._in_use = 0
        self._slots = asyncio.Semaphore(downloads)
        self._changed = asyncio.Condition()

    @property
    def in_use(self) -> int:
        """Bytes reserved now."""
        return self._in_use

    @asynccontextmanager
    async def drawing(self, file_size: int) -> AsyncGenerator[None]:
        """Wait for a download slot and for enough budget for a file of ``file_size`` bytes.

        The wait is recorded as the ``queue`` phase (Server-Timing). A caller that goes away while
        waiting gives its slot back (the ``async with`` exits on the cancellation).
        """
        cost = min(file_size * MEMORY_FACTOR, self._budget)  # larger than all: it runs alone
        started = time.perf_counter()
        async with self._slots:
            async with self._changed:
                await self._changed.wait_for(lambda: self._in_use + cost <= self._budget)
                self._in_use += cost
            record("queue", started)
            try:
                yield
            finally:
                async with self._changed:
                    self._in_use -= cost
                    self._changed.notify_all()
