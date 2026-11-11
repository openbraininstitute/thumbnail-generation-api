"""Where a request's time went, sent back as a W3C ``Server-Timing`` header.

``Server-Timing`` (https://www.w3.org/TR/server-timing/) is the standard place for it: browsers
show each phase in DevTools (Network > a request > Timing), and scripts read it from
``performance.getEntries()``. Phases are measured with ``time.perf_counter`` (monotonic, sub-µs:
a wall clock can jump while a request runs).

The request log middleware opens a collector per request (:func:`collect`); code anywhere below it
records a phase with ``with phase("render"):``, with nothing passed down (a ``ContextVar``, as the
log context). Outside a request, recording does nothing.

Example header (a cache miss):
``queue;dur=0.1, meta;dur=312.4, download;dur=180.2, render_wait;dur=0.2, render;dur=46.9,
app;dur=541.3``

``queue`` and ``render_wait`` are waits (for memory or a download slot, then for a render slot):
high values mean a busy process, not slow work.
"""

import time
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar

type Phases = list[tuple[str, float]]

_PHASES: ContextVar[Phases | None] = ContextVar("server_timing", default=None)


@contextmanager
def collect() -> Generator[Phases]:
    """Collect the phases recorded inside the block (one request)."""
    phases: Phases = []
    token = _PHASES.set(phases)
    try:
        yield phases
    finally:
        _PHASES.reset(token)


@contextmanager
def phase(name: str) -> Generator[None]:
    """Record how long the block took as ``name`` (a token: letters, digits, ``-`` or ``_``).

    Examples:
        >>> with collect() as phases, phase("render"):
        ...     pass
        >>> [name for name, _ in phases]
        ['render']
    """
    started = time.perf_counter()
    try:
        yield
    finally:
        record(name, started)


def record(name: str, started: float) -> None:
    """Record ``name`` as the time since ``started`` (a ``time.perf_counter()`` value)."""
    phases = _PHASES.get()
    if phases is not None:
        phases.append((name, (time.perf_counter() - started) * 1000))


def header(phases: Phases, total_ms: float) -> str:
    """The ``Server-Timing`` value: each phase, then ``app`` (the whole request in the app).

    Examples:
        >>> header([("meta", 312.44), ("render", 46.9)], 400.0)
        'meta;dur=312.4, render;dur=46.9, app;dur=400.0'
    """
    parts = [f"{name};dur={ms:.1f}" for name, ms in phases]
    return ", ".join([*parts, f"app;dur={total_ms:.1f}"])
