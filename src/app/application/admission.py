"""Per-process memory budget and download cap for drawings (Bulkhead).

Without it, 200 concurrent cold requests ran a 2 GiB container out of memory. A drawing reserves
3x its file size before it downloads; one larger than the budget runs alone. First come, first
served.
"""

import asyncio
import time
from collections import deque
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from app.timing import record

# Peak bytes per file byte: file + parsed data + figure.
# ponytail: one factor for all types; measure per renderer if the budget is off.
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
        # FIFO: only the head may take budget, so small drawings cannot starve a large one.
        self._waiting: deque[object] = deque()

    @property
    def in_use(self) -> int:
        """Bytes reserved now."""
        return self._in_use

    @asynccontextmanager
    async def drawing(self, file_size: int) -> AsyncGenerator[None]:
        """Wait for a download slot and budget for ``file_size`` bytes (timed as ``queue``)."""
        cost = min(file_size * MEMORY_FACTOR, self._budget)  # larger than the budget: runs alone
        started = time.perf_counter()
        async with self._slots:
            ticket = object()
            async with self._changed:
                self._waiting.append(ticket)
                try:
                    await self._changed.wait_for(
                        lambda: self._waiting[0] is ticket and self._in_use + cost <= self._budget
                    )
                    self._in_use += cost
                finally:  # served or cancelled: the next waiter becomes the head
                    self._waiting.remove(ticket)  # at most `downloads` waiters
                    self._changed.notify_all()
            record("queue", started)
            try:
                yield
            finally:
                async with self._changed:
                    self._in_use -= cost
                    self._changed.notify_all()
