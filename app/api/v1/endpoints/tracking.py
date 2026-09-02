"""
Endpoints de seguimiento diario: alta/baja de canales trackeados,
historial de snapshots, y disparo manual del worker diario (sin esperar
a que corra el scheduler a las 3am UTC).

Todos requieren el header `X-Admin-Token` únicamente si `ADMIN_TOKEN` está
configurado en el entorno — por defecto (uso local) quedan abiertos.
"""
import time

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import verify_admin_token
from app.core.config import get_settings
from app.core.exceptions import ChannelNotFoundError, TrackedChannelNotFoundError
from app.db.session import get_session
from app.models.schemas import (
    BulkTrackCategoryResult,
    BulkTrackResponse,
    ChannelHistoryResponse,
    ChannelSnapshotOut,
    ChannelTypeOut,
    DailyJobResultOut,
    ExecutionMeta,
    TrackedChannelCreate,
    TrackedChannelListResponse,
    TrackedChannelOut,
)
from app.services.analytics.normalizer import normalize_channels
from app.services.collectors.tiktok import TikTokCollector
from app.services.collectors.youtube import YouTubeCollector
from app.services.orchestrator import DISCOVER_SORT_FIELDS, category_label, discover_by_category_unified
from app.services.tracked_channels import (
    create_tracked,
    deactivate_tracked,
    get_channel_type,
    get_or_create_channel_type_by_name,
    get_tracked,
    latest_snapshot,
    list_tracked,
    snapshot_history,
    upsert_snapshot_from_channel,
)
from app.services.worker import run_daily_snapshot
from app.models.domain import Platform

router = APIRouter(prefix="/tracking", tags=["tracking"])
settings = get_settings()

_COLLECTORS = {Platform.YOUTUBE: YouTubeCollector, Platform.TIKTOK: TikTokCollector}


def _snapshot_out(snapshot) -> ChannelSnapshotOut | None:
    if snapshot is None:
        return None
    return ChannelSnapshotOut(
        snapshot_date=snapshot.snapshot_date,
        followers=snapshot.followers,
        total_views=snapshot.total_views,
        total_posts=snapshot.total_posts,
        normalized_er=snapshot.normalized_er,
        tier=snapshot.tier,
    )


async def _tracked_out(session: AsyncSession, tracked) -> TrackedChannelOut:
    snap = await latest_snapshot(session, tracked.id)
    channel_type = (
        await get_channel_type(session, tracked.channel_type_id) if tracked.channel_type_id else None
    )
    return TrackedChannelOut(
        id=tracked.id, platform=tracked.platform, native_id=tracked.native_id, handle=tracked.handle,
        label=tracked.label, name=tracked.name, url=tracked.url, active=tracked.active,
        created_at=tracked.created_at, latest_snapshot=_snapshot_out(snap),
        channel_type=ChannelTypeOut.model_validate(channel_type) if channel_type else None,
    )


@router.post(
    "/channels", response_model=TrackedChannelOut, dependencies=[Depends(verify_admin_token)],
    summary="Agregar un canal al seguimiento diario",
)
async def add_tracked_channel(
    payload: TrackedChannelCreate, session: AsyncSession = Depends(get_session),
) -> TrackedChannelOut:
    """
    Resuelve el identificador contra la API (o el modo mock) para validar
    que el canal existe y traer sus metadatos reales, lo guarda como
    trackeado, y toma un primer snapshot de una — así no hay que esperar
    a la corrida diaria para ver el primer dato.

    El tipo de canal (catálogo) es opcional: `channel_type_id` referencia
    un tipo ya existente; `channel_type_name` (usado por el botón "+ Seguir"
    de "Por categoría", que ya conoce el nombre de la categoría de YouTube)
    lo busca por nombre o lo crea de una si no existe todavía. Si vienen
    los dos, `channel_type_id` gana.
    """
    collector = _COLLECTORS[payload.platform]()
    raw = await collector.get_channel(payload.identifier)
    if raw is None:
        raise ChannelNotFoundError(payload.platform.value, payload.identifier)

    channel = normalize_channels([raw], payload.platform)[0]

    channel_type_id = payload.channel_type_id
    if channel_type_id is None and payload.channel_type_name:
        channel_type = await get_or_create_channel_type_by_name(session, payload.channel_type_name)
        channel_type_id = channel_type.id

    tracked = await create_tracked(
        session, platform=payload.platform, native_id=channel.native_id, handle=channel.handle,
        label=payload.label, name=channel.name, url=channel.url, channel_type_id=channel_type_id,
    )
    await upsert_snapshot_from_channel(session, tracked.id, channel)
    return await _tracked_out(session, tracked)


