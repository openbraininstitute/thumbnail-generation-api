"""
Module: offload.py

Helpers to run blocking, CPU-bound work (morphology loading, matplotlib
rendering, PNG rasterization, HDF5 parsing) off the asyncio event loop.

The preview endpoints are declared ``async def`` so FastAPI runs them directly
on the event loop. The actual rendering work is synchronous and CPU-bound, so
running it inline blocks the loop and serializes concurrent requests. Wrapping
that work with :func:`run_blocking` moves it to the Starlette/anyio worker
threadpool, letting requests overlap (matplotlib's Agg backend, numpy and h5py
release the GIL for much of their C-level work).
"""

from collections.abc import Callable

from starlette.concurrency import run_in_threadpool


async def run_blocking[T](func: Callable[..., T], *args, **kwargs) -> T:
    """Run a blocking, CPU-bound callable in the worker threadpool.

    Args:
        func: The synchronous callable to execute.
        *args: Positional arguments forwarded to ``func``.
        **kwargs: Keyword arguments forwarded to ``func``.

    Returns:
        The return value of ``func``.
    """
    if kwargs:
        return await run_in_threadpool(lambda: func(*args, **kwargs))
    return await run_in_threadpool(func, *args)
