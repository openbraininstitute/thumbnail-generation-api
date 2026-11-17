"""Cell morphology (SWC) → a 2D projection of the neuron, no axes."""

import io

import neurom as nm
from neurom.view import matplotlib_impl

from app.domain.preview import RenderSpec
from app.rendering.common import encode, new_figure, parsed, text_of

WHITE_SPACE = 0.05


def render(content: bytes, spec: RenderSpec) -> bytes:
    """Draw the morphology in ``content`` (an SWC file).

    Raises:
        DomainError: ``ASSET_UNREADABLE`` when the file is not a readable SWC morphology.
    """
    morphology = parsed(
        lambda: nm.load_morphology(io.StringIO(text_of(content)), reader="swc"), "SWC"
    )
    fig, ax = new_figure()
    matplotlib_impl.plot_morph(morphology, ax)
    ax.set_title("")
    ax.set_aspect("equal")
    ax.set_frame_on(False)
    ax.xaxis.set_visible(False)
    ax.yaxis.set_visible(False)
    x, y, width, height = ax.dataLim.bounds
    ax.set_xlim(x - WHITE_SPACE, x + width + WHITE_SPACE)
    ax.set_ylim(y - WHITE_SPACE, y + height + WHITE_SPACE)
    fig.set_layout_engine("tight")
    return encode(fig, spec.dpi, spec.image_format)
