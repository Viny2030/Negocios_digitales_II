"""
Capa de Normalización: convierte las respuestas crudas de YouTube y TikTok
en la Entidad Universal Canal (`UnifiedChannel`), y expone las funciones
matemáticas de "Normalización Multicanal":

  - NER  (Normalized Engagement Rate)
  - AS   (Attention Score)
  - PFI  (Production Frequency Index)

NER es la única de las tres que puede calcularse solo con datos de
búsqueda/perfil (lo que devuelven los colectores hoy). AS y PFI requieren
series temporales por video (duración/tiempo visto, timestamps de
publicación) que corresponden a la capa de persistencia diaria descripta
en la arquitectura — por eso se dejan implementadas como utilidades puras,
listas para conectarse cuando exista ese worker.
"""
import math
from statistics import pstdev
from typing import Optional, Sequence

from app.core.exceptions import InsufficientDataError
from app.models.domain import ContentFormat, ContentTier, Platform
from app.models.schemas import UnifiedChannel
from app.services.collectors.base import RawChannelData


# ─────────────────────────────────────────────────────────────────────────
# 1. Índices de Normalización Multicanal
# ─────────────────────────────────────────────────────────────────────────

def normalized_engagement_rate(interactions: float, direct_consumption: float) -> float:
    """
    NER = Interacciones Totales / Consumos Directos (Views/Downloads/CCU-hours)

    Devuelve el resultado como porcentaje. Si no hay consumo directo
    registrado, retorna 0.0 en lugar de dividir por cero (canal sin datos
    suficientes, no es un caso de error del sistema).
    """
    if direct_consumption <= 0:
        return 0.0
    return round((interactions / direct_consumption) * 100, 4)


def attention_score(avg_time_consumed_seconds: float, total_duration_seconds: float) -> Optional[float]:
    """
    AS = Tiempo promedio consumido / Duración total del contenido

    Requiere telemetría de reproducción (no disponible en una simple
    búsqueda de perfil). Devuelve None cuando falta el dato, para que el
    llamador decida cómo representarlo (en vez de asumir 0%).
    """
    if total_duration_seconds <= 0:
        return None
    score = avg_time_consumed_seconds / total_duration_seconds
    return round(min(score, 1.0) * 100, 4)


def production_frequency_index(monthly_posts: float, interval_std_dev_days: float) -> Optional[float]:
    """
    PFI = Publicaciones mensuales × Regularidad del intervalo temporal (1/σΔt)

    A mayor regularidad (σ pequeño) mayor el índice. `interval_std_dev_days`
    es la desviación estándar de los días transcurridos entre publicaciones
    consecutivas; requiere series temporales del canal.
    """
    if interval_std_dev_days <= 0:
        return None
    regularity = 1 / interval_std_dev_days
    return round(monthly_posts * regularity, 4)


# ─────────────────────────────────────────────────────────────────────────
# 2. Normalización YouTube -> UnifiedChannel
# ─────────────────────────────────────────────────────────────────────────

def normalize_youtube_channel(raw: RawChannelData) -> UnifiedChannel:
    snippet = raw.get("snippet", {})
    stats = raw.get("statistics", {})

    subscribers = int(stats.get("subscriberCount", 0) or 0)
    views = int(stats.get("viewCount", 0) or 0)
    videos = int(stats.get("videoCount", 0) or 0)
    comments = int(stats.get("commentCount", 0) or 0)
    # La API pública de YouTube no expone "likes" agregados a nivel canal;
    # se aproxima con comentarios (única señal de interacción disponible
    # sin iterar video por video, lo que dispararía el consumo de cuota).
    interactions = comments

    native_id = raw.get("id", "")
    channel = UnifiedChannel(
        universal_id=f"youtube:{native_id}",
        native_id=native_id,
        platform=Platform.YOUTUBE,
        content_format=ContentFormat.VOD,
        name=snippet.get("title", "Unknown"),
        handle=snippet.get("customUrl"),
        url=f"https://www.youtube.com/channel/{native_id}" if native_id else None,
        followers=subscribers,
        total_views=views,
        total_posts=videos,
        raw_interactions=interactions,
        likes=0,
        comments=comments,
        shares=0,
        saves=0,
        normalized_er=normalized_engagement_rate(interactions, views),
        tier=ContentTier.classify(subscribers),
    )
    return channel


# ─────────────────────────────────────────────────────────────────────────
# 3. Normalización TikTok -> UnifiedChannel
# ─────────────────────────────────────────────────────────────────────────

def normalize_tiktok_channel(raw: RawChannelData) -> UnifiedChannel:
    followers = int(raw.get("follower_count", 0) or 0)
    views = int(raw.get("video_views_sum", 0) or 0)
    videos = int(raw.get("video_count", 0) or 0)
    likes = int(raw.get("likes_sum", 0) or 0)
    comments = int(raw.get("comments_sum", 0) or 0)
    shares = int(raw.get("shares_sum", 0) or 0)
    saves = int(raw.get("saves_sum", 0) or 0)
    interactions = likes + comments + shares + saves

    native_id = raw.get("user_id") or raw.get("unique_id", "")
    handle = raw.get("unique_id")
    channel = UnifiedChannel(
        universal_id=f"tiktok:{native_id}",
        native_id=str(native_id),
        platform=Platform.TIKTOK,
        content_format=ContentFormat.MICRO_VIDEO,
        name=raw.get("nickname", handle or "Unknown"),
        handle=f"@{handle}" if handle else None,
        url=f"https://www.tiktok.com/@{handle}" if handle else None,
        followers=followers,
        total_views=views,
        total_posts=videos,
        raw_interactions=interactions,
        likes=likes,
        comments=comments,
        shares=shares,
        saves=saves,
        normalized_er=normalized_engagement_rate(interactions, views),
        tier=ContentTier.classify(followers),
    )
    return channel


# ─────────────────────────────────────────────────────────────────────────
# 4. Fachada genérica usada por los endpoints
# ─────────────────────────────────────────────────────────────────────────

_NORMALIZERS = {
    Platform.YOUTUBE: normalize_youtube_channel,
    Platform.TIKTOK: normalize_tiktok_channel,
}


def normalize_channels(raw_list: Sequence[RawChannelData], platform: Platform) -> list[UnifiedChannel]:
    normalizer_fn = _NORMALIZERS.get(platform)
    if normalizer_fn is None:
        raise InsufficientDataError(f"No hay normalizador implementado para '{platform.value}'")
    return [normalizer_fn(raw) for raw in raw_list]
