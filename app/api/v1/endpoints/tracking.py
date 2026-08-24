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
