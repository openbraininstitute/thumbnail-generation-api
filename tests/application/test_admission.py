"""Admission: the memory budget and the download cap hold under a burst."""

import asyncio

from app.application.admission import MEMORY_FACTOR, Admission


async def burst(admission: Admission, sizes: list[int]) -> tuple[int, int]:
    """Run drawings of ``sizes`` at once; return the peak bytes and peak drawings in flight."""
    peak_bytes = peak_count = count = 0

    async def one(size: int) -> None:
        nonlocal peak_bytes, peak_count, count
        async with admission.drawing(size):
            count += 1
            peak_bytes, peak_count = max(peak_bytes, admission.in_use), max(peak_count, count)
            await asyncio.sleep(0.01)
            count -= 1

    await asyncio.gather(*(one(size) for size in sizes))
    return peak_bytes, peak_count


async def test_memory_never_goes_over_the_budget() -> None:
    admission = Admission(memory_bytes=100 * MEMORY_FACTOR, downloads=50)
    peak_bytes, _ = await burst(admission, [30] * 20)
    assert peak_bytes <= 100 * MEMORY_FACTOR
    assert admission.in_use == 0


async def test_downloads_are_capped() -> None:
    admission = Admission(memory_bytes=10**9, downloads=4)
    _, peak_count = await burst(admission, [1] * 40)
    assert peak_count == 4


async def test_a_file_larger_than_the_budget_runs_alone_and_finishes() -> None:
    admission = Admission(memory_bytes=100, downloads=8)
    peak_bytes, _ = await asyncio.wait_for(burst(admission, [10_000, 1, 1]), timeout=5)
    assert peak_bytes <= 100
    assert admission.in_use == 0


async def test_first_come_first_served_a_large_file_is_not_starved() -> None:
    """A small drawing that arrives after a waiting large one does not overtake it."""
    admission = Admission(memory_bytes=100, downloads=8)
    order: list[str] = []
    release = asyncio.Event()

    async def one(name: str, size: int, hold: asyncio.Event | None = None) -> None:
        async with admission.drawing(size):
            order.append(name)
            if hold:
                await hold.wait()

    first = asyncio.create_task(one("small-1", 1, release))
    await asyncio.sleep(0)  # small-1 holds 3 bytes
    large = asyncio.create_task(one("large", 10_000))
    await asyncio.sleep(0)  # large waits for the whole budget
    late = asyncio.create_task(one("small-2", 1))
    await asyncio.sleep(0.01)
    assert order == ["small-1"]  # small-2 fits, but waits behind large
    release.set()
    await asyncio.wait_for(asyncio.gather(first, large, late), timeout=5)
    assert order == ["small-1", "large", "small-2"]
    assert admission.in_use == 0


async def test_a_cancelled_waiter_does_not_block_the_queue() -> None:
    admission = Admission(memory_bytes=100, downloads=8)
    release = asyncio.Event()

    async def hold() -> None:
        async with admission.drawing(1):
            await release.wait()

    holder = asyncio.create_task(hold())
    await asyncio.sleep(0)
    large = asyncio.create_task(admission.drawing(10_000).__aenter__())
    await asyncio.sleep(0)
    large.cancel()
    await asyncio.gather(large, return_exceptions=True)

    async def small() -> None:
        async with admission.drawing(1):
            pass

    await asyncio.wait_for(small(), timeout=1)  # the cancelled head left the queue
    release.set()
    await holder
    assert admission.in_use == 0
