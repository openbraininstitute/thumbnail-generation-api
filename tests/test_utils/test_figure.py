"""Tests for api.utils.figure.

These guard the thread-safety of the rendering path: preview endpoints offload
rendering to a worker threadpool, so figures must be built and rasterized
concurrently without the global pyplot state that is not thread-safe.
"""

import io
from concurrent.futures import ThreadPoolExecutor

from matplotlib.figure import Figure

from api.utils.figure import new_figure


def test_new_figure_returns_standalone_figure():
    """new_figure returns a Figure with an attached canvas and one axes."""
    fig, ax = new_figure(figsize=(4, 3))

    assert isinstance(fig, Figure)
    # Canvas must be attached so savefig works without pyplot.
    assert fig.canvas is not None
    assert ax in fig.axes
    assert tuple(fig.get_size_inches()) == (4, 3)


def test_new_figure_not_registered_in_pyplot():
    """Figures created via new_figure must not touch pyplot's global registry."""
    import matplotlib.pyplot as plt  # noqa: PLC0415

    before = set(plt.get_fignums())
    fig, _ax = new_figure()
    after = set(plt.get_fignums())

    # No new pyplot-managed figure should appear.
    assert before == after
    # Sanity: it still renders.
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    assert buf.getvalue()[:8] == b"\x89PNG\r\n\x1a\n"


def test_new_figure_concurrent_render_is_thread_safe():
    """Rendering many figures concurrently produces valid PNGs with no errors.

    With the old pyplot-based approach, concurrent plt.subplots/savefig/close
    calls on worker threads could interleave and corrupt each other. The OO
    Figure API must be safe to run in parallel.
    """

    def render(i: int) -> bytes:
        fig, ax = new_figure(figsize=(3, 2))
        ax.plot(range(100), [v * i for v in range(100)])
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100)
        return buf.getvalue()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(render, range(64)))

    assert len(results) == 64
    # Every render must have produced a valid, non-empty PNG.
    for png in results:
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        assert len(png) > 100