@router.post(
    "/discover-and-track", response_model=BulkTrackResponse, dependencies=[Depends(verify_admin_token)],
    summary="Descubrir canales reales de todos los temas y trackearlos de una sola vez (soluciona 'tengo pocos canales trackeados')",
)
async def discover_and_track(
    platform: Platform = Query(Platform.YOUTUBE, description="youtube | tiktok | all"),
    total_limit: int = Query(
        200, ge=1, le=settings.DISCOVER_MAX_LIMIT,
        description="Cantidad total de canales a trackear, repartidos entre las categorías/temas",
    ),
    sort_by: str = Query(
        "followers", pattern=f"^({'|'.join(DISCOVER_SORT_FIELDS)})$",
        description="Qué canales priorizar dentro de cada categoría antes de trackear",
    ),
    session: AsyncSession = Depends(get_session),
) -> BulkTrackResponse:
    """
    Versión "de una sola vez" de agregar canales al seguimiento: en vez de
    `POST /tracking/channels` canal por canal, o "+ Seguir" uno por uno
    desde "Por categoría" en el dashboard, reusa el mismo descubrimiento
    real de `GET /channels/discover/by-category` (trending de YouTube por
    categoría+región -- datos reales si hay `YOUTUBE_API_KEY` configurada,
    mock determinístico si no) y trackea hasta `total_limit` canales de
    una, repartidos entre TODAS las categorías/temas de la plataforma
    elegida -- para cubrir "canales de distintos temas" en vez de que un
    género grande (música, gaming) se lleve todo el cupo.

    Cada canal queda con su tipo de canal (catálogo, ver `/catalog/*`)
    asignado automáticamente según la categoría en la que se descubrió,
    igual que "+ Seguir" desde "Por categoría" -- pero para muchos canales
    de una. A diferencia de agregar uno por uno, NO repite una llamada a
    la API por canal: reusa los datos ya normalizados que trajo el
    descubrimiento, así que trackear 1000 canales es rápido y no gasta
    cuota extra de YouTube más allá de la del propio descubrimiento.

    Un canal que ya estaba trackeado no se duplica (`create_tracked` hace
    upsert por `native_id`) -- correr esto de nuevo más adelante sirve
    para sumar canales nuevos sin tocar los que ya tenías.
    """
    start = time.perf_counter()

    # `limit_per_category` no cambia cuánto le cuesta esto a la cuota de
    # YouTube: las llamadas reales (trending por región+categoría, y el
    # batch de channels.list) ya salen a costo fijo antes de este corte
    # (ver `YouTubeCollector._discover_trending_channel_ids_by_category`);
    # el recorte a `limit_per_category` pasa después, en memoria. Por eso
    # alcanza con pedirle `total_limit` a cada categoría tal cual y dejar
    # que el loop de más abajo corte el TOTAL exacto en `total_limit`, sin
    # necesidad de estimar cuántas categorías tiene cada plataforma.
    by_platform = await discover_by_category_unified(
        platforms=[platform], limit_per_category=total_limit, sort_by=sort_by,
    )

    # Aplanamos a una lista de "carriles" (uno por categoría/tema de cada
    # plataforma) para repartir `total_limit` en ROUND-ROBIN -- un canal de
    # cada carril por vuelta, no categoría por categoría. Si no fuera así,
    # una categoría grande (p. ej. música) podría agotar sola todo el cupo
    # antes de que el loop llegue a tocar el resto, dejando "canales de
    # distintos temas" (el pedido original) sin cumplir cuando `total_limit`
    # es chico en relación a lo que trae esa única categoría.
    lanes = [
        {"platform": p, "category": category_key, "label": category_label(p, category_key),
         "channels": channels, "next_index": 0, "tracked": 0}
        for p, by_category in by_platform.items()
        for category_key, channels in by_category.items()
    ]

    # Cachea el tipo de canal por (plataforma, categoría) para no repetir
    # la búsqueda/creación por cada canal de una misma categoría.
    channel_type_cache: dict[tuple[Platform, str], int] = {}
    errors: list[str] = []
    total_tracked = 0

    made_progress = True
    while total_tracked < total_limit and made_progress:
        made_progress = False
        for lane in lanes:
            if total_tracked >= total_limit:
                break
            if lane["next_index"] >= len(lane["channels"]):
                continue  # este carril ya se quedó sin canales, se saltea

            channel = lane["channels"][lane["next_index"]]
            lane["next_index"] += 1
            made_progress = True

            try:
                cache_key = (lane["platform"], lane["category"])
                channel_type_id = channel_type_cache.get(cache_key)
                if channel_type_id is None:
                    channel_type = await get_or_create_channel_type_by_name(session, lane["label"])
                    channel_type_id = channel_type.id
                    channel_type_cache[cache_key] = channel_type_id

                tracked = await create_tracked(
                    session, platform=lane["platform"], native_id=channel.native_id, handle=channel.handle,
                    label=None, name=channel.name, url=channel.url, channel_type_id=channel_type_id,
                )
                await upsert_snapshot_from_channel(session, tracked.id, channel)
                total_tracked += 1
                lane["tracked"] += 1
            except Exception as e:
                # Un canal individual que falla (p. ej. una violación de
                # constraint) puede dejar la sesión en estado "aborted" para
                # SQLAlchemy -- hay que hacer rollback antes de seguir con el
                # próximo canal, si no todos los que vengan después fallan en
                # cascada con el mismo error.
                await session.rollback()
                platform_value = lane["platform"].value if hasattr(lane["platform"], "value") else lane["platform"]
                errors.append(f"{platform_value}:{channel.native_id} — {e}")

    by_category_results = [
        BulkTrackCategoryResult(
            platform=lane["platform"], category=lane["category"], label=lane["label"],
            channels_found=len(lane["channels"]), channels_tracked=lane["tracked"],
        )
        for lane in lanes
    ]

    elapsed_ms = (time.perf_counter() - start) * 1000
    return BulkTrackResponse(
        meta=ExecutionMeta(
            query=f"discover_and_track:{sort_by}", platforms_requested=list(by_platform.keys()),
            response_time_ms=round(elapsed_ms, 2),
        ),
        total_limit=total_limit,
        total_tracked=total_tracked,
        by_category=by_category_results,
        errors=errors,
    )


