"""``/_access``: the route up to its access check, then 204 or 403."""

from uuid import uuid4

import pytest

from app.api.access import PREFIX
from app.domain.errors import ErrorCode
from app.domain.preview import EntityRoute
from app.settings import ApiSettings, RenderSettings, Settings

from tests.support import DATA, OUTSIDER, FakeEntityCore, bearer, client

SWC = (DATA / "morphology.swc").read_bytes()
MORPHOLOGY = "/core/cell-morphology/preview"


@pytest.fixture
def fake() -> FakeEntityCore:
    return FakeEntityCore()


async def test_a_reader_gets_204_and_the_images_etag_without_a_download(
    fake: FakeEntityCore,
) -> None:
    entity, asset = fake.add(EntityRoute.CellMorphology, SWC)
    params = {"entity_id": str(entity), "asset_id": str(asset), "dpi": "100"}
    async with client(fake) as http:
        gate = await http.get(PREFIX + MORPHOLOGY, params=params, headers=bearer())
        image = await http.get(MORPHOLOGY, params=params, headers=bearer())
        other = await http.get(
            PREFIX + MORPHOLOGY, params={**params, "dpi": "50"}, headers=bearer()
        )
    assert gate.status_code == 204
    assert gate.content == b""
    assert gate.headers["etag"] == image.headers["etag"]  # nginx's cache key
    assert other.headers["etag"] != gate.headers["etag"]
    assert fake.content_calls == 1  # the image's: the check downloads nothing


@pytest.mark.parametrize(
    ("headers", "params", "refusal"),
    [
        (bearer(OUTSIDER), {}, None),  # entitycore: 404
        ({}, {}, None),  # no token: 401
        (bearer(), {"dpi": "5"}, None),  # bad input: 422
        (bearer(), {}, ErrorCode.Unauthenticated),  # entitycore refused the token
        (bearer(), {}, ErrorCode.EntitycoreUnavailable),  # 503: no answer is a "no"
    ],
)
async def test_everything_else_is_403(
    fake: FakeEntityCore, headers: dict[str, str], params: dict[str, str], refusal: ErrorCode | None
) -> None:
    entity, asset = fake.add(EntityRoute.CellMorphology, SWC)
    fake.refusal = refusal
    query = {"entity_id": str(entity), "asset_id": str(asset), **params}
    async with client(fake) as http:
        gate = await http.get(PREFIX + MORPHOLOGY, params=query, headers=headers)
    assert gate.status_code == 403
    assert fake.content_calls == 0


async def test_the_gate_follows_the_base_path_and_every_route(fake: FakeEntityCore) -> None:
    result_id, asset = fake.add(EntityRoute.ValidationResult, b"png", content_type="image/png")
    model = uuid4()
    fake.model_traces[model] = (result_id, asset)
    based = Settings(api=ApiSettings(base_path="/api/thumbs"), render=RenderSettings())
    async with client(fake, based) as http:
        gate = await http.get(
            f"{PREFIX}/api/thumbs/core/model-trace/preview",
            params={"entity_id": str(model)},
            headers=bearer(),
        )
        unknown = await http.get(f"{PREFIX}/api/thumbs/nothing-here", headers=bearer())
    assert gate.status_code == 204
    assert gate.headers["etag"].startswith('"')
    assert unknown.status_code == 403
