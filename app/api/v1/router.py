"""Agregador de rutas v1."""
from fastapi import APIRouter

from app.api.v1.endpoints import search, statistics, tracking

api_router = APIRouter()
api_router.include_router(search.router)
api_router.include_router(statistics.router)
api_router.include_router(tracking.router)
