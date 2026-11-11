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
