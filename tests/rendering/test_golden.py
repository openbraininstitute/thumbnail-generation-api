"""Same output: every renderer draws the pixels the old service drew.

The golden images were made by the old code before it was removed: morphology and ion channel on
macOS (the same pixels as on Linux), ephys and simulation in the old production image (Linux):
ephys because matplotlib 3.11 changed its text layout (matplotlib is pinned to 3.10, see
pyproject.toml), simulation because Chromium draws text per platform (compared in the Docker image
by scripts/smoke.py). `make parity` compares the old and new images on every route. Pixels are
compared, not bytes: an encoder version may pack the same pixels differently.
"""

import io

import pytest
from PIL import Image as PILImage

from app.domain.preview import EntityRoute, ImageFormat, RenderSpec
from app.rendering import RENDERERS

from tests.support import DATA, GOLDEN, same_pixels

SWC = (DATA / "morphology.swc").read_bytes()
NWB = (DATA / "correct_trace.nwb").read_bytes()
ION = (DATA / "ion_channel_recording.nwb").read_bytes()
SIM = (DATA / "simulation_config.json").read_bytes()
PNG, WEBP = ImageFormat.PNG, ImageFormat.WEBP

CASES = [
    ("morphology_default.png", EntityRoute.CellMorphology, SWC, RenderSpec(image_format=PNG)),
    (
        "morphology_dpi100.webp",
        EntityRoute.CellMorphology,
        SWC,
        RenderSpec(dpi=100, image_format=WEBP),
    ),
    ("ephys_dpi100.png", EntityRoute.ElectricalCellRecording, NWB, RenderSpec(dpi=100)),
    ("ephys_default.webp", EntityRoute.ElectricalCellRecording, NWB, RenderSpec(image_format=WEBP)),
    ("ion_channel_dpi100.png", EntityRoute.IonChannelRecording, ION, RenderSpec(dpi=100)),
]


@pytest.mark.parametrize(("golden", "route", "content", "spec"), CASES)
def test_renders_the_old_pixels(
    golden: str, route: EntityRoute, content: bytes, spec: RenderSpec
) -> None:
    image = RENDERERS[route](content, spec)
    assert image[:4] in {b"\x89PNG", b"RIFF"}
    assert same_pixels(image, (GOLDEN / golden).read_bytes())


@pytest.mark.kaleido
@pytest.mark.parametrize(
    ("route", "spec", "size"),
    [
        (EntityRoute.SingleNeuronSimulation, RenderSpec(target="stimulus"), (700, 500)),
        (
            EntityRoute.SingleNeuronSynaptomeSimulation,
            RenderSpec(target="simulation", width=300, height=200, image_format=WEBP),
            (300, 200),
        ),
    ],
)
def test_simulation_draws_an_image_of_the_asked_size(
    route: EntityRoute, spec: RenderSpec, size: tuple[int, int]
) -> None:
    """Pixels: in the Docker image (scripts/smoke.py), as Chromium's text depends on the OS."""
    image = PILImage.open(io.BytesIO(RENDERERS[route](SIM, spec)))
    assert image.size == size
    assert image.format == spec.image_format.value.upper()
