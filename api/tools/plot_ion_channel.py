"""
Module: trace_img.py

This module exposes the business logic for generating ion channel recording trace thumbnails.
We display all the traces on the same plot with different colors.
We try to smooth the artifacts in order to let the user see them, but preventing
them from messing up the global scale of the plot.
"""

from typing import List

import statistics
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
import numpy as np
from numpy.typing import NDArray
from http import HTTPStatus as status
from loguru import logger as L
import palettable
# palettable.cartocolors.sequential.TealGrn_7 import mpl_colormap as colormap

from api.core.api import ApiError, ApiErrorCode
from api.types import IonChannelRecordingData

def compute_derivatives(array: List[float]):
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

def remove_suspiscious_indexes(array: NDArray, indexes: List[int]):
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
    
    array = data[:,index]
    suspiscion = 2
    try:
        for loops in range(3):
            # This is empiric, but we found out that looping
            # 3 times do not remove the artifact completely,
            # but reduce them enough to avoir the scaling messup.
            derivatives = compute_derivatives(array)
            mean_derivative = statistics.mean(derivatives)
            threshold = mean_derivative * suspiscion
            suspiscious_indexes = []
            for index in range(len(array)):
                if (derivatives[index] > threshold):
                    suspiscious_indexes.append(index)
            if len(suspiscious_indexes) == 0:
                break
            remove_suspiscious_indexes(array, suspiscious_indexes)
        return array
    except Exception as ex:
        L.warning(f"Error in remove_artifacts() at line {ex.__traceback__.tb_lineno}:", ex)
        return array
    
def plot_nwb_ion_channel(data: IonChannelRecordingData):
    """Plots traces
    
    No need for axis in the thumbnail."""
    try:
        colormap = palettable.cartocolors.sequential.TealGrn_7.mpl_colormap
        data_y = data.activation_current
        npoints = data_y.shape[0]
        data_x = np.arange(npoints)
        nb_traces = data_y.shape[1]
        figsize = (6, 4)
        fig, ax = plt.subplots(figsize=figsize)
        for trace_index in range(nb_traces):
            trace = remove_artifacts(data_y, trace_index)
            ax.plot(
                data_x, 
                trace, 
                color=colormap(trace_index / (nb_traces - 1)),
                linewidth=0.5
            )
            # We don't want any tick.
            ax.set_xticks([])
            ax.set_yticks([])

        figure = fig.figure
        figure.set_layout_engine("tight")

        return figure
    except Exception as ex:
        raise ApiError(
            message=f"Error in plot_nwb_ion_channel() at line {ex.__traceback__.tb_lineno}: {ex}",
            details=ex,
            error_code=ApiErrorCode.INTERNAL_ERROR,
            http_status_code=status.INTERNAL_SERVER_ERROR,
        ) from ex


