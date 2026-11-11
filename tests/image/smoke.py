"""Draw every golden case inside the Docker image and compare pixels: ``make smoke``.

The real check of the deployed artifact: slim base, read-only root, kaleido's Chromium. The
simulation golden files come from the old production image (Linux); Chromium draws text with the
platform's fonts, so those two cases are compared here and not in pytest on a laptop.
"""

import io
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from app.domain.preview import EntityRoute, ImageFormat, RenderSpec
from app.rendering import RENDERERS

ROOT = Path(sys.argv[1])
CASES = {
    "morphology_dpi100.webp": (
        EntityRoute.CellMorphology,
        "morphology.swc",
        RenderSpec(dpi=100, image_format=ImageFormat.WEBP),
    ),
    "ephys_dpi100.png": (
        EntityRoute.ElectricalCellRecording,
        "correct_trace.nwb",
        RenderSpec(dpi=100),
    ),
    "ion_channel_dpi100.png": (
        EntityRoute.IonChannelRecording,
        "ion_channel_recording.nwb",
        RenderSpec(dpi=100),
    ),
    "simulation_stimulus.png": (
        EntityRoute.SingleNeuronSimulation,
        "simulation_config.json",
        RenderSpec(target="stimulus"),
    ),
    "simulation_simulation_300x200.webp": (
        EntityRoute.SingleNeuronSynaptomeSimulation,
        "simulation_config.json",
        RenderSpec(target="simulation", width=300, height=200, image_format=ImageFormat.WEBP),
    ),
}


def pixels(data: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(data)).convert("RGBA"))


failed = False
for golden, (route, data, spec) in CASES.items():
    image = RENDERERS[route]((ROOT / "data" / data).read_bytes(), spec)
    same = bool((pixels(image) == pixels((ROOT / "golden" / golden).read_bytes())).all())
    failed |= not same
    print(f"{golden:28s} {'same pixels' if same else 'DIFFERENT'}")
sys.exit(1 if failed else 0)
