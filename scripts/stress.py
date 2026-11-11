"""Stress test of one image against staging entitycore, the way the web app's grids load thumbnails.

    make stress-test-old        # the old service's image (built from git)
    make stress-test-new        # this repository's image
    make stress-report          # both results side by side

    uv run python scripts/stress.py run <old|new> <image>
    uv run python scripts/stress.py report

What one run does:

1. Signs in as the obi-e2e QA user (scripts/staging_token.py) and lists public entities from staging
   entitycore, as core-web-app's grids do: morphologies, electrical cell recordings, ion channel
   recordings, e-models and me-models (model traces). Simulations are left out (tested apart).
   The chosen entities are saved (reports/stress-selection.json), so both runs ask for the same.
2. Starts the image with the resources of the staging ECS task (infra
   thumbnail-generation-api/container.tf): ARM64, a 2 vCPU task, a 2 GiB hard memory limit for the
   container, no swap, a read-only root with the task's writable volumes (on disk, as on Fargate).
3. For each type and each level (50, 100, 200 thumbnails), fires every request at the same moment
   on an empty cache (cold), then the same requests again (warm: the nginx cache). A level uses
   entities the earlier levels did not, so a cold request is always a miss.
4. Samples the container's CPU and memory every second, and records per request: status, time,
   size and cache status. Writes reports/stress-<name>.json and prints a summary.

The two runs never overlap, so staging entitycore carries one service at a time.
The grid's request: GET /core/<type>/preview?entity_id=…&asset_id=…&dpi=100&format=webp,
Accept: image/webp,image/png, a bearer token, no project headers (public entities).
"""

import asyncio
import json
import os
import re
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx2

sys.path.insert(0, str(Path(__file__).parent))
import staging_token

ENTITYCORE = "https://staging.cell-a.openbraininstitute.org/api/entitycore"
BASE_PATH = "/api/thumbnail-generation"  # as deployed: requests carry the prefix
REPORTS = Path(__file__).parent.parent / "reports"
SELECTION = REPORTS / "stress-selection.json"
LEVELS = (50, 100, 200)
# STRESS_LEVELS="3" runs a tiny check of the script itself; the selection always covers LEVELS.
RUN_LEVELS = tuple(int(n) for n in os.environ.get("STRESS_LEVELS", "").split() if n) or LEVELS
COOL_DOWN_S = 20  # before each cold burst, so one burst's load on staging does not hit the next
LB_IDLE_TIMEOUT_S = 60  # AWS ALB default; infra sets no idle_timeout, so slower answers get a 504

# The staging ECS task (infra thumbnail-generation-api/container.tf): task cpu 2048 = 2 vCPU,
# memory 4096; the container: cpu 1024 (a share, not a cap, on Fargate: alone in its task it
# may use the task's 2 vCPU) and memory 2048 (a hard limit: over it, the container is killed).
RESOURCES = [
    "--platform",
    "linux/arm64",
    "--cpus",
    "2",
    "--cpu-shares",
    "1024",
    "--memory",
    "2g",
    "--memory-swap",
    "2g",
]
# readonlyRootFilesystem with the task's volumes. Docker volumes, on disk like Fargate's
# ephemeral storage (a tmpfs would count against the 2 GiB memory limit).
VOLUMES = [
    "/tmp",
    "/var/cache/nginx",
    "/var/lib/nginx",
    "/var/run",
    "/var/cache/fontconfig",
    "/app/output",
]

# entity type -> (thumbnail route, entitycore routes, asset content type); None: model trace
TYPES: dict[str, tuple[str, tuple[str, ...], str | None]] = {
    "morphology": ("cell-morphology", ("cell-morphology",), "application/swc"),
    "ephys": ("electrical-cell-recording", ("electrical-cell-recording",), "application/nwb"),
    "ion channel": ("ion-channel-recording", ("ion-channel-recording",), "application/nwb"),
    "model trace": ("model-trace", ("emodel", "memodel"), None),
}


