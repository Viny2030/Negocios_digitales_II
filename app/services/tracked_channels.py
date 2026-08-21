"""
CRUD y consultas sobre los canales trackeados (dim_channels) y sus
snapshots diarios (fact_channel_metrics_daily). Capa fina sobre SQLAlchemy
que usan tanto los endpoints de `/api/v1/tracking/*` como el worker diario.
"""
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChannelMetricSnapshot, TrackedChannel
from app.models.domain import Platform
from app.models.schemas import UnifiedChannel


async def list_tracked(session: AsyncSession, active_only: bool = True) -> list[TrackedChannel]:
    stmt = select(TrackedChannel)
    if active_only:
        stmt = stmt.where(TrackedChannel.active.is_(True))
    stmt = stmt.order_by(TrackedChannel.created_at)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_tracked(session: AsyncSession, tracked_id: int) -> TrackedChannel | None:
    return await session.get(TrackedChannel, tracked_id)


async def find_by_platform_native_id(session: AsyncSession, platform: Platform, native_id: str) -> TrackedChannel | None:
    stmt = select(TrackedChannel).where(
        TrackedChannel.platform == platform.value if hasattr(platform, "value") else platform,
        TrackedChannel.native_id == native_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create_tracked(
    session: AsyncSession,
    platform: Platform,
    native_id: str,
    handle: str | None,
    label: str | None,
    name: str | None,
    url: str | None,
) -> TrackedChannel:
    existing = await find_by_platform_native_id(session, platform, native_id)
    if existing is not None:
        # Reactivar si estaba dado de baja, y refrescar metadatos livianos.
        existing.active = True
        existing.handle = handle or existing.handle
        existing.label = label or existing.label
        existing.name = name or existing.name
        existing.url = url or existing.url
        await session.commit()
        await session.refresh(existing)
        return existing

    platform_value = platform.value if hasattr(platform, "value") else platform
    tracked = TrackedChannel(
        platform=platform_value, native_id=native_id, handle=handle, label=label, name=name, url=url, active=True,
    )
    session.add(tracked)
    await session.commit()
    await session.refresh(tracked)
    return tracked


async def deactivate_tracked(session: AsyncSession, tracked_id: int) -> bool:
    tracked = await session.get(TrackedChannel, tracked_id)
    if tracked is None:
        return False
    tracked.active = False
    await session.commit()
    return True


async def latest_snapshot(session: AsyncSession, tracked_id: int) -> ChannelMetricSnapshot | None:
    stmt = (
        select(ChannelMetricSnapshot)
        .where(ChannelMetricSnapshot.tracked_channel_id == tracked_id)
        .order_by(ChannelMetricSnapshot.snapshot_date.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def snapshot_history(session: AsyncSession, tracked_id: int, days: int = 30) -> list[ChannelMetricSnapshot]:
    since = date.today() - timedelta(days=days)
    stmt = (
        select(ChannelMetricSnapshot)
        .where(ChannelMetricSnapshot.tracked_channel_id == tracked_id, ChannelMetricSnapshot.snapshot_date >= since)
        .order_by(ChannelMetricSnapshot.snapshot_date)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def upsert_snapshot_from_channel(
    session: AsyncSession, tracked_channel_id: int, channel: UnifiedChannel, snapshot_date: date | None = None,
) -> tuple[ChannelMetricSnapshot, bool]:
    """
    Guarda un snapshot para hoy (o `snapshot_date`) a partir de un
    `UnifiedChannel` ya normalizado. Idempotente: si ya existe un snapshot
    para ese canal+día, lo actualiza en vez de duplicarlo — así correr el
    job dos veces el mismo día (p. ej. a mano, para probar) es seguro.
    """
    snap_date = snapshot_date or date.today()
    stmt = select(ChannelMetricSnapshot).where(
        ChannelMetricSnapshot.tracked_channel_id == tracked_channel_id,
        ChannelMetricSnapshot.snapshot_date == snap_date,
    )
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    tier_value = channel.tier if isinstance(channel.tier, str) else channel.tier.value

    if existing is not None:
        existing.followers = channel.followers
        existing.total_views = channel.total_views
        existing.total_posts = channel.total_posts
        existing.raw_interactions = channel.raw_interactions
        existing.normalized_er = channel.normalized_er
        existing.tier = tier_value
        existing.fetched_at = datetime.utcnow()
        await session.commit()
        return existing, False

    snapshot = ChannelMetricSnapshot(
        tracked_channel_id=tracked_channel_id,
        snapshot_date=snap_date,
        followers=channel.followers,
        total_views=channel.total_views,
        total_posts=channel.total_posts,
        raw_interactions=channel.raw_interactions,
        normalized_er=channel.normalized_er,
        tier=tier_value,
    )
    session.add(snapshot)
    await session.commit()
    await session.refresh(snapshot)
    return snapshot, True
