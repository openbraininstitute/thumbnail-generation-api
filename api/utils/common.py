from typing import Union
from matplotlib.figure import Figure
import io


def get_buffer(fig: Figure, dpi: Union[int, None]) -> io.BytesIO:
    """
    Creates a file buffer from a FigureBase object.

    Args:
        - fig: the matplotlib fibure
        - dpi: optional parameter to set the dpi of the image
    Returns:
        The buffer in bytes
    """
    buffer = io.BytesIO()

    fig.savefig(buffer, dpi=dpi, format="png")

    buffer.seek(0)

    return buffer
