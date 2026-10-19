import io

from matplotlib.figure import Figure

from api.utils.image_format import ImageFormat, pil_kwargs_for


def get_buffer(
    fig: Figure, dpi: int | None, image_format: ImageFormat = ImageFormat.PNG
) -> io.BytesIO:
    """
    Creates a file buffer from a FigureBase object.

    Args:
        - fig: the matplotlib figure
        - dpi: optional parameter to set the dpi of the image
        - image_format: output image format (PNG by default, WebP supported)
    Returns:
        The buffer in bytes
    """
    buffer = io.BytesIO()

    # Per-format Pillow options (e.g. fast lossless PNG, lossless WebP) keep the
    # output lossless while minimizing encoding CPU and/or byte size.
    fig.savefig(
        buffer,
        dpi=dpi,
        format=image_format.value,
        pil_kwargs=pil_kwargs_for(image_format),
    )

    buffer.seek(0)

    return buffer
