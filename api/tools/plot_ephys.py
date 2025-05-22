"""
Module: trace_img.py

This module exposes the business logic for generating trace thumbnails
"""

from typing import Any, Union, cast

import matplotlib.pyplot as plt
import numpy as np
from numpy.typing import NDArray


def plot_nwb_ephys(data: NDArray[Any], unit: str, rate: Union[int, float]):
    """Plots traces"""

    def new_ticks(start, end, xory):
        if start == end:
            start = np.floor(start)
            end = np.ceil(end)
            return np.array([start, end])

        if xory == "x":
            stepsize = round((end - start) / 5 / 100) * 100
            xt = np.linspace(start, end, 6)
            return np.concatenate(
                (np.unique(np.round(xt[:-1] / 100) * 100), xt[-1]), axis=None
            )

        if xory == "y":
            stepsize = (end - start) / 4
            return np.arange(start, end + stepsize, stepsize)
        return None

    yrunit = None

    # Plotting
    if unit == "volts":
        data = data * 1e3
        yrunit = "mV"
    elif unit == "amperes":
        data = data * 1e12
        yrunit = "pA"

    npoints = data.shape[0]
    timestamps = 1000 * np.linspace(0, npoints / rate, npoints)
    xunit = "ms"

    figsize = (6, 4)
    fontsize = 16

    fig, ax = plt.subplots(figsize=figsize)
    ax.tick_params(labelsize=fontsize)
    ax.plot(timestamps, data, color="black")
    ax.set_xlabel(xunit, fontsize=fontsize)
    ax.set_ylabel(cast(str, yrunit), fontsize=fontsize)
    ax.xaxis.set_ticks(new_ticks(timestamps.min(), timestamps.max(), "x"))  # type:ignore TODO: Fix type
    ax.set_xticklabels([f"{label:2.0f}" for label in ax.get_xticks()])
    ax.yaxis.set_ticks(new_ticks(min(data), max(data), "y"))  # type:ignore TODO: Fix type
    ax.set_yticklabels([f"{label:2.0f}" for label in ax.get_yticks()])

    figure = fig.figure

    figure.set_layout_engine("tight")

    return figure
