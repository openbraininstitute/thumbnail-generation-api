"""Old service vs new service: latency and throughput of the images, against one fake entitycore.

    uv run python scripts/bench.py <old image> <new image>

Measures, per image, through its nginx: the first request of each thumbnail type (a MISS: fetch
and draw), the same request again (a HIT, median of 20), 64 concurrent hits, 16 concurrent misses
(16 dpi values of one morphology), and the container memory after the run. The fake entitycore
answers at once, so a miss here is drawing time plus local hops, not network time.
"""

import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer

import parity
from parity import Case, query

TYPES = [
    Case("morphology", query("cell-morphology", "&dpi=100&format=webp")),
    Case("ephys", query("electrical-cell-recording", "&dpi=100&format=webp")),
    Case("ion channel", query("ion-channel-recording", "&dpi=100&format=webp")),
    Case("simulation", query("single-neuron-simulation", "&target=stimulus&format=webp")),
    Case("model trace", f"/core/model-trace/preview?entity_id={parity.EMODEL}"),
]


def timed(port: int, case: Case) -> float:
    started = time.perf_counter()
    status, _, _ = parity.get(port, case)
    if status != 200:
        raise RuntimeError(f"{case.name}: {status}")
    return (time.perf_counter() - started) * 1000


def measure(image: str, entitycore: int) -> tuple[dict[str, tuple[float, float]], str]:
    port = parity.free_port()
    name = f"bench-{port}"
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--add-host=host.docker.internal:host-gateway",
            "-p",
            f"127.0.0.1:{port}:80",
            "-e",
            f"ENTITY_CORE_URI=http://host.docker.internal:{entitycore}",
            "-e",
            "MPLCONFIGDIR=/tmp/matplotlib",
            image,
        ],
        check=True,
        capture_output=True,
    )
    try:
        for _ in range(120):
            try:
                if parity.get(port, Case("health", "/health", token=None))[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(0.5)
        result: dict[str, tuple[float, float]] = {}
        for case in TYPES:
            miss = timed(port, case)
            hits = [timed(port, case) for _ in range(20)]
            result[case.name] = (miss, statistics.median(hits))
        hit = TYPES[0]
        with ThreadPoolExecutor(64) as pool:
            started = time.perf_counter()
            latencies = list(pool.map(lambda _: timed(port, hit), range(64)))
            result["64 concurrent hits"] = (
                (time.perf_counter() - started) * 1000,
                statistics.quantiles(latencies, n=20)[18],
            )
        misses = [
            Case(f"dpi {d}", query("cell-morphology", f"&dpi={d}")) for d in range(110, 270, 10)
        ]
        with ThreadPoolExecutor(16) as pool:
            started = time.perf_counter()
            latencies = list(pool.map(lambda c: timed(port, c), misses))
            result["16 concurrent misses"] = (
                (time.perf_counter() - started) * 1000,
                statistics.quantiles(latencies, n=20)[18],
            )
        stats = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", name],
            capture_output=True,
            text=True,
            check=True,
        )
        return result, stats.stdout.strip().split(" / ")[0]
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)


def main() -> int:
    old_image, new_image = sys.argv[1], sys.argv[2]
    server = ThreadingHTTPServer(("0.0.0.0", 0), parity.Handler)  # noqa: S104 - containers reach it
    parity.Handler.port = server.server_port
    threading.Thread(target=server.serve_forever, daemon=True).start()
    (old, old_memory), (new, new_memory) = (
        measure(old_image, server.server_port),
        measure(new_image, server.server_port),
    )
    server.shutdown()
    print(f"{'':24s} {'old: miss / hit ms':>22s} {'new: miss / hit ms':>22s}")
    for case in TYPES:
        (om, oh), (nm, nh) = old[case.name], new[case.name]
        print(f"{case.name:24s} {om:10.0f} / {oh:7.1f}   {nm:10.0f} / {nh:7.1f}")
    print(f"\n{'':24s} {'old: total / p95 ms':>22s} {'new: total / p95 ms':>22s}")
    for key in ("64 concurrent hits", "16 concurrent misses"):
        (ot, op), (nt, np_) = old[key], new[key]
        print(f"{key:24s} {ot:10.0f} / {op:7.0f}   {nt:10.0f} / {np_:7.0f}")
    memory = "memory after the run"
    print(f"\n{memory:24s} {old_memory:>22s} {new_memory:>22s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
