"""
Señales de audiencia inusual: indicios públicos de que los números de un canal
podrían no reflejar personas reales (seguidores comprados, vistas infladas, etc.).

Con la API pública no se puede ver quién mira ni identificar bots: no hay usuarios
únicos, tiempo de visualización ni origen del tráfico (esos datos solo los tiene el
dueño del canal). Por eso esto NO prueba un fraude ni nombra a nadie como tramposo:
marca qué conviene revisar, con el dato que dispara cada señal a la vista.

Criterios que evitan acusar por un solo número:
  - una señal que no se pudo calcular se informa como "no disponible", nunca como normal;
  - una sola señal, por fuerte que sea, no alcanza para pasar de "leve" (ver SINGLE_SIGNAL_CAP);
  - con menos de MIN_SIGNALS_EVALUATED señales calculadas, o menos de MIN_FOLLOWERS
    seguidores, el resultado es "datos_insuficientes".

Los umbrales son heurísticos, no salen de un dataset etiquetado: están acá arriba para
poder ajustarlos cuando haya canales con fraude comprobado contra los que validarlos.
"""
from collections.abc import Iterable, Sequence
from statistics import median
from typing import Protocol

from app.models.domain import ContentFormat, ContentTier, Platform
from app.models.schemas import AudienceAssessment, AudienceSignal, UnifiedChannel
from app.services.analytics.benchmarks import INDUSTRY_BENCHMARKS

# Canales muy chicos: cualquier proporción oscila demasiado para sacar conclusiones.
MIN_FOLLOWERS = 1_000
MIN_POSTS_FOR_LIFETIME_RATIO = 10
MIN_FOLLOWERS_FOR_RECENT_VIEWS = 10_000
MIN_VIDEOS_FOR_RECENT_VIEWS = 3
MIN_VIDEOS_FOR_SPIKE = 5
MIN_SNAPSHOTS_FOR_HISTORY = 4
# Con muchas vistas históricas por seguidor, que los videos nuevos lleguen a pocos no dice
# nada: en una prueba con 69 canales reales (09/11/2026), esta señal marcaba justamente a
# medios con años de historia o decenas de miles de videos (todos con 75 o más).
ESTABLISHED_VIEWS_PER_FOLLOWER = 50

MIN_SIGNALS_EVALUATED = 2
SINGLE_SIGNAL_CAP = 49

LEVEL_MILD = 25
LEVEL_REVIEW = 50
LEVEL_HIGH = 75

DISCLAIMER = (
    "Indicios a partir de datos públicos, no una prueba de compra de audiencia ni de bots. "
    "Un canal legítimo también puede mostrar estas señales: conviene pedirle sus estadísticas "
    "internas antes de sacar conclusiones."
)


def ner_available(channel: UnifiedChannel) -> bool:
    """False si el NER de 0.0 significa "no se pudo medir" y no "nadie interactúa"."""
    if channel.platform == Platform.YOUTUBE.value:
        return channel.engagement_videos_sampled is not None or channel.is_mock
    return channel.total_views > 0


def _signal(code: str, label: str, points: int, detail: str) -> AudienceSignal:
    return AudienceSignal(code=code, label=label, points=points, detail=detail)


def _lifetime_views(channel: UnifiedChannel) -> AudienceSignal | None:
    ratio = channel.total_views / channel.followers
    if ratio < 1:
        points = 35
    elif ratio < 3:
        points = 20
    else:
        return None
    return _signal(
        "few_views_for_followers",
        "Pocas vistas para tantos seguidores",
        points,
        f"{channel.total_views:,} vistas históricas con {channel.followers:,} seguidores "
        f"({ratio:.1f} vistas por seguidor, en {channel.total_posts:,} publicaciones).",
    )


def _low_engagement(channel: UnifiedChannel) -> AudienceSignal | None:
    benchmark = INDUSTRY_BENCHMARKS.get(Platform(channel.platform))
    if benchmark is None:
        return None
    minimum = benchmark.engagement_benchmark_min_pct
    if channel.normalized_er < minimum * 0.1:
        points = 30
    elif channel.normalized_er < minimum * 0.25:
        points = 15
    else:
        return None
    return _signal(
        "low_engagement",
        "Interacción muy baja",
        points,
        f"Interacción de {channel.normalized_er:.3f}%, cuando el piso de referencia de la "
        f"plataforma es {minimum:.1f}%.",
    )