def select(token: str) -> dict[str, list[dict[str, str]]]:
    """The entities to ask for, per type: listed once from entitycore, then reused from the file."""
    if SELECTION.exists():
        return json.loads(SELECTION.read_text())
    wanted = sum(LEVELS)
    chosen: dict[str, list[dict[str, str]]] = {}
    with httpx2.Client(timeout=60, headers={"Authorization": f"Bearer {token}"}) as http:
        for name, (_, routes, content_type) in TYPES.items():
            rows: list[dict[str, str]] = []
            for route in routes:
                answer = http.get(f"{ENTITYCORE}/{route}", params={"page": 1, "page_size": 1000})
                answer.raise_for_status()
                for entity in answer.json()["data"]:
                    if content_type is None:  # model trace: the route needs the entity only
                        rows.append({"entity_id": entity["id"]})
                        continue
                    asset = next(
                        (
                            a
                            for a in entity.get("assets", [])
                            if a.get("content_type") == content_type
                        ),
                        None,
                    )
                    if asset is not None:
                        rows.append({"entity_id": entity["id"], "asset_id": asset["id"]})
            chosen[name] = rows[:wanted]
    REPORTS.mkdir(exist_ok=True)
    SELECTION.write_text(json.dumps(chosen, indent=1))
    return chosen


class Stats:
    """The container's CPU and memory, sampled by `docker stats` while the test runs."""

    def __init__(self, container: str) -> None:
        """Start sampling ``container``; ``phase`` labels the samples taken from now on."""
        self.phase = "start"
        self.samples: list[tuple[str, float, float]] = []  # (phase, cpu %, memory MiB)
        self._process = subprocess.Popen(
            ["docker", "stats", "--format", "{{json .}}", container],
            stdout=subprocess.PIPE,
            text=True,
        )
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        assert self._process.stdout is not None  # noqa: S101
        for line in self._process.stdout:
            match = re.search(r"\{.*\}", line)
            if not match:
                continue
            row = json.loads(match.group(0))
            cpu = float(row["CPUPerc"].rstrip("%") or 0)
            self.samples.append((self.phase, cpu, mebibytes(row["MemUsage"].split("/")[0])))

    def of(self, phase: str) -> dict[str, float]:
        """Average and peak CPU, and peak memory, of one phase."""
        rows = [(c, m) for p, c, m in self.samples if p == phase]
        if not rows:
            return {}
        return {
            "cpu_avg": statistics.mean(c for c, _ in rows),
            "cpu_max": max(c for c, _ in rows),
            "mem_max_mib": max(m for _, m in rows),
        }

    def stop(self) -> None:
        """Stop sampling."""
        self._process.terminate()


def mebibytes(text: str) -> float:
    """``123.4MiB`` / ``1.2GiB`` / ``512KiB`` in MiB."""
    match = re.match(r"([\d.]+)\s*([KMG]i?B|B)", text.strip())
    if match is None:
        return 0.0
    number, unit = match.groups()
    return (
        float(number)
        * {
            "B": 1 / 2**20,
            "KiB": 1 / 1024,
            "KB": 1 / 1024,
            "MiB": 1,
            "MB": 1,
            "GiB": 1024,
            "GB": 1024,
        }[unit]
    )


async def burst(
    port: int, token: str, route: str, rows: list[dict[str, str]]
) -> list[dict[str, Any]]:
    """Every request at the same moment, as a grid that scrolls N thumbnails into view."""
    limits = httpx2.Limits(max_connections=len(rows), max_keepalive_connections=len(rows))
    headers = {"Authorization": f"Bearer {token}", "Accept": "image/webp,image/png"}
    async with httpx2.AsyncClient(
        base_url=f"http://127.0.0.1:{port}", limits=limits, timeout=600, headers=headers
    ) as http:

        async def one(row: dict[str, str]) -> dict[str, Any]:
            params = (
                {"entity_id": row["entity_id"]}
                if route == "model-trace"
                else {**row, "dpi": "100", "format": "webp"}
            )
            started = time.perf_counter()
            try:
                answer = await http.get(f"{BASE_PATH}/core/{route}/preview", params=params)
                status, size = answer.status_code, len(answer.content)
                cache = answer.headers.get("x-cache") or answer.headers.get("x-cached") or ""
                reason = "" if status == 200 else reason_of(answer)
            except httpx2.HTTPError as error:
                status, size, cache, reason = 0, 0, "", type(error).__name__
            return {
                "status": status,
                "ms": (time.perf_counter() - started) * 1000,
                "bytes": size,
                "cache": cache,
                "reason": reason,
            }

        return list(await asyncio.gather(*(one(row) for row in rows)))


