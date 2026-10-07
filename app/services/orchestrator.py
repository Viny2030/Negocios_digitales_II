"""
Ingestion Hub: despacha la búsqueda a los colectores de cada plataforma
de forma concurrente (asyncio.gather), normaliza las respuestas crudas y
arma el resumen agregado. Es el punto único que consumen los endpoints
de `search.py` y `statistics.py`, evitando duplicar lógica de orquestación.
"""
import asyncio

from app.core.config import get_settings
from app.core.exceptions import InsufficientDataError, PlatformAPIError, UnsupportedPlatformError
from app.models.domain import Platform
from app.models.schemas import PlatformSummary, UnifiedChannel
from app.services.analytics.benchmarks import compare_to_benchmark
from app.services.analytics.normalizer import apply_recent_engagement, normalize_channels
from app.services.collectors.base import BaseCollector
from app.services.collectors.tiktok import TikTokCollector
from app.services.collectors.youtube import DISCOVER_CATEGORY_LABELS, YouTubeCollector

_COLLECTORS: dict[Platform, type[BaseCollector]] = {
    Platform.YOUTUBE: YouTubeCollector,
    Platform.TIKTOK: TikTokCollector,
}

SUPPORTED_PLATFORMS: list[Platform] = [Platform.YOUTUBE, Platform.TIKTOK]

settings = get_settings()


def platform_available(platform: Platform) -> bool:
    """
    True si la plataforma puede devolver datos: tiene credenciales, o el modo
    mock está habilitado. Con el mock apagado (default en producción), una
    plataforma sin credenciales NO está disponible -- así `platform=all` no
    mezcla YouTube real con TikTok inventado.
    """
    if settings.USE_MOCK_DATA_IF_NO_CREDENTIALS:
        return True
    if platform == Platform.YOUTUBE:
        return bool(settings.YOUTUBE_API_KEY)
    if platform == Platform.TIKTOK:
        return bool(settings.TIKTOK_CLIENT_KEY and settings.TIKTOK_CLIENT_SECRET)
    return False

# Métricas por las que se puede ordenar de mayor a menor en /channels/discover.
DISCOVER_SORT_FIELDS: dict[str, str] = {
    "followers": "followers",
    "total_views": "total_views",
    "total_posts": "total_posts",
    "normalized_er": "normalized_er",
}


def resolve_platforms(requested: list[Platform]) -> list[Platform]:
    """
    Expande Platform.ALL (solo a las plataformas disponibles, ver
    `platform_available`) y valida que todo lo pedido esté soportado.
    """
    if Platform.ALL in requested or not requested:
        available = [p for p in SUPPORTED_PLATFORMS if platform_available(p)]
        if not available:
            raise PlatformAPIError(
                "all", "ninguna plataforma tiene credenciales configuradas (y el modo mock está desactivado)"
            )
        return available

    resolved = []
    for platform in requested:
        if platform not in SUPPORTED_PLATFORMS:
            raise UnsupportedPlatformError(platform.value if hasattr(platform, "value") else str(platform))
        resolved.append(platform)
    return resolved


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

    return dict(zip(resolved_platforms, results_per_platform, strict=True))


def build_summary(channels_by_platform: dict[Platform, list[UnifiedChannel]]) -> list[PlatformSummary]:
    summaries: list[PlatformSummary] = []
    for platform, channels in channels_by_platform.items():
        if not channels:
            summaries.append(PlatformSummary(
                platform=platform, channel_count=0, total_followers=0,
                total_views=0, avg_normalized_er=0.0, benchmark=None, mock_data=False,
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
            mock_data=any(c.is_mock for c in channels),
        ))
    return summaries


async def enrich_engagement(platform: Platform, channels: list[UnifiedChannel]) -> list[UnifiedChannel]:
    """
    Completa el NER de canales de YouTube que llegaron sin muestreo de videos
    (los de `discover*`, ver `YouTubeCollector.discover`). Se llama sobre el
    resultado FINAL (ya ordenado y recortado), así la cuota extra es
    proporcional a lo que se devuelve y no a los miles de candidatos del
    trending. No-op para TikTok, canales simulados o ya muestreados.
    """
    if platform != Platform.YOUTUBE:
        return channels
    pending = [c.native_id for c in channels if not c.is_mock and c.engagement_videos_sampled is None]
    if not pending:
        return channels
    by_id = await YouTubeCollector().recent_engagement_by_channel(pending)
    return [apply_recent_engagement(c, by_id[c.native_id]) if c.native_id in by_id else c for c in channels]


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

    if sort_by == "normalized_er":
        # Para ordenar por engagement hay que muestrearlo en TODOS los
        # candidatos antes de recortar (más cuota: ~1 unidad por canal).
        deduped = await enrich_engagement(platform, deduped)
        deduped.sort(key=lambda c: c.normalized_er, reverse=True)
        return deduped[:limit]
    deduped.sort(key=lambda c: getattr(c, sort_by), reverse=True)
    return await enrich_engagement(platform, deduped[:limit])


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

    return dict(zip(resolved_platforms, results_per_platform, strict=True))


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
    platform: Platform, limit_per_category: int, sort_by: str, with_engagement: bool = True,
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

        if with_engagement and sort_by == "normalized_er":
            deduped = await enrich_engagement(platform, deduped)
        deduped.sort(key=lambda c: getattr(c, sort_by), reverse=True)
        normalized_by_category[category_key] = deduped[:limit_per_category]

    if with_engagement:
        # Un solo muestreo para todos los canales finales de todas las
        # categorías (un canal puede repetirse entre categorías).
        all_final = [c for channels in normalized_by_category.values() for c in channels]
        enriched = {c.universal_id: c for c in await enrich_engagement(platform, all_final)}
        normalized_by_category = {
            key: [enriched.get(c.universal_id, c) for c in channels]
            for key, channels in normalized_by_category.items()
        }
    return normalized_by_category


async def discover_by_category_unified(
    platforms: list[Platform], limit_per_category: int, sort_by: str = "followers", with_engagement: bool = True,
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
        _discover_by_category_and_normalize(platform, limit_per_category, sort_by, with_engagement)
        for platform in resolved_platforms
    ]
    results_per_platform = await asyncio.gather(*tasks)

    return dict(zip(resolved_platforms, results_per_platform, strict=True))
