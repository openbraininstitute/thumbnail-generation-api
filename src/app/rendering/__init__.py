"""Renderers: asset bytes in, image bytes out. Pure and synchronous; run on a worker thread.

One registry (Strategy pattern): a new entity type is one module with a ``render`` function and
one line in :data:`RENDERERS`, nothing else. Model traces are absent: entitycore stores them as
PNG files, which are sent as they are.
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
    """Draw one tiny figure: the first render of a process builds matplotlib's font cache.

    Moves that one-off cost (the old service measured it on the first request after a deploy)
    to start-up, off the first caller.
    """
    fig, ax = new_figure()
    ax.plot([0, 1], [0, 1])
    encode(fig, None, ImageFormat.PNG)
