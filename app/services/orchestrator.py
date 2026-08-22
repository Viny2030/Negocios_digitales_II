"""
Ingestion Hub: despacha la búsqueda a los colectores de cada plataforma
de forma concurrente (asyncio.gather), normaliza las respuestas crudas y
arma el resumen agregado. Es el punto único que consumen los endpoints
de `search.py` y `statistics.py`, evitando duplicar lógica de orquestación.
"""
import asyncio

from app.core.exceptions import InsufficientDataError, UnsupportedPlatformError
from app.models.domain import Platform
from app.models.schemas import PlatformSummary, UnifiedChannel
from app.services.analytics.benchmarks import compare_to_benchmark
from app.services.analytics.normalizer import normalize_channels
from app.services.collectors.base import BaseCollector
from app.services.collectors.tiktok import TikTokCollector
from app.services.collectors.youtube import DISCOVER_CATEGORY_LABELS, YouTubeCollector

_COLLECTORS: dict[Platform, type[BaseCollector]] = {
    Platform.YOUTUBE: YouTubeCollector,
    Platform.TIKTOK: TikTokCollector,
}

SUPPORTED_PLATFORMS: list[Platform] = [Platform.YOUTUBE, Platform.TIKTOK]

# Métricas por las que se puede ordenar de mayor a menor en /channels/discover.
DISCOVER_SORT_FIELDS: dict[str, str] = {
    "followers": "followers",
    "total_views": "total_views",
    "total_posts": "total_posts",
    "normalized_er": "normalized_er",
}


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


async def _discover_and_normalize(
    platform: Platform, limit: int, sort_by: str
) -> list[UnifiedChannel]:
    collector_cls = _COLLECTORS[platform]
    collector = collector_cls()
    raw_results = await collector.discover(limit=limit)
    channels = normalize_channels(raw_results, platform)

    # `discover()` puede devolver el mismo canal más de una vez (aparece en
    # el trending de más de una categoría, o en más de un tema semilla del
    # fallback mock) — se deduplica por universal_id antes de ordenar.
    seen: set[str] = set()
    deduped: list[UnifiedChannel] = []
    for channel in channels:
        if channel.universal_id in seen:
            continue
        seen.add(channel.universal_id)
        deduped.append(channel)

    deduped.sort(key=lambda c: getattr(c, sort_by), reverse=True)
    return deduped[:limit]


async def discover_unified_channels(
    platforms: list[Platform], limit: int, sort_by: str = "followers"
) -> dict[Platform, list[UnifiedChannel]]:
    """
    Ingestion Hub para "todos los temas" (sin buscar por categoría/tema
    puntual, ver GET /api/v1/channels/discover): despacha `discover()` a
    cada colector en paralelo, normaliza, deduplica y devuelve los canales
    de cada plataforma ordenados de mayor a menor por `sort_by`.
    """
    if sort_by not in DISCOVER_SORT_FIELDS:
        raise InsufficientDataError(
            f"'{sort_by}' no es una métrica válida para ordenar. "
            f"Opciones: {', '.join(DISCOVER_SORT_FIELDS)}"
        )

    resolved_platforms = resolve_platforms(platforms)
    tasks = [_discover_and_normalize(platform, limit, sort_by) for platform in resolved_platforms]
    results_per_platform = await asyncio.gather(*tasks)

    return dict(zip(resolved_platforms, results_per_platform))


def category_label(platform: Platform, category_key: str) -> str:
    """
    Nombre legible de una categoría/tópico de `discover_by_category()`. En
    YouTube `category_key` es un `videoCategoryId` numérico ("10") que se
    traduce vía `DISCOVER_CATEGORY_LABELS`; en el fallback genérico (TikTok,
    o YouTube sin credenciales) `category_key` ya es el tópico semilla en
    español ("música"), así que se devuelve tal cual.
    """
    if platform == Platform.YOUTUBE:
        return DISCOVER_CATEGORY_LABELS.get(category_key, category_key)
    return category_key.title()


async def _discover_by_category_and_normalize(
    platform: Platform, limit_per_category: int, sort_by: str
) -> dict[str, list[UnifiedChannel]]:
    collector_cls = _COLLECTORS[platform]
    collector = collector_cls()
    raw_by_category = await collector.discover_by_category(limit_per_category=limit_per_category)

    normalized_by_category: dict[str, list[UnifiedChannel]] = {}
    for category_key, raw_results in raw_by_category.items():
        channels = normalize_channels(raw_results, platform)

        seen: set[str] = set()
        deduped: list[UnifiedChannel] = []
        for channel in channels:
            if channel.universal_id in seen:
                continue
            seen.add(channel.universal_id)
            deduped.append(channel)

        deduped.sort(key=lambda c: getattr(c, sort_by), reverse=True)
        normalized_by_category[category_key] = deduped[:limit_per_category]
    return normalized_by_category


async def discover_by_category_unified(
    platforms: list[Platform], limit_per_category: int, sort_by: str = "followers"
) -> dict[Platform, dict[str, list[UnifiedChannel]]]:
    """
    Variante de `discover_unified_channels()` que NO mezcla las categorías:
    para GET /api/v1/channels/discover/by-category, devuelve un ranking
    independiente por cada categoría/tópico de cada plataforma, en vez de
    una sola lista global donde los géneros más grandes tapan a los chicos.
    """
    if sort_by not in DISCOVER_SORT_FIELDS:
        raise InsufficientDataError(
            f"'{sort_by}' no es una métrica válida para ordenar. "
            f"Opciones: {', '.join(DISCOVER_SORT_FIELDS)}"
        )

    resolved_platforms = resolve_platforms(platforms)
    tasks = [
        _discover_by_category_and_normalize(platform, limit_per_category, sort_by)
        for platform in resolved_platforms
    ]
    results_per_platform = await asyncio.gather(*tasks)

    return dict(zip(resolved_platforms, results_per_platform))
