"""Where a request's time went, sent back as a W3C ``Server-Timing`` header (shown in DevTools).

The request log opens a collector per request (:func:`collect`); code below it records a phase with
``with phase("render"):``. ``queue`` and ``render_wait`` are waits: high values mean a busy process.
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
