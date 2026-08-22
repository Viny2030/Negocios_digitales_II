"""
Funcionalidades exclusivas del plan premium sobre canales YA trackeados
(`/tracking/channels`): proyecciones de tendencia y recomendaciones de
política general por métrica. Ambas requieren `plan == 'premium'` activo
(ver `app.api.deps.require_premium`) — 'unica'/'mensual' NO alcanzan.

  GET /premium/channels/{tracked_id}/projections     -> extrapolación lineal
                                                          simple por métrica
  GET /premium/channels/{tracked_id}/recommendations  -> reglas basadas en
                                                          benchmarks + tendencia
"""
import time

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_premium
from app.core.exceptions import InsufficientDataError, TrackedChannelNotFoundError
from app.db.models import User
from app.db.session import get_session
from app.models.domain import Platform
from app.models.schemas import (
    ChannelProjectionResponse,
    ChannelRecommendationResponse,
    ExecutionMeta,
    MetricProjection,
    ProjectionPoint,
    RecommendationItem,
)
from app.services.analytics.projections import MIN_SNAPSHOTS_FOR_PROJECTION, project_channel, project_metric
from app.services.analytics.recommendations import recommend_for_channel
from app.services.tracked_channels import get_tracked, snapshot_history

router = APIRouter(prefix="/premium", tags=["premium"], dependencies=[Depends(require_premium)])


def _parse_weeks_ahead(raw: str) -> list[int]:
    weeks = [int(w) for w in raw.split(",") if w.strip()]
    return weeks or [1, 4, 12]


@router.get(
    "/channels/{tracked_id}/projections",
    response_model=ChannelProjectionResponse,
    summary="[Premium] Proyección de tendencia por métrica (extrapolación lineal sobre el histórico semanal)",
)
async def channel_projections(
    tracked_id: int,
    weeks_ahead: str = Query("1,4,12", description="Semanas a proyectar, separadas por coma (ej: '1,4,12')"),
    session: AsyncSession = Depends(get_session),
) -> ChannelProjectionResponse:
    start = time.perf_counter()

    tracked = await get_tracked(session, tracked_id)
    if tracked is None:
        raise TrackedChannelNotFoundError(tracked_id)

    weeks = _parse_weeks_ahead(weeks_ahead)
    snapshots = await snapshot_history(session, tracked_id, days=3650)

    raw_projections = project_channel(snapshots, weeks_ahead=weeks)
    projections = [
        MetricProjection(
            field=item["field"],
            history_points=item["history_points"],
            weekly_trend=item["weekly_trend"],
            projections=[ProjectionPoint(**p) for p in item["projections"]],
            confidence_note=item["confidence_note"],
        )
        for item in raw_projections
    ]

    elapsed_ms = (time.perf_counter() - start) * 1000
    return ChannelProjectionResponse(
        meta=ExecutionMeta(response_time_ms=round(elapsed_ms, 2)),
        tracked_channel_id=tracked_id,
        projections=projections,
    )


@router.get(
    "/channels/{tracked_id}/recommendations",
    response_model=ChannelRecommendationResponse,
    summary="[Premium] Recomendaciones de política general para mejorar cada métrica",
)
async def channel_recommendations(
    tracked_id: int, session: AsyncSession = Depends(get_session),
) -> ChannelRecommendationResponse:
    start = time.perf_counter()

    tracked = await get_tracked(session, tracked_id)
    if tracked is None:
        raise TrackedChannelNotFoundError(tracked_id)

    snapshots = await snapshot_history(session, tracked_id, days=3650)
    if not snapshots:
        raise InsufficientDataError(
            f"El canal trackeado {tracked_id} todavía no tiene ningún snapshot — esperá a la próxima "
            f"corrida semanal del worker o disparalo a mano desde 'Seguimiento diario'."
        )
    latest = snapshots[-1]

    weekly_follower_trend = None
    if len(snapshots) >= MIN_SNAPSHOTS_FOR_PROJECTION:
        try:
            trend_result = project_metric(snapshots, "followers", weeks_ahead=[1])
            weekly_follower_trend = trend_result["weekly_trend"]
        except InsufficientDataError:
            weekly_follower_trend = None

    items = recommend_for_channel(
        platform=Platform(tracked.platform),
        followers=latest.followers,
        total_posts=latest.total_posts,
        normalized_er=latest.normalized_er,
        weekly_follower_trend=weekly_follower_trend,
    )

    elapsed_ms = (time.perf_counter() - start) * 1000
    return ChannelRecommendationResponse(
        meta=ExecutionMeta(response_time_ms=round(elapsed_ms, 2)),
        tracked_channel_id=tracked_id,
        recommendations=[RecommendationItem(**item) for item in items],
    )