@router.get(
    "/channels", response_model=TrackedChannelListResponse, summary="Listar canales trackeados",
)
async def list_tracked_channels(
    include_inactive: bool = Query(False), session: AsyncSession = Depends(get_session),
) -> TrackedChannelListResponse:
    start = time.perf_counter()
    tracked_list = await list_tracked(session, active_only=not include_inactive)
    channels = [await _tracked_out(session, tc) for tc in tracked_list]
    elapsed_ms = (time.perf_counter() - start) * 1000
    return TrackedChannelListResponse(
        meta=ExecutionMeta(response_time_ms=round(elapsed_ms, 2)), channels=channels,
    )


@router.delete(
    "/channels/{tracked_id}", dependencies=[Depends(verify_admin_token)], summary="Dejar de trackear un canal",
)
async def remove_tracked_channel(tracked_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    """
    Baja lógica (`active=False`): el historial de snapshots ya tomado se
    conserva, solo se excluye del próximo job diario y de los listados
    por defecto.
    """
    ok = await deactivate_tracked(session, tracked_id)
    if not ok:
        raise TrackedChannelNotFoundError(tracked_id)
    return {"status": "ok", "id": tracked_id, "active": False}


@router.get(
    "/channels/{tracked_id}/history", response_model=ChannelHistoryResponse,
    summary="Historial de snapshots diarios de un canal trackeado",
)
async def channel_history(
    tracked_id: int, days: int = Query(30, ge=1, le=365), session: AsyncSession = Depends(get_session),
) -> ChannelHistoryResponse:
    start = time.perf_counter()
    tracked = await get_tracked(session, tracked_id)
    if tracked is None:
        raise TrackedChannelNotFoundError(tracked_id)

    snapshots = await snapshot_history(session, tracked_id, days=days)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return ChannelHistoryResponse(
        meta=ExecutionMeta(response_time_ms=round(elapsed_ms, 2)),
        channel=await _tracked_out(session, tracked),
        snapshots=[_snapshot_out(s) for s in snapshots],
    )


@router.post(
    "/run-daily-job", response_model=DailyJobResultOut, dependencies=[Depends(verify_admin_token)],
    summary="Disparar el worker diario ahora mismo (sin esperar al scheduler)",
)
async def trigger_daily_job() -> DailyJobResultOut:
    start = time.perf_counter()
    result = await run_daily_snapshot()
    elapsed_ms = (time.perf_counter() - start) * 1000
    return DailyJobResultOut(
        meta=ExecutionMeta(response_time_ms=round(elapsed_ms, 2)),
        channels_evaluated=result.channels_evaluated,
        snapshots_created=result.snapshots_created,
        snapshots_updated=result.snapshots_updated,
        errors=result.errors,
    )
