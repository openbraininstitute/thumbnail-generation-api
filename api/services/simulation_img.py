"""
Module: simulation_img.py

This module exposes the business logic for generating simulation thumbnails
"""

from typing import List
import io
import json
import plotly.graph_objects as go

from api.models.common import (
    PlotData,
    SimulationConfiguration,
    PlotTarget,
)


def generate_simulation_plots(
    config_file_content: str,
    target: PlotTarget,
    w: int | None,
    h: int | None,
) -> bytes | None:
    """
    Creates plotly figure with data and layout

    Parameters:
        - config: configuration object contains the content_url, dimension of the image and plot target
    Returns:
        The simulation figure
    """

    try:
        simulation_config = SimulationConfiguration(**json.loads(config_file_content))
    except Exception as exc:
        raise ValueError("Configuration file is malformed") from exc

    data: List[PlotData] = []

    if target == "stimulus":
        stimulus_config = simulation_config.stimulus
        # in the future the stimulus may have different configs
        # we should agree how the user can specify the stimulus thumb needed
        if stimulus_config is not None:
            data = stimulus_config
    elif target == "simulation":
        if simulation_config.simulation and len(simulation_config.simulation) > 0:
            data = list(simulation_config.simulation.items())[0][1]

    if len(data) > 0:
        fig = go.Figure(
            data=[
                {"x": pd.x, "y": pd.y, "type": pd.type, "name": pd.name} for pd in data
            ],
            layout={
                "showlegend": False,
                "margin": {"t": 4, "r": 4, "l": 4, "b": 4},
            },
        )
        buffer = io.BytesIO()
        fig.write_image(
            buffer,
            format="png",
            width=w,
            height=h,
        )
        buffer.seek(0)

        return buffer.getvalue()

    raise ValueError("No data for selected plot type is found")