def _recent_views(channel: UnifiedChannel, views: Sequence[int]) -> AudienceSignal | None:
    if channel.total_views / channel.followers >= ESTABLISHED_VIEWS_PER_FOLLOWER:
        return None
    typical = median(views)
    share = typical / channel.followers * 100
    if share < 0.5:
        points = 25
    elif share < 1.5:
        points = 12
    else:
        return None
    return _signal(
        "few_recent_views",
        "Los seguidores casi no miran los videos nuevos",
        points,
        f"Un video reciente típico tiene {int(typical):,} vistas: {share:.2f}% de sus "
        f"{channel.followers:,} seguidores.",
    )


def _interaction_balance(channel: UnifiedChannel, recent_views: int) -> list[AudienceSignal]:
    """Un 0 no cuenta: YouTube permite ocultar los me gusta y desactivar comentarios."""
    signals = []
    if channel.likes > 0 and recent_views >= 1_000:
        likes_share = channel.likes / recent_views * 100
        if likes_share < 0.1:
            signals.append(_signal(
                "views_without_likes",
                "Muchas vistas, casi sin me gusta",
                20,
                f"{channel.likes:,} me gusta en {recent_views:,} vistas recientes ({likes_share:.3f}%).",
            ))
    if channel.likes >= 200 and channel.comments > 0:
        comments_share = channel.comments / channel.likes * 100
        if comments_share < 0.2:
            signals.append(_signal(
                "likes_without_comments",
                "Muchos me gusta, casi sin comentarios",
                15,
                f"{channel.comments:,} comentarios por cada {channel.likes:,} me gusta ({comments_share:.2f}%).",
            ))
    return signals


def _view_spike(views: Sequence[int]) -> AudienceSignal | None:
    """Pesa poco a propósito: un video viral es lo más común del mundo."""
    highest = max(views)
    others = sorted(views)[:-1]
    typical = median(others)
    if typical <= 0 or highest / typical < 20:
        return None
    return _signal(
        "isolated_view_spike",
        "Un video muy por encima del resto",
        10,
        f"Un video tiene {highest:,} vistas y el resto, unas {int(typical):,}.",
    )


class _Snapshot(Protocol):
    snapshot_date: object
    followers: int
    total_views: int


def _history_signals(snapshots: Sequence[_Snapshot]) -> list[AudienceSignal]:
    """Salto o caída de seguidores entre fotos sucesivas. Un cambio de menos de 5% no se
    evalúa: YouTube redondea los suscriptores a 3 cifras y eso solo ya produce saltitos."""
    steps = []
    for previous, current in zip(snapshots, snapshots[1:], strict=False):
        if previous.followers < MIN_FOLLOWERS:
            continue
        days = max((current.snapshot_date - previous.snapshot_date).days, 1)
        change = (current.followers - previous.followers) / previous.followers * 100
        views_change = (
            (current.total_views - previous.total_views) / previous.total_views * 100
            if previous.total_views > 0 else 0.0
        )
        steps.append({"current": current, "change": change, "per_day": change / days, "views_change": views_change})
    if not steps:
        return []

    signals = []
    biggest_jump = max(steps, key=lambda s: s["per_day"])
    others = [abs(s["per_day"]) for s in steps if s is not biggest_jump]
    usual = median(others) if others else 0.0
    if biggest_jump["change"] >= 5 and biggest_jump["per_day"] >= 5 * max(usual, 0.1):
        flat_views = biggest_jump["views_change"] < biggest_jump["change"] / 4
        signals.append(_signal(
            "follower_jump",
            "Salto brusco de seguidores",
            40 if flat_views else 30,
            f"+{biggest_jump['change']:.1f}% de seguidores al {biggest_jump['current'].snapshot_date} "
            f"(lo habitual: {usual:.2f}% por día), con vistas {biggest_jump['views_change']:+.1f}%.",
        ))

    biggest_drop = min(steps, key=lambda s: s["change"])
    if biggest_drop["change"] <= -5:
        signals.append(_signal(
            "follower_drop",
            "Caída brusca de seguidores",
            25,
            f"{biggest_drop['change']:.1f}% de seguidores al {biggest_drop['current'].snapshot_date}: "
            "puede ser una depuración de cuentas falsas de la plataforma.",
        ))
    return signals


