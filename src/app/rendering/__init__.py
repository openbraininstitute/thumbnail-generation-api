"""Renderers: asset bytes in, image bytes out, on a worker thread (Strategy registry).

A new entity type is one module and one line in :data:`RENDERERS`. Model traces are stored PNGs.
"""

from collections.abc import Callable, Mapping

from app.domain.preview import EntityRoute, ImageFormat, RenderSpec
from app.rendering import ephys, ion_channel, morphology, simulation
from app.rendering.common import encode, new_figure

type Render = Callable[[bytes, RenderSpec], bytes]

RENDERERS: Mapping[EntityRoute, Render] = {
    EntityRoute.CellMorphology: morphology.render,
    EntityRoute.ElectricalCellRecording: ephys.render,
    EntityRoute.IonChannelRecording: ion_channel.render,
    EntityRoute.SingleNeuronSimulation: simulation.render,
    EntityRoute.SingleNeuronSynaptomeSimulation: simulation.render,
}


def warm_up() -> None:
    """Draw one tiny figure at start-up, so the first caller does not pay for the font cache."""
    fig, ax = new_figure()
    ax.plot([0, 1], [0, 1])
    encode(fig, None, ImageFormat.PNG)
