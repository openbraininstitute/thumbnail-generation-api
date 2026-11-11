"""Old service vs new service: the same requests to both images, the answers compared.

    uv run python scripts/parity.py <old image> <new image>

The old image is built from the commit before the re-architecture (``git archive <commit> | docker
build -t thumbnail-generation-api:old -``). Both images run against one fake entitycore that holds
a real file for every entity type (tests/fixtures/data). For every thumbnail case it compares the
status, the content type and the decoded pixels; for the error cases it prints both answers (the
new service changed those on purpose: real statuses instead of 400 or 500).
"""

import http.client
import io
import json
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import NamedTuple
from urllib.parse import parse_qs, urlsplit

import numpy as np
from PIL import Image

DATA = Path(__file__).parent.parent / "tests/fixtures/data"
GOLDEN = Path(__file__).parent.parent / "tests/fixtures/golden"
MEMBER, OUTSIDER = "Bearer member", "Bearer outsider"
NOW = "2026-11-10T00:00:00Z"


def uid(n: int) -> str:
    return f"00000000-0000-0000-0000-{n:012d}"


# entity route -> (entity id, asset id, file, content type)
FILES = {
    "cell-morphology": (uid(1), uid(101), DATA / "morphology.swc", "application/swc"),
    "electrical-cell-recording": (uid(2), uid(102), DATA / "correct_trace.nwb", "application/nwb"),
    "ion-channel-recording": (
        uid(3),
        uid(103),
        DATA / "ion_channel_recording.nwb",
        "application/nwb",
    ),
    "single-neuron-simulation": (
        uid(4),
        uid(104),
        DATA / "simulation_config.json",
        "application/json",
    ),
    "single-neuron-synaptome-simulation": (
        uid(5),
        uid(105),
        DATA / "simulation_config.json",
        "application/json",
    ),
    "validation-result": (uid(6), uid(106), GOLDEN / "ephys_dpi100.png", "image/png"),
}
EMODEL = uid(7)  # the model whose "thumbnail" validation result is uid(6)


def asset_row(route: str) -> dict[str, object]:
    _, asset_id, path, content_type = FILES[route]
    size = path.stat().st_size
    return {
        "id": asset_id,
        "path": path.name,
        "full_path": path.name,
        "is_directory": False,
        "content_type": content_type,
        "size": size,
        "sha256_digest": None,
        "meta": {},
        "status": "created",
    }


def page(rows: list[dict[str, object]]) -> dict[str, object]:
    return {"data": rows, "pagination": {"page": 1, "page_size": 100, "total_items": len(rows)}}


class Handler(BaseHTTPRequestHandler):
    """entitycore for MEMBER only (others get 404, as entitycore answers)."""

    port = 0

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - the base's name
        """Quiet."""

    def _send(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: object) -> None:
        self._send(200, json.dumps(data).encode(), {"Content-Type": "application/json"})

    def do_GET(self) -> None:  # noqa: PLR0911 - one branch per entitycore route
        """Asset metadata, downloads, files and the validation-result lookups."""
        url = urlsplit(self.path)
        parts = url.path.strip("/").split("/")
        if parts[0] == "storage":
            return self._send(200, FILES[parts[1]][2].read_bytes())
        if self.headers.get("Authorization") != MEMBER:
            return self._send(404, b'{"error_code":"ENTITY_NOT_FOUND"}')
        if url.path == "/validation-result":
            query = parse_qs(url.query)
            if query.get("validated_entity_id") != [EMODEL] or query.get("name") != ["thumbnail"]:
                return self._json(page([]))
            return self._json(
                page(
                    [
                        {
                            "id": FILES["validation-result"][0],
                            "name": "thumbnail",
                            "passed": True,
                            "validated_entity_id": EMODEL,
                            "creation_date": NOW,
                            "update_date": NOW,
                        }
                    ]
                )
            )
        route = parts[0]
        if route not in FILES or parts[1] != FILES[route][0]:
            return self._send(404)
        match parts[2:]:
            case ["assets"]:
                return self._json(page([asset_row(route)]))
            case ["assets", asset_id] if asset_id == FILES[route][1]:
                return self._json(asset_row(route))
            case ["assets", asset_id, "download"] if asset_id == FILES[route][1]:
                location = f"http://host.docker.internal:{self.port}/storage/{route}?sig=x"
                return self._send(307, headers={"Location": location})
        return self._send(404)


class Case(NamedTuple):
    """One request: its name, path and token, and whether a thumbnail is expected."""

    name: str
    path: str
    token: str | None = MEMBER
    image: bool = True  # a thumbnail is expected