def _level(score: int, evaluated: int, followers: int) -> str:
    if evaluated < MIN_SIGNALS_EVALUATED or followers < MIN_FOLLOWERS:
        return "datos_insuficientes"
    if score >= LEVEL_HIGH:
        return "alta"
    if score >= LEVEL_REVIEW:
        return "revisar"
    if score >= LEVEL_MILD:
        return "leve"
    return "sin_senales"


def assess_channel(
    channel: UnifiedChannel,
    cohort_flagged: Iterable[str] | None = None,
    snapshots: Sequence[_Snapshot] | None = None,
) -> AudienceAssessment:
    """`cohort_flagged` son los canales marcados por `detect_anomalies` en su búsqueda (None
    si no hubo cohorte); `snapshots`, el historial del canal, del más viejo al más nuevo."""
    signals: list[AudienceSignal] = []
    evaluated = 0
    unavailable: list[str] = []

    def check(available: bool, name: str, compute) -> None:
        nonlocal evaluated
        if not available:
            unavailable.append(name)
            return
        evaluated += 1
        found = compute()
        if isinstance(found, list):
            signals.extend(found)
        elif found is not None:
            signals.append(found)

    big_enough = channel.followers >= MIN_FOLLOWERS
    check(
        big_enough and channel.total_views > 0 and channel.total_posts >= MIN_POSTS_FOR_LIFETIME_RATIO,
        "Vistas históricas por seguidor",
        lambda: _lifetime_views(channel),
    )
    check(big_enough and ner_available(channel), "Interacción", lambda: _low_engagement(channel))

    views = channel.recent_video_views or []
    check(
        channel.followers >= MIN_FOLLOWERS_FOR_RECENT_VIEWS and len(views) >= MIN_VIDEOS_FOR_RECENT_VIEWS,
        "Vistas de videos recientes",
        lambda: _recent_views(channel, views),
    )
    check(
        big_enough and sum(views) > 0,
        "Equilibrio entre vistas, me gusta y comentarios",
        lambda: _interaction_balance(channel, sum(views)),
    )
    check(len(views) >= MIN_VIDEOS_FOR_SPIKE, "Picos de vistas", lambda: _view_spike(views))

    flagged = None if cohort_flagged is None else set(cohort_flagged)
    check(
        flagged is not None,
        "Comparación con canales parecidos",
        lambda: _signal(
            "cohort_outlier",
            "Interacción muy por debajo de canales parecidos",
            15,
            "Está entre los más grandes de su búsqueda, con interacción anormalmente baja para el grupo.",
        ) if channel.universal_id in flagged else None,
    )
    check(
        snapshots is not None and len(snapshots) >= MIN_SNAPSHOTS_FOR_HISTORY,
        "Evolución de seguidores",
        lambda: _history_signals(snapshots),
    )

    signals.sort(key=lambda s: s.points, reverse=True)
    score = min(sum(s.points for s in signals), 100)
    if len(signals) == 1:
        score = min(score, SINGLE_SIGNAL_CAP)

    return AudienceAssessment(
        universal_id=channel.universal_id,
        name=channel.name,
        handle=channel.handle,
        url=channel.url,
        platform=channel.platform,
        followers=channel.followers,
        score=score,
        level=_level(score, evaluated, channel.followers),
        signals=signals,
        signals_evaluated=evaluated,
        signals_unavailable=unavailable,
        is_mock=channel.is_mock,
    )


def channel_from_snapshot(tracked, snapshot) -> UnifiedChannel:
    """El canal tal como quedó en su última foto. No guarda me gusta ni videos: esas señales
    quedan "no disponibles" y no se gasta cuota de la API para leer un canal ya trackeado."""
    platform = Platform(tracked.platform)
    return UnifiedChannel(
        universal_id=tracked.universal_id,
        native_id=tracked.native_id,
        platform=platform,
        content_format=ContentFormat.VOD if platform == Platform.YOUTUBE else ContentFormat.MICRO_VIDEO,
        name=tracked.name or tracked.label or tracked.native_id,
        handle=tracked.handle,
        url=tracked.url,
        followers=snapshot.followers,
        total_views=snapshot.total_views,
        total_posts=snapshot.total_posts,
        raw_interactions=snapshot.raw_interactions,
        normalized_er=snapshot.normalized_er,
        engagement_videos_sampled=1 if snapshot.raw_interactions > 0 else None,
        tier=ContentTier.classify(snapshot.followers),
        is_mock="_mock_" in tracked.native_id,
    )
