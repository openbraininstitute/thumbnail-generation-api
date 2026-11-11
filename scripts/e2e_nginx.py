"""End-to-end check of the image: nginx cache + granian app, against a fake entitycore.

``make e2e`` (builds first). Standard library only. Runs the image as ECS does (read-only root, the
task's writable volumes, BASE_PATH) and checks the cache over HTTP: a hit makes no call to the app
or entitycore, errors are never stored, CORS per origin, concurrent misses draw once.
"""

import hashlib
import http.client
import json
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

IMAGE = sys.argv[1] if len(sys.argv) > 1 else "thumbnail-generation-api:local"
BASE = "/api/thumbnail-generation"
ENTITY, ASSET = "00000000-0000-0000-0000-00000000e001", "00000000-0000-0000-0000-00000000a001"
SWC = (Path(__file__).parent.parent / "tests/fixtures/data/morphology.swc").read_bytes()
MEMBER, OUTSIDER = "Bearer member", "Bearer outsider"
ALLOWED_ORIGIN = "http://localhost:3000"


STORAGE_PORT = [0]  # the fake's port, set once it listens (it serves storage too)


class Entitycore:
    """What the fake entitycore counts, and the digest of its one file."""

    metadata = 0
    downloads = 0
    digest = hashlib.sha256(SWC).hexdigest()
    lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    """entitycore's asset routes, readable by MEMBER only (others get 404, as entitycore does)."""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - the base's name
        """Quiet."""

    def _send(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        """Asset metadata, download redirect, and the stored file."""
        asset_path = f"/cell-morphology/{ENTITY}/assets/{ASSET}"
        member = self.headers.get("Authorization") == MEMBER
        if self.path == asset_path:
            with Entitycore.lock:
                Entitycore.metadata += 1
            if not member:
                return self._send(404, b'{"error_code":"ENTITY_NOT_FOUND"}')
            row = {
                "id": ASSET,
                "content_type": "application/swc",
                "size": len(SWC),
                "sha256_digest": Entitycore.digest,
                "status": "created",
                "path": "m.swc",
            }
            return self._send(200, json.dumps(row).encode(), {"Content-Type": "application/json"})
        if self.path == f"{asset_path}/download":
            if not member:
                return self._send(404)
            location = (
                f"http://host.docker.internal:{STORAGE_PORT[0]}/storage/m.swc?X-Signature=abc"
            )
            return self._send(307, headers={"Location": location})
        if self.path.startswith("/storage/m.swc"):
            with Entitycore.lock:
                Entitycore.downloads += 1
            time.sleep(0.3)  # a slow storage, so concurrent misses overlap
            return self._send(200, SWC)
        return self._send(404)


def docker_logs(name: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", "logs", name], capture_output=True, text=True, check=False)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


RAW_HEADERS: list[tuple[str, str]] = []  # of the last response, duplicates kept


def get(port: int, path: str, **headers: str) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    connection.request("GET", path, headers={k.replace("_", "-"): v for k, v in headers.items()})
    response = connection.getresponse()
    body = response.read()
    connection.close()
    RAW_HEADERS[:] = [(k.lower(), v) for k, v in response.getheaders()]
    return response.status, dict(RAW_HEADERS), body


failures: list[str] = []


def check(name: str, condition: bool, detail: object = "") -> None:  # noqa: FBT001
    print(f"{'ok  ' if condition else 'FAIL'} {name}{'' if condition else f'  ({detail})'}")
    if not condition:
        failures.append(name)


def main() -> int:
    fake = ThreadingHTTPServer(("0.0.0.0", 0), Handler)  # noqa: S104 - the container reaches it
    STORAGE_PORT[0] = fake.server_port
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    port = free_port()
    name = f"thumb-e2e-{port}"
    volumes = ["/tmp", "/var/cache/nginx", "/var/lib/nginx", "/var/run", "/var/cache/fontconfig"]
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--read-only",
            *[arg for v in volumes for arg in ("--tmpfs", v)],
            "--add-host=host.docker.internal:host-gateway",
            "-p",
            f"127.0.0.1:{port}:80",
            "-e",
            f"BASE_PATH={BASE}",
            "-e",
            f"ENTITY_CORE_URI=http://host.docker.internal:{fake.server_port}",
            "-e",
            f'WHITELISTED_CORS_URLS=["{ALLOWED_ORIGIN}"]',
            IMAGE,
        ],
        check=True,
        capture_output=True,
    )
    try:
        for _ in range(60):
            try:
                if get(port, f"{BASE}/health")[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(0.5)
        run(port)
        lines = docker_logs(name).stdout
        nginx_lines = [
            json.loads(line) for line in lines.splitlines() if '"logger":"nginx"' in line
        ]
        check(
            "nginx logs JSON lines with the request id and the cache status",
            bool(nginx_lines)
            and all(line["request_id"] for line in nginx_lines)
            and {"HIT", "MISS"} <= {line["cache"] for line in nginx_lines},
            nginx_lines[-1:],
        )
    finally:
        if failures:
            logs = docker_logs(name)
            print(logs.stdout[-4000:], logs.stderr[-4000:])
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
        fake.shutdown()
    print(f"\n{len(failures)} failed" if failures else "\nall checks passed")
    return 1 if failures else 0


def cors_checks(port: int, preview: str) -> None:
    """CORS, as a browser asks: the preflight with its request headers, then the image."""

    # The preflight exactly as core-web-app's browser sends it (src/api/thumbnail-svc/index.ts sends
    # Content-Type: application/json, which is not a simple header): the first version of this
    # check sent no request headers, and missed that Content-Type was refused.
    def preflight(origin: str, headers: str) -> http.client.HTTPResponse:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        connection.request(
            "OPTIONS",
            preview,
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": headers,
            },
        )
        response = connection.getresponse()
        response.read()
        return response

    asked = "authorization,content-type,virtual-lab-id,project-id"
    answer = preflight(ALLOWED_ORIGIN, asked)
    allowed = (answer.getheader("Access-Control-Allow-Headers") or "").lower()
    check(
        "preflight as core-web-app sends it (Authorization, Content-Type, project-id): allowed",
        answer.status == 204
        and answer.getheader("Access-Control-Allow-Origin") == ALLOWED_ORIGIN
        and all(name in allowed for name in asked.split(",")),
        (answer.status, allowed),
    )
    other_port = preflight("http://localhost:5173", asked)
    check(
        "preflight from another localhost port (5173): allowed",
        other_port.getheader("Access-Control-Allow-Origin") == "http://localhost:5173",
        other_port.getheader("Access-Control-Allow-Origin"),
    )
    evil = preflight("http://localhost.evil.test", asked)
    check(
        "preflight from a lookalike origin: no CORS header",
        evil.getheader("Access-Control-Allow-Origin") is None,
        evil.getheader("Access-Control-Allow-Origin"),
    )
    _, headers, _ = get(port, preview, Authorization=MEMBER, Origin="http://localhost:5173")
    check(
        "an image for another localhost port gets that origin back",
        headers.get("access-control-allow-origin") == "http://localhost:5173",
        headers.get("access-control-allow-origin"),
    )


