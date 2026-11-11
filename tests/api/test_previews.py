"""The preview routes over a fake entitycore: access, caching, conditional requests, errors."""

from uuid import UUID, uuid4

import pytest

from app.domain.errors import ErrorCode
from app.domain.preview import Asset, Caller, EntityRoute

from tests.support import (
    DATA,
    GOLDEN,
    OUTSIDER,
    FakeEntityCore,
    bearer,
    client,
    same_pixels,
)

SWC = (DATA / "morphology.swc").read_bytes()
MORPHOLOGY = "/core/cell-morphology/preview"


@pytest.fixture
def fake() -> FakeEntityCore:
    return FakeEntityCore()


def query(entity_id: object, asset_id: object, **extra: object) -> dict[str, str]:
    return {
        "entity_id": str(entity_id),
        "asset_id": str(asset_id),
        **{k: str(v) for k, v in extra.items()},
    }


async def test_morphology_preview_is_the_old_image(fake: FakeEntityCore) -> None:
    entity, asset = fake.add(EntityRoute.CellMorphology, SWC)
    async with client(fake) as http:
        response = await http.get(
            MORPHOLOGY, params=query(entity, asset, dpi=100, format="webp"), headers=bearer()
        )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    assert response.headers["cache-control"] == "private, max-age=3600"
    assert response.headers["etag"].startswith('"')
    assert same_pixels(response.content, (GOLDEN / "morphology_dpi100.webp").read_bytes())


async def test_private_image_is_refused_to_an_outsider_and_without_token(
    fake: FakeEntityCore,
) -> None:
    entity, asset = fake.add(EntityRoute.CellMorphology, SWC)
    async with client(fake) as http:
        member = await http.get(MORPHOLOGY, params=query(entity, asset), headers=bearer())
        outsider = await http.get(MORPHOLOGY, params=query(entity, asset), headers=bearer(OUTSIDER))
        anonymous = await http.get(MORPHOLOGY, params=query(entity, asset))
    assert member.status_code == 200
    assert outsider.status_code == 404
    assert outsider.json()["code"] == "ASSET_NOT_FOUND"
    assert outsider.headers["content-type"] == "application/problem+json"
    assert anonymous.status_code == 401
    assert anonymous.headers["www-authenticate"] == "Bearer"


async def test_current_browser_copy_gets_304_without_download(fake: FakeEntityCore) -> None:
    entity, asset = fake.add(EntityRoute.CellMorphology, SWC)
    async with client(fake) as http:
        etag = (await http.get(MORPHOLOGY, params=query(entity, asset), headers=bearer())).headers[
            "etag"
        ]
        again = await http.get(
            MORPHOLOGY, params=query(entity, asset), headers=bearer(**{"If-None-Match": etag})
        )
        refused = await http.get(
            MORPHOLOGY,
            params=query(entity, asset),
            headers=bearer(OUTSIDER, **{"If-None-Match": etag}),
        )
    assert again.status_code == 304
    assert again.content == b""
    assert again.headers["etag"] == etag
    assert (fake.asset_calls, fake.content_calls) == (3, 1)  # every request checked, one download
    assert refused.status_code == 404  # a known ETag is no way around the access check


async def test_etag_changes_with_the_parameters(fake: FakeEntityCore) -> None:
    entity, asset = fake.add(EntityRoute.CellMorphology, SWC)
    async with client(fake) as http:
        png = await http.get(MORPHOLOGY, params=query(entity, asset), headers=bearer())
        webp = await http.get(
            MORPHOLOGY, params=query(entity, asset, format="webp"), headers=bearer()
        )
    assert png.headers["etag"] != webp.headers["etag"]


@pytest.mark.parametrize(
    ("refusal", "status"),
    [
        (ErrorCode.Unauthenticated, 401),
        (ErrorCode.Forbidden, 403),
        (ErrorCode.AssetNotReady, 409),
        (ErrorCode.EntitycoreUnavailable, 503),
    ],
)
async def test_entitycore_refusals_keep_their_status(
    fake: FakeEntityCore, refusal: ErrorCode, status: int
) -> None:
    """Each refusal keeps its own status, not a blanket 400."""
    entity, asset = fake.add(EntityRoute.CellMorphology, SWC)
    fake.refusal = refusal
    async with client(fake) as http:
        response = await http.get(MORPHOLOGY, params=query(entity, asset), headers=bearer())
    assert response.status_code == status
    assert response.json()["code"] == refusal.value


