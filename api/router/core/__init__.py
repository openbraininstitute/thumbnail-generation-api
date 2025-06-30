"""
Module: core.py

This module provides routes for generating previews
"""

from fastapi import APIRouter

from api.router.core.ephys import router as ephys_router
from api.router.core.model_trace import router as model_trace_router
from api.router.core.morphology import router as morphology_router
from api.router.core.simulation import router as simulation_router

core_router = APIRouter(
    prefix="/core",
)


core_router.include_router(morphology_router)
core_router.include_router(ephys_router)
core_router.include_router(model_trace_router)
core_router.include_router(simulation_router)
