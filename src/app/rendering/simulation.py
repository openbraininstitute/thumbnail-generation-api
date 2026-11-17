"""Single-neuron simulation result (JSON) → the stimulus or the first recording.

Drawn with plotly + kaleido (a bundled headless Chromium), so the images stay the same.
"""

import io
import json

import plotly.graph_objects as go
from pydantic import BaseModel

from app.domain.errors import ErrorCode
from app.domain.guards import ensure
from app.domain.preview import RenderSpec
from app.rendering.common import parsed, text_of

MARGIN = 4


class PlotData(BaseModel):
    """One plotly trace (not ``Value``: extra keys are ignored)."""

    x: list[float]
    y: list[float]
    type: str = "scatter"
    name: str


class SimulationResult(BaseModel):
    """The simulation file: the stimulus traces, and recordings by name."""

    stimulus: list[PlotData]
    simulation: dict[str, list[PlotData]]


def render(content: bytes, spec: RenderSpec) -> bytes:
    """Draw ``spec.target`` (stimulus, or the first simulation recording) of ``content``.

    Raises:
        DomainError: ``ASSET_UNREADABLE`` for a file that is not a simulation result;
            ``PLOT_DATA_NOT_FOUND`` when it has nothing for the target.
    """
    result = parsed(lambda: SimulationResult(**json.loads(text_of(content))), "simulation")
    data = (
        result.stimulus if spec.target == "stimulus" else next(iter(result.simulation.values()), [])
    )
    ensure(data, ErrorCode.PlotDataNotFound, f"The simulation file has no {spec.target} data")
    fig = go.Figure(
        data=[{"x": d.x, "y": d.y, "type": d.type, "name": d.name} for d in data],
        layout={"showlegend": False, "margin": dict.fromkeys("trlb", MARGIN)},
    )
    buffer = io.BytesIO()
    fig.write_image(buffer, format=spec.image_format.value, width=spec.width, height=spec.height)
    return buffer.getvalue()