def reason_of(answer: httpx2.Response) -> str:
    """Why a request failed: the error body's code (both services), else its first words."""
    try:
        body = answer.json()
    except ValueError:
        return answer.text[:60].strip() or f"HTTP {answer.status_code}"
    if isinstance(body, dict):
        detail = body.get("detail") if isinstance(body.get("detail"), str) else ""
        return str(body.get("code") or body.get("error_code") or detail or body)[:80]
    return str(body)[:80]


def summary(results: list[dict[str, Any]], wall_ms: float) -> dict[str, Any]:
    times = sorted(r["ms"] for r in results)
    statuses: dict[str, int] = {}
    caches: dict[str, int] = {}
    reasons: dict[str, int] = {}
    for r in results:
        if r["reason"]:
            reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
        statuses[str(r["status"])] = statuses.get(str(r["status"]), 0) + 1
        caches[r["cache"] or "-"] = caches.get(r["cache"] or "-", 0) + 1

    def pct(p: float) -> float:
        return times[min(len(times) - 1, round(p * (len(times) - 1)))]

    return {
        "requests": len(results),
        "statuses": statuses,
        "reasons": reasons,
        "cache": caches,
        "p50_ms": pct(0.5),
        "p95_ms": pct(0.95),
        "p99_ms": pct(0.99),
        "max_ms": times[-1],
        "wall_ms": wall_ms,
        "per_second": len(results) / (wall_ms / 1000),
        "over_lb_timeout": sum(t > LB_IDLE_TIMEOUT_S * 1000 for t in times),
        "bytes": sum(r["bytes"] for r in results),
    }


def start(image: str, port: int) -> str:
    name = f"stress-{port}"
    volumes = [arg for v in VOLUMES for arg in ("--mount", f"type=volume,dst={v}")]
    env = {
        "ENTITY_CORE_URI": ENTITYCORE,
        "BASE_PATH": BASE_PATH,
        "ENVIRONMENT": "staging",
        "MPLCONFIGDIR": "/tmp/matplotlib",
        "WHITELISTED_CORS_URLS": '["http://localhost:3000"]',
    }
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--read-only",
            *RESOURCES,
            *volumes,
            "-p",
            f"127.0.0.1:{port}:80",
            *[a for k, v in env.items() for a in ("-e", f"{k}={v}")],
            image,
        ],
        check=True,
        capture_output=True,
    )
    for _ in range(240):
        try:
            if (
                httpx2.get(f"http://127.0.0.1:{port}{BASE_PATH}/health", timeout=2).status_code
                == 200
            ):
                return name
        except httpx2.HTTPError:
            pass
        time.sleep(0.5)
    raise SystemExit(f"{image} did not become healthy")


def run(label: str, image: str) -> None:
    token = staging_token.token()
    chosen = select(token)
    port = 18400 + (label == "new")
    container = start(image, port)
    stats = Stats(container)
    time.sleep(3)  # an idle sample, before any load
    load_started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    report: dict[str, Any] = {"label": label, "image": image, "resources": RESOURCES, "phases": []}
    try:
        for name, (route, _, _) in TYPES.items():
            token = staging_token.token()  # fresh (1 h tokens), the run lasts several minutes
            offset = 0
            for level in RUN_LEVELS:
                rows = chosen[name][offset : offset + level]
                offset += level
                if not rows:
                    continue
                for phase in ("cold", "warm"):
                    probe = {}
                    if phase == "cold":
                        time.sleep(COOL_DOWN_S)  # staging recovers from the last burst
                        probe = entitycore_health()
                    key = f"{name} {len(rows)} {phase}"
                    stats.phase = key
                    started = time.perf_counter()
                    results = asyncio.run(burst(port, token, route, rows))
                    wall = (time.perf_counter() - started) * 1000
                    time.sleep(1.5)  # one more sample of this phase
                    row = {
                        "entitycore_before": probe,
                        "type": name,
                        "level": len(rows),
                        "phase": phase,
                        **summary(results, wall),
                        **stats.of(key),
                    }
                    report["phases"].append(row)
                    print(line(row), flush=True)
        stats.phase = "end"
        time.sleep(2)
        report["idle"] = stats.of("start")
        report["health"] = health(container)
    finally:
        stats.stop()
        # Only what was logged under load: start-up lines (nginx up before the app) are not load.
        logs = subprocess.run(
            ["docker", "logs", "--since", load_started, container],
            capture_output=True,
            text=True,
            check=False,
        )
        (REPORTS / f"stress-{label}.log").parent.mkdir(exist_ok=True)
        (REPORTS / f"stress-{label}.log").write_text(logs.stdout + logs.stderr)  # the full logs
        report["log_tail"] = (logs.stdout + logs.stderr)[-6000:]
        report["log_counts"] = log_counts(logs.stdout + logs.stderr)
        subprocess.run(["docker", "rm", "-f", "-v", container], capture_output=True, check=False)
        REPORTS.mkdir(exist_ok=True)
        (REPORTS / f"stress-{label}.json").write_text(json.dumps(report, indent=1))
    print(f"\nhealth: {report['health']}\nlog counts: {report['log_counts']}")
    print(f"written: {REPORTS / f'stress-{label}.json'}")


