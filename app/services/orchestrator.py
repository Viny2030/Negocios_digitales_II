"""
Ingestion Hub: despacha la búsqueda a los colectores de cada plataforma
de forma concurrente (asyncio.gather), normaliza las respuestas crudas y
arma el resumen agregado. Es el punto único que consumen los endpoints
de `search.py` y `statistics.py`, evitando duplicar lógica de orquestación.
"""
import asyncio

from app.core.exceptions import UnsupportedPlatformError
from app.models.domain import Platform
from app.models.schemas import PlatformSummary, UnifiedChannel
from app.services.analytics.benchmarks import compare_to_benchmark
from app.services.analytics.normalizer import normalize_channels
from app.services.collectors.base import BaseCollector
from app.services.collectors.tiktok import TikTokCollector
from app.services.collectors.youtube import YouTubeCollector

_COLLECTORS: dict[Platform, type[BaseCollector]] = {
    Platform.YOUTUBE: YouTubeCollector,
    Platform.TIKTOK: TikTokCollector,
}

SUPPORTED_PLATFORMS: list[Platform] = [Platform.YOUTUBE, Platform.TIKTOK]


def resolve_platforms(requested: list[Platform]) -> list[Platform]:
    """Expande Platform.ALL y valida que todo lo pedido esté soportado."""
    if Platform.ALL in requested:
        return list(SUPPORTED_PLATFORMS)

    resolved = []
    for platform in requested:
        if platform not in SUPPORTED_PLATFORMS:
            raise UnsupportedPlatformError(platform.value if hasattr(platform, "value") else str(platform))
        resolved.append(platform)
    return resolved or list(SUPPORTED_PLATFORMS)


async def _fetch_and_normalize(platform: Platform, query: str, limit: int) -> list[UnifiedChannel]:
    collector_cls = _COLLECTORS[platform]
    collector = collector_cls()
    raw_results = await collector.search(query=query, limit=limit)
    return normalize_channels(raw_results, platform)


async def fetch_unified_channels(
    query: str, platforms: list[Platform], limit: int
) -> dict[Platform, list[UnifiedChannel]]:
    """
    Ejecuta la búsqueda en todas las plataformas solicitadas en paralelo
    (2. Despacho Asíncrono Concurrente del Diagrama 1) y devuelve los
    resultados ya normalizados, agrupados por plataforma.
    """
    resolved_platforms = resolve_platforms(platforms)

    tasks = [_fetch_and_normalize(platform, query, limit) for platform in resolved_platforms]
    results_per_platform = await asyncio.gather(*tasks)

    return dict(zip(resolved_platforms, results_per_platform))


def build_summary(channels_by_platform: dict[Platform, list[UnifiedChannel]]) -> list[PlatformSummary]:
    summaries: list[PlatformSummary] = []
    for platform, channels in channels_by_platform.items():
        if not channels:
            summaries.append(PlatformSummary(
                platform=platform, channel_count=0, total_followers=0,
                total_views=0, avg_normalized_er=0.0, benchmark=None,
            ))
            continue

        total_followers = sum(c.followers for c in channels)
        total_views = sum(c.total_views for c in channels)
        avg_ner = sum(c.normalized_er for c in channels) / len(channels)

        summaries.append(PlatformSummary(
            platform=platform,
            channel_count=len(channels),
            total_followers=total_followers,
            total_views=total_views,
            avg_normalized_er=round(avg_ner, 4),
            benchmark=compare_to_benchmark(platform, avg_ner),
        ))
    return summaries


def flatten_channels(channels_by_platform: dict[Platform, list[UnifiedChannel]]) -> list[UnifiedChannel]:
    flat: list[UnifiedChannel] = []
    for channels in channels_by_platform.values():
        flat.extend(channels)
    return flat
