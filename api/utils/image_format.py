"""
Module: image_format.py

Shared helpers for the output image format of generated thumbnails.

Thumbnails are line-art plots (morphologies, traces) which compress extremely
well. WebP (lossless) is typically ~5-10x smaller than PNG for this content
with no visible quality loss, which reduces both response size and the size of
objects held in the nginx cache. PNG remains the default so existing clients
are unaffected; clients opt into WebP via the ``format`` query parameter.
"""

from enum import Enum


class ImageFormat(str, Enum):
    """Supported output formats for generated thumbnails."""

    PNG = "png"
    WEBP = "webp"


# Media type returned in the HTTP response for each format.
_MEDIA_TYPES: dict[ImageFormat, str] = {
    ImageFormat.PNG: "image/png",
    ImageFormat.WEBP: "image/webp",
}

# Extra keyword arguments forwarded to Pillow via matplotlib's ``savefig``.
# - PNG: compress_level=1 is the fastest zlib level (lossless), trading a few
#   bytes for noticeably less encoding CPU.
# - WEBP: lossless keeps line art pixel-perfect; for sparse plots lossless and
#   lossy produce near-identical sizes, so we default to lossless.
_PIL_KWARGS: dict[ImageFormat, dict] = {
    ImageFormat.PNG: {"compress_level": 1},
    ImageFormat.WEBP: {"lossless": True},
}


def media_type_for(image_format: ImageFormat) -> str:
    """Return the HTTP media type for the given image format."""
    return _MEDIA_TYPES[image_format]


def pil_kwargs_for(image_format: ImageFormat) -> dict:
    """Return the Pillow savefig kwargs for the given image format."""
    return dict(_PIL_KWARGS[image_format])