async def test_unreadable_asset_is_422(fake: FakeEntityCore) -> None:
    entity, asset = fake.add(EntityRoute.ElectricalCellRecording, b"not an nwb file")
    async with client(fake) as http:
        response = await http.get(
            "/core/electrical-cell-recording/preview", params=query(entity, asset), headers=bearer()
        )
    assert response.status_code == 422
    assert response.json()["code"] == "ASSET_UNREADABLE"


async def test_simulation_needs_a_token(fake: FakeEntityCore) -> None:
    """A request without a token is refused before entitycore is called."""
    entity, asset = fake.add(EntityRoute.SingleNeuronSimulation, b"{}")
    async with client(fake) as http:
        response = await http.get(
            "/core/single-neuron-simulation/preview", params=query(entity, asset, target="stimulus")
        )
    assert response.status_code == 401
    assert fake.asset_calls == 0


@pytest.mark.parametrize(
    ("path", "params"),
    [
        (MORPHOLOGY, {"dpi": 5}),
        (MORPHOLOGY, {"format": "gif"}),
        ("/core/single-neuron-simulation/preview", {"target": "stimulus", "w": 100_000}),
        ("/core/not-a-type/preview", {"target": "stimulus"}),
    ],
)
async def test_bad_input_is_422_problem(
    fake: FakeEntityCore, path: str, params: dict[str, object]
) -> None:
    async with client(fake) as http:
        response = await http.get(path, params=query(uuid4(), uuid4(), **params), headers=bearer())
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "BAD_USER_INPUT"
    assert body["errors"]


async def test_model_trace_is_the_stored_png(fake: FakeEntityCore) -> None:
    png = (GOLDEN / "ephys_dpi100.png").read_bytes()
    result_id, asset = fake.add(EntityRoute.ValidationResult, png, content_type="image/png")
    model = uuid4()
    fake.model_traces[model] = (result_id, asset)
    async with client(fake) as http:
        found = await http.get(
            "/core/model-trace/preview", params={"entity_id": str(model)}, headers=bearer()
        )
        missing = await http.get(
            "/core/model-trace/preview", params={"entity_id": str(uuid4())}, headers=bearer()
        )
    assert found.status_code == 200
    assert found.headers["content-type"] == "image/png"
    assert found.content == png
    assert missing.status_code == 404
    assert missing.json()["code"] == "VALIDATION_RESULT_NOT_FOUND"


async def test_health(fake: FakeEntityCore) -> None:
    async with client(fake) as http:
        response = await http.get("/health")
    assert response.json() == {"status": "OK"}
    assert response.headers["x-request-id"]


async def test_ion_channel_preview_is_the_old_image(fake: FakeEntityCore) -> None:
    entity, asset = fake.add(
        EntityRoute.IonChannelRecording, (DATA / "ion_channel_recording.nwb").read_bytes()
    )
    async with client(fake) as http:
        response = await http.get(
            "/core/ion-channel-recording/preview",
            params=query(entity, asset, dpi=100),
            headers=bearer(),
        )
    assert response.status_code == 200
    assert same_pixels(response.content, (GOLDEN / "ion_channel_dpi100.png").read_bytes())


async def test_unknown_route_is_a_404_problem(fake: FakeEntityCore) -> None:
    async with client(fake) as http:
        response = await http.get("/nothing-here", headers=bearer())
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


class CrashingEntityCore(FakeEntityCore):
    async def asset(
        self, caller: Caller, route: EntityRoute, entity_id: UUID, asset_id: UUID
    ) -> Asset:
        message = "secret internals"
        raise RuntimeError(message)


async def test_a_crash_is_a_masked_500() -> None:
    fake = CrashingEntityCore()
    async with client(fake) as http:
        response = await http.get(MORPHOLOGY, params=query(uuid4(), uuid4()), headers=bearer())
    assert response.status_code == 500
    assert response.json() == {
        "type": "about:blank",
        "title": "Internal",
        "status": 500,
        "detail": "Internal error",
        "code": "INTERNAL",
    }


async def test_server_timing_names_each_phase(fake: FakeEntityCore) -> None:
    entity, asset = fake.add(EntityRoute.CellMorphology, SWC)
    async with client(fake) as http:
        drawn = await http.get(MORPHOLOGY, params=query(entity, asset), headers=bearer())
        refused = await http.get(MORPHOLOGY, params=query(entity, asset), headers=bearer(OUTSIDER))
    names = [part.split(";")[0].strip() for part in drawn.headers["server-timing"].split(",")]
    assert names == ["meta", "queue", "download", "render_wait", "render", "app"]
    durations = [float(part.split("dur=")[1]) for part in drawn.headers["server-timing"].split(",")]
    assert durations[-1] >= max(durations[:-1])  # the whole request covers every phase
    assert refused.headers["server-timing"].startswith("meta;dur=")  # errors are timed too