def run(port: int) -> None:
    query = f"entity_id={ENTITY}&asset_id={ASSET}&dpi=100&format=webp"
    preview = f"{BASE}/core/cell-morphology/preview?{query}"
    status, headers, _ = get(port, f"{BASE}/health")
    check(
        "health answers through nginx under BASE_PATH",
        status == 200 and headers.get("server") == "nginx",
        (status, headers.get("server")),
    )

    status, headers, body = get(port, preview)
    check(
        "no token: 401 problem from the app, cache not read",
        status == 401 and json.loads(body)["code"] == "UNAUTHENTICATED",
        (status, body[:80]),
    )

    status, headers, body = get(port, preview, Authorization=OUTSIDER)
    check("outsider on a miss: entitycore refuses, 404", status == 404, status)

    status, headers, first = get(port, preview, Authorization=MEMBER)
    check(
        "member after the refusal: 200 from a MISS (the 404 was not stored)",
        status == 200
        and headers.get("content-type") == "image/webp"
        and headers.get("x-cache") == "MISS",
        (status, headers),
    )
    check(
        "browser caching headers",
        headers.get("cache-control") == "private, max-age=3600"
        and headers.get("etag", "").startswith('"'),
        headers,
    )
    timing = headers.get("server-timing", "")
    check(
        "a miss carries the app's phases in Server-Timing",
        all(f"{name};dur=" in timing for name in ("meta", "download", "render", "app"))
        and 'cache;desc="MISS"' in timing,
        timing,
    )
    etag = headers.get("etag", "")
    check("one download for the miss", Entitycore.downloads == 1, Entitycore.downloads)

    metadata = Entitycore.metadata
    status, headers, again = get(port, preview, Authorization=MEMBER)
    check(
        "member again: HIT, same bytes",
        status == 200 and headers.get("x-cache") == "HIT" and again == first,
        (status, headers.get("x-cache")),
    )
    check(
        "a hit makes no call to entitycore",
        (Entitycore.metadata, Entitycore.downloads) == (metadata, 1),
        (Entitycore.metadata - metadata, Entitycore.downloads),
    )
    check(
        "a hit says HIT in Server-Timing, not the miss's old times",
        headers.get("server-timing") == 'cache;desc="HIT"',
        headers.get("server-timing"),
    )
    names = [k for k, _ in RAW_HEADERS]
    check(
        "a hit has one Cache-Control, one Content-Type, one ETag",
        all(names.count(n) == 1 for n in ("cache-control", "content-type", "etag")),
        RAW_HEADERS,
    )

    shuffled = f"format=webp&dpi=100&asset_id={ASSET}&entity_id={ENTITY}&x=1"
    reordered = f"{BASE}/core/cell-morphology/preview?{shuffled}"
    status, headers, body = get(port, reordered, Authorization=MEMBER)
    check(
        "other parameter order and an unknown parameter: same entry, HIT",
        headers.get("x-cache") == "HIT" and body == first,
        headers.get("x-cache"),
    )

    status, headers, body = get(port, preview, Authorization=MEMBER, If_None_Match=etag)
    check("current browser copy: 304, empty", status == 304 and body == b"", status)

    _, headers, _ = get(port, preview, Authorization=MEMBER, Origin=ALLOWED_ORIGIN)
    check(
        "allowed origin gets its own origin on a cached image",
        headers.get("access-control-allow-origin") == ALLOWED_ORIGIN,
        headers.get("access-control-allow-origin"),
    )
    _, headers, _ = get(port, preview, Authorization=MEMBER, Origin="http://evil.test")
    check(
        "other origin gets no CORS header",
        "access-control-allow-origin" not in headers,
        headers.get("access-control-allow-origin"),
    )
    status, headers, _ = get(port, preview, Origin=ALLOWED_ORIGIN)
    check(
        "401 for no token still has CORS for the allowed origin",
        status == 401 and headers.get("access-control-allow-origin") == ALLOWED_ORIGIN,
        (status, headers.get("access-control-allow-origin")),
    )

    cors_checks(port, preview)

    burst = preview.replace("dpi=100", "dpi=150")
    downloads = Entitycore.downloads
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: get(port, burst, Authorization=MEMBER), range(8)))
    check(
        "8 concurrent misses: all 200, same image",
        all(r[0] == 200 for r in results) and len({r[2] for r in results}) == 1,
        [r[0] for r in results],
    )
    check(
        "8 concurrent misses: one download (cache lock)",
        Entitycore.downloads == downloads + 1,
        Entitycore.downloads - downloads,
    )

    status, headers, _ = get(port, preview, Authorization=OUTSIDER)
    check(
        "KNOWN GAP (planned next): a cached image is sent to any token, no access check",
        status == 200 and headers.get("x-cache") == "HIT",
        status,
    )


if __name__ == "__main__":
    sys.exit(main())
