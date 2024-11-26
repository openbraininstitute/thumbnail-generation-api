"""
Model module defining models related to images
"""

from typing import List, Literal, Optional
from fastapi import Query
from pydantic import BaseModel


class ImageGenerationInput(BaseModel):
    """
    The input format for image generation
    """

    content_url: str
    dpi: Optional[int] = Query(None, ge=10, le=600)


PlotTarget = Literal["stimulus", "simulation"]


class SimulationGenerationInput(BaseModel):
    """
    The input format for image generation
    """

    content_url: str
    target: PlotTarget
    w: Optional[int] = None
    h: Optional[int] = None


class PlotData(BaseModel):
    """
    Plotly data format
    """

    x: List[float]
    y: List[float]
    type: str = "scatter"
    name: str


class SimulationConfigurationFile(BaseModel):
    """
    Configuration file content for simulation
    """

    stimulus: List[PlotData]
    simulation: dict[str, List[PlotData]]


class ErrorMessage(BaseModel):
    """
    Model of an error message
    """

    detail: str
