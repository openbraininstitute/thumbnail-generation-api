"""Shared by renderers: a thread-safe figure, the encoder, the parse boundary.

Figures use the object API (``Figure`` + Agg), not ``pyplot``, which is not thread-safe.
"""

import io
from collections.abc import Callable
from typing import NoReturn

import matplotlib as mpl
from matplotlib.axes import Axes
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from app.domain.errors import DomainError, ErrorCode
from app.domain.guards import match_error
from app.domain.preview import ImageFormat

mpl.use("agg")  # neurom imports pyplot; on a server there is no display backend to pick

# PNG: fastest zlib level (much less CPU, a few bytes more). WebP: lossless keeps line art exact.
_PIL_KWARGS: dict[ImageFormat, dict[str, object]] = {
    ImageFormat.PNG: {"compress_level": 1},
    ImageFormat.WEBP: {"lossless": True},
}


def new_figure(figsize: tuple[float, float] | None = None) -> tuple[Figure, Axes]:
    """A standalone figure with one axes, not registered with pyplot (safe on any thread)."""
    fig = Figure(figsize=figsize)
    FigureCanvasAgg(fig)  # so savefig can rasterize without pyplot
    return fig, fig.add_subplot(1, 1, 1)


def encode(fig: Figure, dpi: int | None, image_format: ImageFormat) -> bytes:
    """The figure as image bytes; ``dpi=None`` is matplotlib's own resolution."""
    buffer = io.BytesIO()
    fig.savefig(
        buffer, dpi=dpi, format=image_format.value, pil_kwargs=dict(_PIL_KWARGS[image_format])
    )
    return buffer.getvalue()


def text_of(content: bytes) -> str:
    """The file as UTF-8 text; a bad byte is replaced, not fatal."""
    return content.decode("utf-8", errors="replace")


def parsed[T](parse: Callable[[], T], what: str) -> T:
    """Run ``parse``; any failure means the file is not the format this renderer reads.

    A ``DomainError`` raised by the parser (a missing NWB group) keeps its own message.

    Raises:
        DomainError: ``ASSET_UNREADABLE``.

    Examples:
        >>> parsed(lambda: int("7"), "number")
        7
        >>> try:
        ...     parsed(lambda: int("x"), "number")
        ... except DomainError as error:
        ...     error.code.value, error.message
        ('ASSET_UNREADABLE', 'The number file could not be read')
    """
    try:
        return parse()
    except Exception as error:  # noqa: BLE001 - any parser error; the table decides
        return match_error(
            error,
            {
                DomainError: _keep,
                Exception: lambda _: DomainError(
                    ErrorCode.AssetUnreadable, f"The {what} file could not be read"
                ),
            },
        )


def _keep(error: DomainError) -> NoReturn:
    """A parser's own ``DomainError`` (a missing NWB group) goes on with its message."""
    raise error


def unreadable(message: str) -> DomainError:
    """The error of a file that parses but lacks what the renderer needs."""
    return DomainError(ErrorCode.AssetUnreadable, message)
