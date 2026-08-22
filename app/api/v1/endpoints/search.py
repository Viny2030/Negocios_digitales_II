"""
Endpoints de orquestación de búsqueda multicanal (Diagrama 1, end-to-end).

  POST /api/v1/analyze                     -> pipeline completo (request validado)
  GET  /api/v1/channels/search              -> variante GET, misma lógica
  GET  /api/v1/channels/discover            -> "todos los temas" (sin categoría),
                                                una sola lista, ordenada de mayor a
                                                menor por métrica
  GET  /api/v1/channels/discover/by-category -> "todos los temas", pero un ranking
                                                independiente por cada categoría
"""
import time

from fastapi import APIRouter, Query

from app.core.config import get_settings
from app.models.domain import Platform
from app.models.schemas import (
    CategoryChannels,
    ChannelSearchRequest,
    DiscoverByCategoryResponse,
    ExecutionMeta,
    PlatformCategoryBreakdown,
    SearchResponse,
)
from app.services.orchestrator import (
    DISCOVER_SORT_FIELDS,
    build_summary,
    category_label,
    discover_by_category_unified,
    discover_unified_channels,
    fetch_unified_channels,
    flatten_channels,
)

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


@router.get(
    "/channels/discover",
    response_model=SearchResponse,
    summary="Descubrir canales de todos los temas (sin categoría), ordenados de mayor a menor por métrica",
)
async def discover_channels(
    platform: Platform = Query(Platform.YOUTUBE, description="youtube | tiktok | all"),
    limit: int = Query(settings.DEFAULT_SEARCH_LIMIT, ge=1, le=settings.DISCOVER_MAX_LIMIT),
    sort_by: str = Query(
        "followers",
        pattern=f"^({'|'.join(DISCOVER_SORT_FIELDS)})$",
        description="Métrica para ordenar de mayor a menor: followers | total_views | total_posts | normalized_er",
    ),
) -> SearchResponse:
    """
    Variante de /channels/search que NO pide un tema/palabra clave: en vez
    de buscar por categoría, junta candidatos de "todos los temas" (en
    YouTube, recorriendo el trending de varias categorías y regiones muy
    distintas — ver `YouTubeCollector.discover`) y los devuelve ya
    ordenados de mayor a menor por `sort_by`, para elegir de ahí cuáles
    agregar al seguimiento (POST /tracking/channels) sin tener que buscar
    tema por tema. `limit` no tiene un tope duro de la API — el resultado
    real queda acotado por cuántos canales distintos aparecen en el
    trending combinado (ver `DISCOVER_REGION_CODES`/`DISCOVER_PAGES_PER_
    REGION_CATEGORY` en la configuración).
    """
    start = time.perf_counter()

    channels_by_platform = await discover_unified_channels(platforms=[platform], limit=limit, sort_by=sort_by)
    channels = flatten_channels(channels_by_platform)
    summary = build_summary(channels_by_platform)

    elapsed_ms = (time.perf_counter() - start) * 1000
    return SearchResponse(
        meta=ExecutionMeta(
            query=f"discover:{sort_by}",
            platforms_requested=list(channels_by_platform.keys()),
            response_time_ms=round(elapsed_ms, 2),
        ),
        summary_by_platform=summary,
        channels=channels,
    )


@router.get(
    "/channels/discover/by-category",
    response_model=DiscoverByCategoryResponse,
    summary="Descubrir canales de todos los temas, con un ranking independiente por cada categoría",
)
async def discover_channels_by_category(
    platform: Platform = Query(Platform.YOUTUBE, description="youtube | tiktok | all"),
    limit_per_category: int = Query(
        settings.DISCOVER_DEFAULT_LIMIT_PER_CATEGORY, ge=1, le=settings.DISCOVER_MAX_LIMIT,
        description="Cantidad de canales a devolver POR categoría (no un total global)",
    ),
    sort_by: str = Query(
        "followers",
        pattern=f"^({'|'.join(DISCOVER_SORT_FIELDS)})$",
        description="Métrica para ordenar de mayor a menor dentro de cada categoría",
    ),
) -> DiscoverByCategoryResponse:
    """
    Variante de /channels/discover que NO mezcla los temas entre sí: en vez
    de un solo ranking global (donde géneros grandes como música o gaming
    tapan a los más chicos), devuelve un ranking independiente por cada
    categoría — Música, Gaming, Noticias, Ciencia y tecnología, etc. — para
    poder "abarcar todos los temas" viendo cada nicho por separado.
    """
    start = time.perf_counter()

    by_platform = await discover_by_category_unified(
        platforms=[platform], limit_per_category=limit_per_category, sort_by=sort_by,
    )

    platform_breakdowns = [
        PlatformCategoryBreakdown(
            platform=p,
            categories=[
                CategoryChannels(
                    category=category_key,
                    label=category_label(p, category_key),
                    channel_count=len(channels),
                    channels=channels,
                )
                for category_key, channels in by_category.items()
            ],
        )
        for p, by_category in by_platform.items()
    ]

    elapsed_ms = (time.perf_counter() - start) * 1000
    return DiscoverByCategoryResponse(
        meta=ExecutionMeta(
            query=f"discover_by_category:{sort_by}",
            platforms_requested=list(by_platform.keys()),
            response_time_ms=round(elapsed_ms, 2),
        ),
        sort_by=sort_by,
        platforms=platform_breakdowns,
    )
