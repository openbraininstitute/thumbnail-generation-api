"""Unit tests for the image_format helper."""

from api.utils.image_format import (
    ImageFormat,
    media_type_for,
    pil_kwargs_for,
)


def test_media_type_for_png():
    assert media_type_for(ImageFormat.PNG) == "image/png"


def test_media_type_for_webp():
    assert media_type_for(ImageFormat.WEBP) == "image/webp"


def test_pil_kwargs_png_is_fast_lossless():
    assert pil_kwargs_for(ImageFormat.PNG) == {"compress_level": 1}


def test_pil_kwargs_webp_is_lossless():
    assert pil_kwargs_for(ImageFormat.WEBP) == {"lossless": True}


def test_pil_kwargs_returns_a_copy():
    """Callers must not be able to mutate the shared defaults."""
    kwargs = pil_kwargs_for(ImageFormat.PNG)
    kwargs["compress_level"] = 9
    assert pil_kwargs_for(ImageFormat.PNG) == {"compress_level": 1}


def test_image_format_values_are_lowercase_strings():
    assert ImageFormat.PNG.value == "png"
    assert ImageFormat.WEBP.value == "webp"
