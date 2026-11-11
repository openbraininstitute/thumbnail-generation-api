"""Ion channel recording (NWB) → every activation trace on one plot, one colour each, no axes.

Artifacts are smoothed (a point whose derivative is over twice the mean is replaced by the mean
of its neighbours, three passes) so they stay visible without crushing the scale of the plot.
The algorithm is the old ``api/tools/plot_ion_channel.py`` one, with the same results bit for bit;
only the per-sample Python loops are replaced by numpy (measured: the artifact loop was 86-90% of
the render for 20 000 samples, 910 ms for 30 traces). tests/rendering/test_ion_channel.py keeps the
old loops as the reference and compares on random recordings.
"""

import io
import statistics
from fractions import Fraction
from typing import Any, cast

import h5py
import numpy as np
from numpy.typing import NDArray
from palettable.cartocolors.sequential import TealGrn_7  # ty: ignore[import-not-found]

from app.domain.guards import match_error
from app.domain.preview import RenderSpec
from app.logs import get_logger
from app.rendering.common import encode, new_figure, parsed
from app.rendering.nwb import read_array

log = get_logger("render.ion_channel")

FIGSIZE = (6, 4)
SUSPICION = 2  # a derivative over twice the mean is an artifact
PASSES = 3  # empiric: does not remove artifacts fully, but enough to keep the scale


def read_activation(content: bytes) -> NDArray[Any]:
    """The activation currents (samples x traces) of the first repetition."""
    with h5py.File(io.BytesIO(content), "r") as h5:
        repetition = cast(
            "h5py.Group", h5["acquisition/timeseries/Activation/repetitions/repetition1"]
        )
        return read_array(repetition, "data", np.float32)


def compute_derivatives(array: NDArray[np.float32]) -> NDArray[np.float32]:
    """Per point, the larger absolute difference to its two neighbours (0 past each end).

    The same float32 subtractions as the old per-sample loop, on whole arrays.

    Examples:
        >>> compute_derivatives(np.array([0, 1, 3, 2], dtype=np.float32)).tolist()
        [1.0, 2.0, 2.0, 1.0]
    """
    step = np.abs(np.diff(array))
    zero = np.zeros(1, dtype=array.dtype)
    return np.maximum(np.concatenate((zero, step)), np.concatenate((step, zero)))


def exact_mean(values: NDArray[np.float32]) -> np.float32:
    """``statistics.mean(list(values))`` for float32 values, without a Fraction per value.

    statistics.mean adds the values exactly (as fractions), divides by their count and converts
    the result to float32. Here a float32 is written k * 2**e with an integer k below 2**24; the k
    of each exponent are added in float64 (exact: below 2**53 for fewer than 2**29 values), then
    the few sums are joined as one exact integer, and the same final division and conversion
    follow.

    Examples:
        >>> import statistics
        >>> values = np.array([0.1, 3e-8, 2.5, 7e5], dtype=np.float32)
        >>> bool(exact_mean(values) == statistics.mean(list(values)))
        True
    """
    if not np.isfinite(values).all() or values.size >= 2**29:
        # The rare case keeps the original code path (float32 items: statistics returns float32).
        return np.float32(statistics.mean(list(values)))  # ty: ignore[invalid-argument-type]
    mantissa, exponent = np.frexp(values)
    k = np.ldexp(mantissa, 24)  # whole numbers, |k| < 2**24 (float32 has a 24-bit significand)
    exponent = exponent.astype(np.int64) - 24
    lowest = int(exponent.min())
    sums = np.bincount(exponent - lowest, weights=k.astype(np.float64))
    total = sum(int(part) << shift for shift, part in enumerate(sums) if part)
    exact = Fraction(total) * Fraction(2) ** lowest
    return np.float32(exact / len(values))  # as statistics._convert(value, float32)


def remove_suspicious_indexes(array: NDArray[Any], indexes: list[int]) -> NDArray[Any]:
    """Replace each point at ``indexes`` by the mean of its neighbours, in place, in order."""
    count = len(array)
    for index in indexes:
        before = max(0, index - 1)
        after = min(count - 1, index + 1)
        array[index] = (array[before] + array[after]) / 2
    return array


def remove_artifacts(data: NDArray[Any], index: int) -> NDArray[Any]:
    """Trace ``index`` of ``data`` with its artifacts smoothed (in place)."""
    array = data[:, index]
    try:
        for _ in range(PASSES):
            derivatives = compute_derivatives(array)
            threshold = exact_mean(derivatives) * SUSPICION
            suspicious = np.flatnonzero(derivatives > threshold).tolist()
            if not suspicious:
                return array
            # Stays a loop: each point uses its neighbours as already replaced, in order.
            remove_suspicious_indexes(array, suspicious)
    except Exception as error:  # noqa: BLE001 - best effort: the trace is drawn unsmoothed
        return match_error(error, {Exception: lambda e: _unsmoothed(array, index, e)})
    return array


def _unsmoothed(array: NDArray[Any], index: int, error: Exception) -> NDArray[Any]:
    log.warning("artifact removal failed", trace=index, exc_info=error)
    return array


def render(content: bytes, spec: RenderSpec) -> bytes:
    """Draw the activation traces in ``content`` (an NWB file).

    Raises:
        DomainError: ``ASSET_UNREADABLE`` when the file has no activation repetition.
    """
    data = parsed(lambda: read_activation(content), "NWB")
    colormap = TealGrn_7.mpl_colormap
    npoints, nb_traces = data.shape[0], data.shape[1]
    x = np.arange(npoints)
    fig, ax = new_figure(figsize=FIGSIZE)
    for trace in range(nb_traces):
        # max(…, 1): one trace divided by zero in the old service (a 500); it now gets colour 0.
        color = colormap(trace / max(nb_traces - 1, 1))
        ax.plot(x, remove_artifacts(data, trace), color=color, linewidth=0.5)
    ax.set_xticks([])
    ax.set_yticks([])
    for side in ("top", "right", "bottom", "left"):
        ax.spines[side].set_visible(False)
    fig.set_layout_engine("tight")
    return encode(fig, spec.dpi, spec.image_format)