def entitycore_health() -> dict[str, Any]:
    """Staging entitycore's own health and answer time, just before a burst."""
    started = time.perf_counter()
    try:
        status = httpx2.get(f"{ENTITYCORE}/health", timeout=30).status_code
    except httpx2.HTTPError as error:
        status = type(error).__name__
    return {"status": status, "ms": round((time.perf_counter() - started) * 1000)}


def health(container: str) -> dict[str, Any]:
    state = subprocess.run(
        ["docker", "inspect", "--format", "{{json .State}}", container],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(state.stdout)
    return {
        "running": data["Running"],
        "oom_killed": data["OOMKilled"],
        "restarts": data.get("RestartCount", 0),
    }


def log_counts(text: str) -> dict[str, int]:
    """Signs of trouble in the container's logs (both images)."""
    patterns = {
        "worker timeouts (gunicorn)": r"WORKER TIMEOUT",
        "workers started (gunicorn: 2 at start)": r"Booting worker",
        "processes exited (supervisord)": r"exited: ",
        "killed (out of memory)": r"\bKilled\b|signal 9|SIGKILL",
        "errors": r'"level":\s*"ERROR"|\[error\]|ERROR',
        "5xx responses": r'"status":\s*"?5\d\d|" 5\d\d ',
    }
    return {name: len(re.findall(p, text)) for name, p in patterns.items()}


def line(row: dict[str, Any]) -> str:
    ok = row["statuses"].get("200", 0)
    return (
        f"{row['type']:12s} {row['level']:>4} {row['phase']:5s}  ok {ok:>4}/{row['requests']:<4} "
        f"p50 {row['p50_ms']:7.0f}  p95 {row['p95_ms']:7.0f}  max {row['max_ms']:7.0f} ms  "
        f"wall {row['wall_ms'] / 1000:6.1f}s  cpu max {row.get('cpu_max', 0):5.0f}%  "
        f"mem max {row.get('mem_max_mib', 0):6.0f} MiB  cache {row['cache']}  "
        f"statuses {row['statuses']}  reasons {row.get('reasons', {})}  "
        f"entitycore before {row.get('entitycore_before') or '-'}"
    )


def report() -> None:
    """Old and new side by side, from the two JSON files."""
    runs = {
        label: json.loads((REPORTS / f"stress-{label}.json").read_text())
        for label in ("old", "new")
    }
    print(
        f"{'type':12s} {'n':>4} {'phase':5s} | {'old p50/p95/max ms':>22s} {'ok':>8s} {'mem':>6s} "
        f"| {'new p50/p95/max ms':>22s} {'ok':>8s} {'mem':>6s}"
    )
    for old, new in zip(runs["old"]["phases"], runs["new"]["phases"], strict=True):

        def cell(r: dict[str, Any]) -> str:
            ok = f"{r['statuses'].get('200', 0)}/{r['requests']}"
            return (
                f"{r['p50_ms']:6.0f}/{r['p95_ms']:6.0f}/{r['max_ms']:6.0f} {ok:>8s} "
                f"{r.get('mem_max_mib', 0):6.0f}"
            )

        print(f"{old['type']:12s} {old['level']:>4} {old['phase']:5s} | {cell(old)} | {cell(new)}")
    for label, data in runs.items():
        health, idle, logs = data.get("health"), data.get("idle"), data.get("log_counts")
        print(f"\n{label}: health {health}, idle {idle}, logs {logs}")


if __name__ == "__main__":
    match sys.argv[1:]:
        case ["run", label, image] if label in {"old", "new"}:
            run(label, image)
        case ["report"]:
            report()
        case _:
            raise SystemExit(__doc__)
