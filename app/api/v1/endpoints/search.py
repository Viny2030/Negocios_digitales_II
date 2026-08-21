"""
Endpoints de orquestación de búsqueda multicanal (Diagrama 1, end-to-end).

  POST /api/v1/analyze                 -> pipeline completo (request validado)
  GET  /api/v1/channels/search          -> variante GET, misma lógica
"""
import time

from fastapi import APIRouter, Query

from app.core.config import get_settings
from app.models.domain import Platform
from app.models.schemas import ChannelSearchRequest, ExecutionMeta, SearchResponse
from app.services.orchestrator import build_summary, fetch_unified_channels, flatten_channels

router = APIRouter(tags=["search"])
settings = get_settings()


@router.post("/analyze", response_model=SearchResponse, summary="Pipeline completo de búsqueda + normalización")
async def analyze(payload: ChannelSearchRequest) -> SearchResponse:
    start = time.perf_counter()

    channels_by_platform = await fetch_unified_channels(
        query=payload.query, platforms=payload.platforms, limit=payload.limit,
    )
    channels = flatten_channels(channels_by_platform)
    summary = build_summary(channels_by_platform)

    elapsed_ms = (time.perf_counter() - start) * 1000
    return SearchResponse(
        meta=ExecutionMeta(
            query=payload.query,
            platforms_requested=list(channels_by_platform.keys()),
            response_time_ms=round(elapsed_ms, 2),
        ),
        summary_by_platform=summary,
        channels=channels,
    )


@router.get("/channels/search", response_model=SearchResponse, summary="Búsqueda unificada YouTube + TikTok")
async def search_channels(
    query: str = Query(..., min_length=1, max_length=200, description="Tema / palabra clave"),
    platform: Platform = Query(Platform.ALL, description="youtube | tiktok | all"),
    limit: int = Query(settings.DEFAULT_SEARCH_LIMIT, ge=1, le=settings.MAX_SEARCH_LIMIT),
) -> SearchResponse:
    start = time.perf_counter()

    channels_by_platform = await fetch_unified_channels(query=query, platforms=[platform], limit=limit)
    channels = flatten_channels(channels_by_platform)
    summary = build_summary(channels_by_platform)

    elapsed_ms = (time.perf_counter() - start) * 1000
    return SearchResponse(
        meta=ExecutionMeta(
            query=query,
            platforms_requested=list(channels_by_platform.keys()),
            response_time_ms=round(elapsed_ms, 2),
        ),
        summary_by_platform=summary,
        channels=channels,
    )
