"""Electrical cell recording (NWB) → one sweep of the response, in mV or pA over ms."""

import io
from typing import Any, cast

import h5py
import numpy as np
from numpy.typing import NDArray
from pydantic import ConfigDict

from app.domain.guards import match_error
from app.domain.preview import RenderSpec
from app.domain.types import Value
from app.rendering.common import encode, new_figure, parsed
from app.rendering.nwb import (
    attribute,
    read_array,
    select_element,
    select_protocol,
    select_response,
)

FIGSIZE = (6, 4)
FONTSIZE = 16


class Trace(Value):
    """One response trace, already multiplied by its conversion factor."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    data: NDArray[Any]
    unit: str
    rate: float


def read_trace(content: bytes) -> Trace:
    """The trace to draw, from an LNMC data-organization NWB file or a generic one.

    Raises:
        DomainError: ``ASSET_UNREADABLE`` when an expected group or attribute is missing.
    """
    with h5py.File(io.BytesIO(content), "r") as h5:
        try:
            response = _lnmc_response(h5)
        except KeyError as error:  # no LNMC group: the generic layout
            response = match_error(error, {KeyError: lambda _: _generic_response(h5)})
        unit = str(attribute(response, "data", "unit"))
        rate = float(cast("float", attribute(response, "starting_time", "rate")))
        conversion = float(cast("float", attribute(response, "data", "conversion")))
        data = read_array(response, "data", np.float64) * conversion
    return Trace(data=data, unit=unit, rate=rate)


def _lnmc_response(h5: h5py.File) -> h5py.Group:
    """LNMC layout: cell / protocol / repetition / sweep / response."""
    cells = cast("h5py.Group", h5["data_organization"])
    cell = cells[select_element(list(cells.keys()), n=0, what="cell")]
    protocol = cell[select_protocol(list(cell.keys()))]
    repetition = protocol[select_element(list(protocol.keys()), n=0, what="repetition")]
    sweep = repetition[select_element(list(repetition.keys()), n=-3, what="sweep")]
    return sweep[select_response(list(sweep.keys()))]


def _generic_response(h5: h5py.File) -> h5py.Group:
    """Generic layout: acquisition / response."""
    acquisition = cast("h5py.Group", h5["acquisition"])
    return acquisition[select_element(list(acquisition.keys()), n=-3)]


def _ticks(start: float, end: float, axis: str) -> NDArray[Any]:
    if start == end:
        return np.array([np.floor(start), np.ceil(end)])
    if axis == "x":
        xt = np.linspace(start, end, 6)
        return np.concatenate((np.unique(np.round(xt[:-1] / 100) * 100), xt[-1]), axis=None)
    step = (end - start) / 4
    return np.arange(start, end + step, step)


def render(content: bytes, spec: RenderSpec) -> bytes:
    """Draw the response trace in ``content`` (an NWB file).

    Raises:
        DomainError: ``ASSET_UNREADABLE`` when the file is not a readable recording.
    """
    trace = parsed(lambda: read_trace(content), "NWB")
    data, y_unit = trace.data, None
    if trace.unit == "volts":
        data *= 1e3
        y_unit = "mV"
    elif trace.unit == "amperes":
        data *= 1e12
        y_unit = "pA"
    npoints = data.shape[0]
    timestamps = 1000 * np.linspace(0, npoints / trace.rate, npoints)

    fig, ax = new_figure(figsize=FIGSIZE)
    ax.tick_params(labelsize=FONTSIZE)
    ax.plot(timestamps, data, color="black")
    ax.set_xlabel("ms", fontsize=FONTSIZE)
    ax.set_ylabel(cast("str", y_unit), fontsize=FONTSIZE)
    ax.xaxis.set_ticks(_ticks(timestamps.min(), timestamps.max(), "x"))
    ax.set_xticklabels([f"{label:2.0f}" for label in ax.get_xticks()])
    ax.yaxis.set_ticks(_ticks(min(data), max(data), "y"))
    ax.set_yticklabels([f"{label:2.0f}" for label in ax.get_yticks()])
    fig.set_layout_engine("tight")
    return encode(fig, spec.dpi, spec.image_format)
