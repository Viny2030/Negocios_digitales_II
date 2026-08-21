"""
Endpoints analíticos puros: reciben una búsqueda (query + plataforma),
la resuelven vía el Ingestion Hub y aplican el Motor Estadístico Vectorial
(descriptive / inequality / correlation / anomalies) sobre los canales
normalizados resultantes. También expone las Métricas y Benchmarks del
Medio: valores de referencia de industria por plataforma y comparación
del ER observado contra esos rangos.

Nota de diseño: en esta fase no hay capa de persistencia (dim_channels /
fact_metrics_daily), así que cada llamada recalcula sobre datos frescos.
Cuando se agregue el worker diario (ver README), estos endpoints pueden
leer snapshots precalculados en <50ms en lugar de re-consultar las APIs.
"""
import time

from fastapi import APIRouter, Query

from app.core.config import get_settings
from app.core.exceptions import InsufficientDataError
from app.models.domain import Platform
from app.models.schemas import (
    AnomalyFlag,
    AnomalyResponse,
    BenchmarkResponse,
    CorrelationResponse,
    DistributionResponse,
    ExecutionMeta,
    InequalityResponse,
    InequalityStats,
    OverviewResponse,
    PlatformOverview,
)
from app.services.analytics.anomalies import detect_anomalies
from app.services.analytics.benchmarks import compare_to_benchmark, get_benchmarks
from app.services.analytics.correlation import correlate
from app.services.analytics.descriptive import describe
from app.services.analytics.inequality import gini_coefficient, pareto_alpha, top_decile_share
from app.services.orchestrator import SUPPORTED_PLATFORMS, fetch_unified_channels

router = APIRouter(prefix="/analytics", tags=["analytics"])
settings = get_settings()


@router.get("/benchmarks", response_model=BenchmarkResponse, summary="Métricas y benchmarks de industria por plataforma")
async def benchmarks(
    platform: Platform = Query(Platform.ALL, description="youtube | tiktok | all"),
) -> BenchmarkResponse:
    """
    Referencia estática de industria (Matriz Comparativa de Métricas):
    fórmula y rango típico de engagement, métrica de retención, frecuencia
    de publicación esperable y riesgo de sesgo en métricas crudas, por
    plataforma. No consulta APIs externas ni depende de una búsqueda.
    """
    start = time.perf_counter()
    platforms = SUPPORTED_PLATFORMS if platform == Platform.ALL else [platform]

    elapsed_ms = (time.perf_counter() - start) * 1000
    return BenchmarkResponse(
        meta=ExecutionMeta(platforms_requested=platforms, response_time_ms=round(elapsed_ms, 2)),
        benchmarks=get_benchmarks(platforms),
    )


@router.get("/distribution", response_model=DistributionResponse, summary="Percentiles, dispersión y forma")
async def distribution(
    query: str = Query(..., min_length=1, max_length=200),
    platform: Platform = Query(..., description="youtube | tiktok"),
    limit: int = Query(settings.DEFAULT_SEARCH_LIMIT, ge=1, le=settings.MAX_SEARCH_LIMIT),
) -> DistributionResponse:
    start = time.perf_counter()

    channels_by_platform = await fetch_unified_channels(query=query, platforms=[platform], limit=limit)
    channels = channels_by_platform.get(platform, [])
    if len(channels) < 2:
        raise InsufficientDataError(
            f"Se necesitan al menos 2 canales para '{query}' en {platform.value} "
            f"(encontrados: {len(channels)})"
        )

    followers_stats = describe([float(c.followers) for c in channels], "followers")
    er_stats = describe([c.normalized_er for c in channels], "normalized_er")

    tier_breakdown: dict[str, int] = {}
    for c in channels:
        tier_breakdown[c.tier] = tier_breakdown.get(c.tier, 0) + 1

    elapsed_ms = (time.perf_counter() - start) * 1000
    return DistributionResponse(
        meta=ExecutionMeta(query=query, platforms_requested=[platform], response_time_ms=round(elapsed_ms, 2)),
        platform=platform,
        followers=followers_stats,
        normalized_er=er_stats,
        tier_breakdown=tier_breakdown,
        benchmark=compare_to_benchmark(platform, er_stats.mean),
    )


@router.get("/inequality", response_model=InequalityResponse, summary="Coeficiente de Gini comparativo")
async def inequality(
    query: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(settings.DEFAULT_SEARCH_LIMIT, ge=1, le=settings.MAX_SEARCH_LIMIT),
) -> InequalityResponse:
    start = time.perf_counter()

    channels_by_platform = await fetch_unified_channels(
        query=query, platforms=[Platform.YOUTUBE, Platform.TIKTOK], limit=limit,
    )

    results: list[InequalityStats] = []
    for platform, channels in channels_by_platform.items():
        if len(channels) < 2:
            continue
        followers = [float(c.followers) for c in channels]
        results.append(InequalityStats(
            platform=platform,
            n=len(channels),
            gini_followers=round(gini_coefficient(followers), 4),
            pareto_alpha=(
                round(a, 4) if (a := pareto_alpha(followers)) is not None else None
            ),
            top_10_pct_share=round(top_decile_share(followers), 4),
        ))

    if not results:
        raise InsufficientDataError(f"No hay suficientes canales para '{query}' en ninguna plataforma")

    elapsed_ms = (time.perf_counter() - start) * 1000
    return InequalityResponse(
        meta=ExecutionMeta(
            query=query,
            platforms_requested=list(channels_by_platform.keys()),
            response_time_ms=round(elapsed_ms, 2),
        ),
        results=results,
    )


