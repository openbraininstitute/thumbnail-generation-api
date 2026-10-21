"""
Local perf benchmark for the event-loop-offload change (PR #34).

What it measures
----------------
The PR's claim: running synchronous CPU-bound render work directly on the
asyncio event loop serializes concurrent requests *within a single worker*,
causing a latency ramp under bursts. Offloading that work to the worker
threadpool (api.utils.offload.run_blocking) lets upstream fetches overlap with
CPU work and lets renders run on multiple threads.

Methodology (apples-to-apples, same app, same machine)
-------------------------------------------------------
- Drive the real FastAPI app in-process via httpx ASGITransport with an async
  client, so N requests are genuinely concurrent on ONE event loop (simulating
  a single gunicorn/uvicorn worker — the unit the PR reasons about).
- Mock only the entitycore asset fetch: it `await asyncio.sleep(UPSTREAM_MS)`
  to simulate real upstream latency, then returns the real SWC fixture. The
  render (neurom load + matplotlib raster) is REAL CPU work.
- Two modes on the identical app:
    offloaded : current behavior (run_blocking -> threadpool)
    inline    : run_blocking monkeypatched to call inline on the event loop,
                reproducing the pre-PR behavior.
- Report p50 / p95 / p99 latency and throughput for a burst of concurrent
  requests. Run both modes; the delta is the value of the change.

Usage:
    uv run python scripts/bench_offload.py
    uv run python scripts/bench_offload.py --concurrency 32 --requests 128
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import statistics
import time
import uuid
from pathlib import Path

import httpx

# Silence per-request access logs so the benchmark output stays readable.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

import api.router.core.morphology as morphology_mod
from api.main import app

SWC_PATH = Path("tests/fixtures/data/morphology.swc")
ENTITY_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
ASSET_ID = uuid.UUID("87654321-4321-8765-4321-876543210987")
HEADERS = {"Authorization": "Bearer fake-token"}


def _load_swc() -> str:
    return SWC_PATH.read_text(encoding="utf-8")


def _install_mock_entitycore(upstream_ms: float) -> None:
    """Patch the morphology router's entitycore client with an async mock.

    The download/content coroutines sleep to simulate upstream latency and
    return the real SWC fixture so the render is genuine CPU work.
    """
    swc = _load_swc()
    upstream_s = upstream_ms / 1000.0

    class _MockClient:
        async def get_asset_download_url(self, *args, **kwargs):
            await asyncio.sleep(upstream_s)
            return "http://example.com/download"

        async def get_asset_content(self, *args, **kwargs):
            await asyncio.sleep(upstream_s)
            return swc

    class _MockCtx:
        async def __aenter__(self):
            return _MockClient()

        async def __aexit__(self, *exc):
            return None

    morphology_mod.get_entitycore_client = lambda: _MockCtx()


def _set_inline_mode(enabled: bool) -> None:
    """Toggle run_blocking between threadpool (offloaded) and inline (pre-PR)."""
    if enabled:

        async def _inline(func, *args, **kwargs):
            # Pre-PR behavior: run the blocking callable directly on the loop.
            return func(*args, **kwargs)

        morphology_mod.run_blocking = _inline
    else:
        from api.utils.offload import run_blocking as real_run_blocking  # noqa: PLC0415

        morphology_mod.run_blocking = real_run_blocking


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    k = max(0, min(len(s) - 1, round(pct / 100 * (len(s) - 1))))
    return s[k]


async def _one_request(client: httpx.AsyncClient, dpi: int) -> tuple[float, int]:
    t0 = time.perf_counter()
    r = await client.get(
        "/core/cell-morphology/preview",
        headers=HEADERS,
        params={"entity_id": str(ENTITY_ID), "asset_id": str(ASSET_ID), "dpi": dpi},
    )
    return (time.perf_counter() - t0) * 1000.0, r.status_code


async def _run_burst(
    concurrency: int, total: int, dpi: int
) -> tuple[list[float], list[int], float]:
    transport = httpx.ASGITransport(app=app)
    latencies: list[float] = []
    codes: list[int] = []
    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:

        async def _bounded() -> None:
            async with sem:
                ms, code = await _one_request(client, dpi)
                latencies.append(ms)
                codes.append(code)

        wall0 = time.perf_counter()
        await asyncio.gather(*[_bounded() for _ in range(total)])
        wall = time.perf_counter() - wall0

    return latencies, codes, wall


async def _bench_mode(
    name: str, inline: bool, concurrency: int, total: int, dpi: int, upstream_ms: float
) -> dict:
    _install_mock_entitycore(upstream_ms)
    _set_inline_mode(inline)

    # Warm up (font cache, first render) so it doesn't skew the first sample.
    await _run_burst(concurrency=1, total=2, dpi=dpi)

    latencies, codes, wall = await _run_burst(concurrency, total, dpi)
    ok = sum(1 for c in codes if c == 200)
    return {
        "mode": name,
        "ok": ok,
        "total": total,
        "wall_s": wall,
        "rps": total / wall if wall else float("nan"),
        "p50": statistics.median(latencies),
        "p95": _percentile(latencies, 95),
        "p99": _percentile(latencies, 99),
        "max": max(latencies),
    }


def _print_row(r: dict) -> None:
    print(
        f"{r['mode']:>9} | ok {r['ok']:>3}/{r['total']:<3} | "
        f"rps {r['rps']:7.1f} | p50 {r['p50']:8.1f}ms | "
        f"p95 {r['p95']:8.1f}ms | p99 {r['p99']:8.1f}ms | max {r['max']:8.1f}ms"
    )


async def _main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, default=16)
    ap.add_argument("--requests", type=int, default=64)
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--upstream-ms", type=float, default=40.0)
    args = ap.parse_args()

    print(
        f"\nBurst: concurrency={args.concurrency} requests={args.requests} "
        f"dpi={args.dpi} simulated-upstream={args.upstream_ms}ms  "
        f"(single event loop)\n"
    )

    inline = await _bench_mode(
        "inline", True, args.concurrency, args.requests, args.dpi, args.upstream_ms
    )
    offloaded = await _bench_mode(
        "offloaded", False, args.concurrency, args.requests, args.dpi, args.upstream_ms
    )

    _print_row(inline)
    _print_row(offloaded)

    print()
    if inline["p95"] and offloaded["p95"]:
        print(
            f"p95 improvement : {inline['p95'] / offloaded['p95']:.2f}x "
            f"({inline['p95']:.0f}ms -> {offloaded['p95']:.0f}ms)"
        )
    if inline["rps"] and offloaded["rps"]:
        print(f"throughput gain : {offloaded['rps'] / inline['rps']:.2f}x")
    print()


if __name__ == "__main__":
    asyncio.run(_main())
