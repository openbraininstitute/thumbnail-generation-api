"""
Module: trace_img.py

This module exposes the business logic for generating ion channel recording trace thumbnails.
We display all the traces on the same plot with different colors.
We try to smooth the artifacts in order to let the user see them, but preventing
them from messing up the global scale of the plot.
"""

import statistics
from http import HTTPStatus

import matplotlib.pyplot as plt
import numpy as np
from palettable.cartocolors.sequential import TealGrn_7  # pyright: ignore
from loguru import logger
from numpy.typing import NDArray

# palettable.cartocolors.sequential.TealGrn_7 import mpl_colormap as colormap
from api.core.api import ApiError, ApiErrorCode
from api.types import IonChannelRecordingData


def get_line_number(ex: Exception):
    line_number = "?"
    if ex.__traceback__:
        line_number = ex.__traceback__.tb_lineno
    return line_number


def compute_derivatives(array: NDArray):
    derivatives = []
    count = len(array)
    for i in range(count):
        before = max(0, i - 1)
        after = min(count - 1, i + 1)
        deriv_before = array[i] - array[before]
        deriv_after = array[after] - array[i]
        value = max(abs(deriv_before), abs(deriv_after))
        derivatives.append(value)
    return derivatives


def remove_suspiscious_indexes(array: NDArray, indexes: list[int]):
    count = len(array)
    for index in indexes:
        before = max(0, index - 1)
        after = min(count - 1, index + 1)
        array[index] = (array[before] + array[after]) / 2
    return array


def remove_artifacts(data: NDArray, index: int) -> NDArray:
    """Remove artifacts

    We start by computing the average derivative, then
    we find points with a suspiscious derivative (one that
    is 2 times the mean) and we remove them by averaging with
    the neighbours."""

    array = data[:, index]
    suspiscion = 2
    try:
        for _loops in range(3):
            # This is empiric, but we found out that looping
            # 3 times do not remove the artifact completely,
            # but reduce them enough to avoir the scaling messup.
            derivatives = compute_derivatives(array)
            mean_derivative = statistics.mean(derivatives)
            threshold = mean_derivative * suspiscion
            suspiscious_indexes = [
                index for index in range(len(array)) if derivatives[index] > threshold
            ]
            if len(suspiscious_indexes) == 0:
                return array
            remove_suspiscious_indexes(array, suspiscious_indexes)
        return array
    except Exception as ex:  # noqa: BLE001
        logger.warning(f"Error in remove_artifacts() at line {get_line_number(ex)}:", ex)
        return array


def plot_nwb_ion_channel(data: IonChannelRecordingData):
    """Plots traces

    No need for axis in the thumbnail."""
    try:
        colormap = TealGrn_7.mpl_colormap
        data_y = data.activation_current
        npoints = data_y.shape[0]
        data_x = np.arange(npoints)
        nb_traces = data_y.shape[1]
        figsize = (6, 4)
        fig, ax = plt.subplots(figsize=figsize)
        for trace_index in range(nb_traces):
            trace = remove_artifacts(data_y, trace_index)
            ax.plot(data_x, trace, color=colormap(trace_index / (nb_traces - 1)), linewidth=0.5)
            # We don't want any tick.
            ax.set_xticks([])
            ax.set_yticks([])

        figure = fig.figure
        figure.set_layout_engine("tight")
        return figure

    except Exception as ex:
        raise ApiError(
            message=f"Error in plot_nwb_ion_channel() at line {get_line_number(ex)}: {ex}",
            details=ex,
            error_code=ApiErrorCode.INTERNAL_ERROR,
            http_status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        ) from ex
