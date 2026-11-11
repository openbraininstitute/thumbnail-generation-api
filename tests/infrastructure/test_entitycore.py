"""The entitycore adapter over a mock transport: headers, statuses, download, limits."""

import asyncio
from collections.abc import AsyncIterator, Callable
from uuid import UUID, uuid4

import httpx2
import pytest

from app.domain.errors import DomainError, ErrorCode
from app.domain.preview import Asset, Caller, EntityRoute
from app.infrastructure.entitycore import HttpEntityCore

BASE = "https://entitycore.test"
STORAGE = "https://storage.test/presigned?sig=secret"
CALLER = Caller(token="tok", virtual_lab_id=UUID(int=1), project_id=UUID(int=2))
ENTITY, ASSET_ID = uuid4(), uuid4()


def asset_row(asset_id: UUID = ASSET_ID, **extra: object) -> dict[str, object]:
    return {
        "id": str(asset_id),
        "content_type": "application/swc",
        "size": 5,
        "status": "created",
        "path": "m.swc",
        "sha256_digest": "ab",
        **extra,
    }


def adapter(
    handler: Callable[[httpx2.Request], httpx2.Response],
    max_bytes: int = 100,
    download_seconds: float = 60.0,
) -> tuple[HttpEntityCore, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def record(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request)

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(record))
    core = HttpEntityCore(
        client, base_url=BASE + "/", max_asset_bytes=max_bytes, download_seconds=download_seconds
    )
    return core, seen


async def test_asset_read_carries_the_callers_token_and_project() -> None:
    core, seen = adapter(lambda r: httpx2.Response(200, json=asset_row()))
    asset = await core.asset(CALLER, EntityRoute.CellMorphology, ENTITY, ASSET_ID)
    assert asset == Asset(id=ASSET_ID, content_type="application/swc", size=5, sha256_digest="ab")
    request = seen[0]
    assert str(request.url) == f"{BASE}/cell-morphology/{ENTITY}/assets/{ASSET_ID}"
    assert request.headers["authorization"] == "Bearer tok"
    assert request.headers["project-id"] == str(UUID(int=2))
    assert request.headers["virtual-lab-id"] == str(UUID(int=1))


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, ErrorCode.Unauthenticated),
        (403, ErrorCode.Forbidden),
        (404, ErrorCode.AssetNotFound),
        (409, ErrorCode.AssetNotReady),
        (422, ErrorCode.BadUserInput),
        (429, ErrorCode.EntitycoreUnavailable),
        (500, ErrorCode.EntitycoreUnavailable),
    ],
)
async def test_statuses_map_to_codes(status: int, code: ErrorCode) -> None:
    core, _ = adapter(lambda r: httpx2.Response(status, json={}))
    with pytest.raises(DomainError) as caught:
        await core.asset(CALLER, EntityRoute.CellMorphology, ENTITY, ASSET_ID)
    assert caught.value.code is code


