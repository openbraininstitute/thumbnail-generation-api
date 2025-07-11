"""
Model module defining models related to images
"""

from typing import Literal

from fastapi import Query
from pydantic import BaseModel


class ImageGenerationInput(BaseModel):
    """
    The input format for image generation
    """

    content_url: str
    dpi: int | None = Query(None, ge=10, le=600)


PlotTarget = Literal["stimulus", "simulation"]


class SimulationGenerationInput(BaseModel):
    """
    The input format for image generation
    """

    content_url: str
    target: PlotTarget
    w: int | None = None
    h: int | None = None


class PlotData(BaseModel):
    """
    Plotly data format
    """

    x: list[float]
    y: list[float]
    type: str = "scatter"
    name: str


class SimulationConfiguration(BaseModel):
    """
    Configuration file content for simulation
    """

    stimulus: list[PlotData]
    simulation: dict[str, list[PlotData]]


class ErrorMessage(BaseModel):
    """
    Model of an error message
    """

    detail: str