@router.get("/correlation", response_model=CorrelationResponse, summary="Spearman/Pearson entre variables de canal")
async def correlation(
    query: str = Query(..., min_length=1, max_length=200),
    platform: Platform = Query(..., description="youtube | tiktok"),
    limit: int = Query(settings.DEFAULT_SEARCH_LIMIT, ge=1, le=settings.MAX_SEARCH_LIMIT),
) -> CorrelationResponse:
    start = time.perf_counter()

    channels_by_platform = await fetch_unified_channels(query=query, platforms=[platform], limit=limit)
    channels = channels_by_platform.get(platform, [])
    if len(channels) < 3:
        raise InsufficientDataError(
            f"Se necesitan al menos 3 canales para correlacionar en {platform.value} "
            f"(encontrados: {len(channels)})"
        )

    followers = [float(c.followers) for c in channels]
    posts = [float(c.total_posts) for c in channels]
    ner = [c.normalized_er for c in channels]

    pairs = [
        correlate(posts, ner, "total_posts", "normalized_er"),
        correlate(followers, ner, "followers", "normalized_er"),
    ]

    elapsed_ms = (time.perf_counter() - start) * 1000
    return CorrelationResponse(
        meta=ExecutionMeta(query=query, platforms_requested=[platform], response_time_ms=round(elapsed_ms, 2)),
        platform=platform,
        correlations=pairs,
    )


@router.get("/anomalies", response_model=AnomalyResponse, summary="Detección de cuentas con métricas infladas")
async def anomalies(
    query: str = Query(..., min_length=1, max_length=200),
    platform: Platform = Query(..., description="youtube | tiktok"),
    limit: int = Query(settings.DEFAULT_SEARCH_LIMIT, ge=1, le=settings.MAX_SEARCH_LIMIT),
) -> AnomalyResponse:
    start = time.perf_counter()

    channels_by_platform = await fetch_unified_channels(query=query, platforms=[platform], limit=limit)
    channels = channels_by_platform.get(platform, [])
    if len(channels) < 4:
        raise InsufficientDataError(
            f"Se necesitan al menos 4 canales para detectar anomalías en {platform.value} "
            f"(encontrados: {len(channels)})"
        )

    flagged: list[AnomalyFlag] = detect_anomalies(channels)

    elapsed_ms = (time.perf_counter() - start) * 1000
    return AnomalyResponse(
        meta=ExecutionMeta(query=query, platforms_requested=[platform], response_time_ms=round(elapsed_ms, 2)),
        platform=platform,
        flagged=flagged,
        total_evaluated=len(channels),
    )


@router.get(
    "/overview",
    response_model=OverviewResponse,
    summary="Vista consolidada: distribución + desigualdad + correlación + anomalías + benchmark, por plataforma",
)
async def overview(
    query: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(settings.DEFAULT_SEARCH_LIMIT, ge=1, le=settings.MAX_SEARCH_LIMIT),
) -> OverviewResponse:
    """
    Trae en una sola llamada lo que hoy requiere golpear /distribution,
    /inequality, /correlation y /anomalies por separado, para YouTube y
    TikTok. Los sub-análisis que necesitan más observaciones de las
    encontradas se omiten (no hacen fallar la respuesta completa).
    """
    start = time.perf_counter()

    channels_by_platform = await fetch_unified_channels(
        query=query, platforms=[Platform.YOUTUBE, Platform.TIKTOK], limit=limit,
    )

    platform_overviews: list[PlatformOverview] = []
    for platform, channels in channels_by_platform.items():
        n = len(channels)

        followers_stats = describe([float(c.followers) for c in channels], "followers") if n >= 2 else None
        er_stats = describe([c.normalized_er for c in channels], "normalized_er") if n >= 2 else None

        tier_breakdown: dict[str, int] = {}
        for c in channels:
            tier_breakdown[c.tier] = tier_breakdown.get(c.tier, 0) + 1

        inequality_stats = None
        if n >= 2:
            followers_raw = [float(c.followers) for c in channels]
            inequality_stats = InequalityStats(
                platform=platform,
                n=n,
                gini_followers=round(gini_coefficient(followers_raw), 4),
                pareto_alpha=(
                    round(a, 4) if (a := pareto_alpha(followers_raw)) is not None else None
                ),
                top_10_pct_share=round(top_decile_share(followers_raw), 4),
            )

        correlations = []
        if n >= 3:
            followers_raw = [float(c.followers) for c in channels]
            posts_raw = [float(c.total_posts) for c in channels]
            ner_raw = [c.normalized_er for c in channels]
            correlations = [
                correlate(posts_raw, ner_raw, "total_posts", "normalized_er"),
                correlate(followers_raw, ner_raw, "followers", "normalized_er"),
            ]

        anomaly_flags = detect_anomalies(channels) if n >= 4 else []

        avg_ner = sum(c.normalized_er for c in channels) / n if n > 0 else 0.0

        platform_overviews.append(PlatformOverview(
            platform=platform,
            channel_count=n,
            followers=followers_stats,
            normalized_er=er_stats,
            tier_breakdown=tier_breakdown,
            inequality=inequality_stats,
            correlations=correlations,
            anomalies=anomaly_flags,
            benchmark=compare_to_benchmark(platform, avg_ner) if n > 0 else None,
        ))

    elapsed_ms = (time.perf_counter() - start) * 1000
    return OverviewResponse(
        meta=ExecutionMeta(
            query=query,
            platforms_requested=list(channels_by_platform.keys()),
            response_time_ms=round(elapsed_ms, 2),
        ),
        platforms=platform_overviews,
    )