def query(route: str, extra: str = "") -> str:
    entity_id, asset_id, _, _ = FILES[route]
    return f"/core/{route}/preview?entity_id={entity_id}&asset_id={asset_id}{extra}"


CASES = [
    # Ephys first: the old code drew it a few pixels differently after a morphology in the
    # same process (measured 2026-11-10).
    Case("ephys dpi=100 png", query("electrical-cell-recording", "&dpi=100")),
    Case("ephys default webp", query("electrical-cell-recording", "&format=webp")),
    Case("morphology default png", query("cell-morphology")),
    Case("morphology dpi=100 webp", query("cell-morphology", "&dpi=100&format=webp")),
    Case("morphology dpi=400", query("cell-morphology", "&dpi=400")),
    Case("ion channel dpi=100", query("ion-channel-recording", "&dpi=100")),
    Case("ion channel webp", query("ion-channel-recording", "&format=webp")),
    Case("simulation stimulus", query("single-neuron-simulation", "&target=stimulus")),
    Case(
        "simulation 300x200 webp",
        query("single-neuron-simulation", "&target=simulation&w=300&h=200&format=webp"),
    ),
    Case(
        "synaptome simulation stimulus",
        query("single-neuron-synaptome-simulation", "&target=stimulus"),
    ),
    Case("model trace", f"/core/model-trace/preview?entity_id={EMODEL}"),
    Case("health", "/health", token=None, image=False),
    # Error cases: the new service changed these on purpose.
    Case("no token", query("cell-morphology", "&dpi=150"), token=None, image=False),
    Case("outsider, not cached", query("cell-morphology", "&dpi=200"), token=OUTSIDER, image=False),
    Case("dpi out of range", query("cell-morphology", "&dpi=5"), image=False),
    Case("simulation without target", query("single-neuron-simulation"), image=False),
    Case(
        "unknown entity type",
        "/core/not-a-type/preview?entity_id=x&asset_id=y&target=stimulus",
        image=False,
    ),
    Case(
        "model trace, no validation", f"/core/model-trace/preview?entity_id={uid(9)}", image=False
    ),
    Case(
        "unknown asset",
        f"/core/cell-morphology/preview?entity_id={uid(1)}&asset_id={uid(999)}",
        image=False,
    ),
]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(port: int, case: Case) -> tuple[int, str, bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
    headers = {"Authorization": case.token} if case.token else {}
    connection.request("GET", case.path, headers=headers)
    response = connection.getresponse()
    body = response.read()
    connection.close()
    return response.status, response.getheader("content-type", ""), body


def run(image: str, entitycore: int) -> list[tuple[int, str, bytes]]:
    port = free_port()
    name = f"parity-{port}"
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
                if get(port, Case("health", "/health", token=None))[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(0.5)
        return [get(port, case) for case in CASES]
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)


def pixels(body: bytes) -> np.ndarray | None:
    try:
        return np.asarray(Image.open(io.BytesIO(body)).convert("RGBA"))
    except OSError:
        return None


def summary(status: int, body: bytes) -> str:
    try:
        data = json.loads(body)
    except ValueError:
        return f"{status} ({len(body)} bytes)"
    code = data.get("code") or data.get("error_code") or ""
    return f"{status} {code}".strip()


def main() -> int:
    old_image, new_image = sys.argv[1], sys.argv[2]
    server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)  # noqa: S104 - the containers reach it
    Handler.port = server.server_port
    threading.Thread(target=server.serve_forever, daemon=True).start()
    old, new = run(old_image, server.server_port), run(new_image, server.server_port)
    server.shutdown()
    lost = 0
    print(f"{'case':34s} {'old':26s} {'new':26s} result")
    for case, (os_, ot, ob), (ns, nt, nb) in zip(CASES, old, new, strict=True):
        if case.image:
            a, b = pixels(ob), pixels(nb)
            same = (
                os_ == ns == 200
                and ot == nt
                and a is not None
                and b is not None
                and a.shape == b.shape
                and bool((a == b).all())
            )
            result = "same image" if same else "DIFFERENT"
            lost += not same
            print(f"{case.name:34s} {f'{os_} {ot}':26s} {f'{ns} {nt}':26s} {result}")
        else:
            print(f"{case.name:34s} {summary(os_, ob):26s} {summary(ns, nb):26s} -")
    print(
        f"\n{lost} thumbnail case(s) differ"
        if lost
        else "\nevery thumbnail case gives the same image"
    )
    return 1 if lost else 0


if __name__ == "__main__":
    sys.exit(main())
