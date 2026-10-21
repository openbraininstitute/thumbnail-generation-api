"""
Module: figure.py

Thread-safe matplotlib figure construction.

The preview endpoints offload rendering to the Starlette/anyio worker
threadpool (see :mod:`api.utils.offload`), so multiple renders can run on
different threads at the same time. ``matplotlib.pyplot`` keeps global,
process-wide state (the current figure, the figure manager registry) and is
**not** thread-safe: concurrent ``plt.subplots`` / ``plt.figure`` / ``plt.close``
calls can interleave and corrupt each other's figures, raise spurious errors or
leak memory.

Using the object-oriented API (:class:`matplotlib.figure.Figure` with an
explicit :class:`~matplotlib.backends.backend_agg.FigureCanvasAgg`) touches no
global state, so each render is fully isolated and safe to run concurrently
without a lock.
"""

from matplotlib.axes import Axes
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure


def new_figure(figsize: tuple[float, float] | None = None) -> tuple[Figure, Axes]:
    """Create a standalone ``(Figure, Axes)`` without using pyplot.

    The figure is backed by an Agg canvas so :meth:`Figure.savefig` works, and
    it is not registered in pyplot's global figure manager, making it safe to
    build and render from worker threads concurrently.

    Args:
        figsize: Optional ``(width, height)`` in inches.

    Returns:
        A tuple of the new figure and a single subplot axes.
    """
    fig = Figure(figsize=figsize)
    # Attach an Agg canvas so savefig() can rasterize without pyplot.
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(1, 1, 1)
    return fig, ax
