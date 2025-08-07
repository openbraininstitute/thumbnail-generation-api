"""
Module: health.py

This module provides a simple health check endpoint for the web server.
"""

from fastapi import APIRouter, Depends

from api.dependencies import CacheControl

router = APIRouter()


@router.get("/health", dependencies=[Depends(CacheControl("no-cache"))])
async def health() -> dict:
    """Simple health check endpoint"""
    return {"status": "OK"}