async def test_network_failure_is_unavailable() -> None:
    def down(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    core, _ = adapter(down)
    with pytest.raises(DomainError) as caught:
        await core.asset(CALLER, EntityRoute.CellMorphology, ENTITY, ASSET_ID)
    assert caught.value.code is ErrorCode.EntitycoreUnavailable


def storage(body: bytes) -> Callable[[httpx2.Request], httpx2.Response]:
    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "storage.test":
            return httpx2.Response(200, content=body)
        return httpx2.Response(307, headers={"location": STORAGE})

    return handle


ASSET = Asset(id=ASSET_ID, content_type="application/swc", size=5)


async def test_download_follows_the_presigned_url_without_the_token() -> None:
    core, seen = adapter(storage(b"hello"))
    assert await core.content(CALLER, EntityRoute.CellMorphology, ENTITY, ASSET) == b"hello"
    assert seen[0].url.path.endswith(f"/assets/{ASSET_ID}/download")
    assert seen[0].headers["authorization"] == "Bearer tok"
    assert "authorization" not in seen[1].headers


async def test_download_over_the_limit_stops() -> None:
    core, _ = adapter(storage(b"x" * 50), max_bytes=10)
    with pytest.raises(
        DomainError
    ) as caught:  # the metadata said 5 bytes; the stream is checked too
        await core.content(CALLER, EntityRoute.CellMorphology, ENTITY, ASSET)
    assert caught.value.code is ErrorCode.AssetTooLarge
    big = ASSET.model_copy(update={"size": 11})
    with pytest.raises(DomainError) as caught:
        await core.content(CALLER, EntityRoute.CellMorphology, ENTITY, big)
    assert caught.value.code is ErrorCode.AssetTooLarge


async def test_empty_download_is_content_empty() -> None:
    core, _ = adapter(storage(b""))
    with pytest.raises(DomainError) as caught:
        await core.content(CALLER, EntityRoute.CellMorphology, ENTITY, ASSET)
    assert caught.value.code is ErrorCode.ContentEmpty


async def test_model_trace_finds_the_png_of_the_thumbnail_validation() -> None:
    result = uuid4()
    png_id = uuid4()

    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/validation-result":
            assert request.url.params["name"] == "thumbnail"
            assert request.url.params["validated_entity_id"] == str(ENTITY)
            return httpx2.Response(200, json={"data": [{"id": str(result)}], "pagination": {}})
        return httpx2.Response(
            200,
            json={
                "data": [
                    asset_row(uuid4(), content_type="text/plain"),
                    asset_row(png_id, content_type="image/png"),
                ]
            },
        )

    core, _ = adapter(handle)
    found_result, png = await core.model_trace(CALLER, ENTITY)
    assert (found_result, png.id) == (result, png_id)


async def test_model_trace_without_a_result() -> None:
    core, _ = adapter(lambda r: httpx2.Response(200, json={"data": []}))
    with pytest.raises(DomainError) as caught:
        await core.model_trace(CALLER, ENTITY)
    assert caught.value.code is ErrorCode.ValidationResultNotFound


async def test_a_non_web_download_location_is_not_followed() -> None:
    def handle(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(307, headers={"location": "file:///etc/passwd"})

    core, seen = adapter(handle)
    with pytest.raises(DomainError) as caught:
        await core.content(CALLER, EntityRoute.CellMorphology, ENTITY, ASSET)
    assert caught.value.code is ErrorCode.EntitycoreUnavailable
    assert len(seen) == 1  # the location was never requested


async def test_metadata_over_the_limit_is_refused_before_any_download() -> None:
    core, seen = adapter(lambda r: httpx2.Response(200, json=asset_row(size=11)), max_bytes=10)
    with pytest.raises(DomainError) as caught:
        await core.asset(CALLER, EntityRoute.CellMorphology, ENTITY, ASSET_ID)
    assert caught.value.code is ErrorCode.AssetTooLarge
    assert len(seen) == 1


async def test_a_slow_download_stops_at_the_deadline() -> None:
    async def trickle() -> AsyncIterator[bytes]:
        while True:  # each chunk is within httpx's per-read timeout; the whole is not
            yield b"x"
            await asyncio.sleep(0.01)

    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "storage.test":
            return httpx2.Response(200, content=trickle())
        return httpx2.Response(307, headers={"location": STORAGE})

    core, _ = adapter(handle, max_bytes=10**6, download_seconds=0.1)
    with pytest.raises(DomainError) as caught:
        await asyncio.wait_for(
            core.content(CALLER, EntityRoute.CellMorphology, ENTITY, ASSET), timeout=5
        )
    assert caught.value.code is ErrorCode.EntitycoreUnavailable


async def test_model_trace_uses_the_latest_thumbnail_validation() -> None:
    old, new = uuid4(), uuid4()
    rows = [
        {"id": str(old), "creation_date": "2026-01-01T00:00:00Z"},
        {"id": str(new), "creation_date": "2026-03-01T00:00:00Z"},
        {"id": str(uuid4()), "creation_date": "2026-02-01T00:00:00Z"},
    ]

    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/validation-result":
            return httpx2.Response(200, json={"data": rows})
        assert request.url.path == f"/validation-result/{new}/assets"
        return httpx2.Response(200, json={"data": [asset_row(content_type="image/png")]})

    core, _ = adapter(handle)
    found, _ = await core.model_trace(CALLER, ENTITY)
    assert found == new
