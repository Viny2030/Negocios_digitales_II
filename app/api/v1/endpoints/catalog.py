"""
Catálogo de canales: taxonomía de "tipo de canal" flexible (combina las
15 categorías nativas de YouTube, sembradas al arrancar la app — ver
`db/session.py::_seed_default_channel_types` — con tipos propios que se
pueden crear en cualquier momento sin tocar código) más la vista de
cantidades por tipo, para la pestaña "Catálogo" del dashboard.

Un `ChannelType` es una etiqueta sobre un canal ya trackeado (`/tracking/*`
sigue siendo el único lugar donde se da de alta/baja un canal y se guardan
sus snapshots) — este router no agrega una tabla de storage nueva de
canales, solo clasifica los que ya existen.

Igual que `/tracking/*`, los endpoints de escritura exigen `X-Admin-Token`
únicamente si `ADMIN_TOKEN` está configurado (default local = sin protección).
"""
import time

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import verify_admin_token
from app.api.v1.endpoints.tracking import _tracked_out
from app.core.exceptions import ChannelTypeNotFoundError, TrackedChannelNotFoundError
from app.db.session import get_session
from app.models.schemas import (
    CatalogSummaryResponse,
    ChannelTypeCount,
    ChannelTypeCreate,
    ChannelTypeListResponse,
    ChannelTypeOut,
    ExecutionMeta,
    SetChannelTypeRequest,
    TrackedChannelOut,
)
from app.services.tracked_channels import (
    catalog_summary,
    create_channel_type,
    delete_channel_type,
    get_channel_type,
    get_tracked,
    list_channel_types,
    set_channel_type,
)

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get(
    "/types", response_model=ChannelTypeListResponse,
    summary="Listar tipos de canal (categorías de YouTube + tipos propios)",
)
async def get_channel_types(session: AsyncSession = Depends(get_session)) -> ChannelTypeListResponse:
    start = time.perf_counter()
    types = await list_channel_types(session)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return ChannelTypeListResponse(
        meta=ExecutionMeta(response_time_ms=round(elapsed_ms, 2)),
        types=[ChannelTypeOut.model_validate(t) for t in types],
    )


@router.post(
    "/types", response_model=ChannelTypeOut, dependencies=[Depends(verify_admin_token)],
    summary="Crear un tipo de canal propio",
)
async def add_channel_type(
    payload: ChannelTypeCreate, session: AsyncSession = Depends(get_session),
) -> ChannelTypeOut:
    channel_type = await create_channel_type(session, name=payload.name, description=payload.description)
    return ChannelTypeOut.model_validate(channel_type)


@router.delete(
    "/types/{type_id}", dependencies=[Depends(verify_admin_token)],
    summary="Borrar un tipo de canal (falla si algún canal trackeado todavía lo tiene asignado)",
)
async def remove_channel_type(type_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    await delete_channel_type(session, type_id)
    return {"status": "ok", "id": type_id}


@router.get(
    "/summary", response_model=CatalogSummaryResponse,
    summary="Cantidad de canales trackeados activos por tipo de canal",
)
async def get_catalog_summary(session: AsyncSession = Depends(get_session)) -> CatalogSummaryResponse:
    start = time.perf_counter()
    summary = await catalog_summary(session)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return CatalogSummaryResponse(
        meta=ExecutionMeta(response_time_ms=round(elapsed_ms, 2)),
        total_channels=summary["total"],
        by_type=[
            ChannelTypeCount(
                channel_type=ChannelTypeOut.model_validate(row["channel_type"]) if row["channel_type"] else None,
                channel_count=row["channel_count"],
            )
            for row in summary["by_type"]
        ],
    )


@router.patch(
    "/channels/{tracked_id}/type", response_model=TrackedChannelOut, dependencies=[Depends(verify_admin_token)],
    summary="Asignar (o quitar) el tipo de canal de un canal ya trackeado",
)
async def update_channel_type(
    tracked_id: int, payload: SetChannelTypeRequest, session: AsyncSession = Depends(get_session),
) -> TrackedChannelOut:
    tracked = await get_tracked(session, tracked_id)
    if tracked is None:
        raise TrackedChannelNotFoundError(tracked_id)
    if payload.channel_type_id is not None and await get_channel_type(session, payload.channel_type_id) is None:
        raise ChannelTypeNotFoundError(payload.channel_type_id)
    updated = await set_channel_type(session, tracked_id, payload.channel_type_id)
    return await _tracked_out(session, updated)
