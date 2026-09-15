"""
CRUD y consultas sobre los canales trackeados (dim_channels) y sus
snapshots diarios (fact_channel_metrics_daily), más el catálogo de tipos
de canal (`channel_types`, ver `/api/v1/catalog/*`). Capa fina sobre
SQLAlchemy que usan tanto los endpoints de `/api/v1/tracking/*` y
`/api/v1/catalog/*` como el worker diario.
"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ChannelTypeInUseError, ChannelTypeNotFoundError, DuplicateChannelTypeError
from app.db.models import ChannelMetricSnapshot, ChannelType, TrackedChannel
from app.models.domain import Platform
from app.models.schemas import UnifiedChannel
from app.services.orchestrator import category_label, discover_by_category_unified


def slugify(name: str) -> str:
    """Slug simple (minúsculas, sin acentos, guiones) para `ChannelType.slug`."""
    normalized = (
        name.lower()
        .replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u").replace("ñ", "n")
    )
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return slug or "tipo"


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
    channel_type_id: int | None = None,
) -> TrackedChannel:
    existing = await find_by_platform_native_id(session, platform, native_id)
    if existing is not None:
        # Reactivar si estaba dado de baja, y refrescar metadatos livianos.
        existing.active = True
        existing.handle = handle or existing.handle
        existing.label = label or existing.label
        existing.name = name or existing.name
        existing.url = url or existing.url
        existing.channel_type_id = channel_type_id or existing.channel_type_id
        await session.commit()
        await session.refresh(existing)
        return existing

    platform_value = platform.value if hasattr(platform, "value") else platform
    tracked = TrackedChannel(
        platform=platform_value, native_id=native_id, handle=handle, label=label, name=name, url=url, active=True,
        channel_type_id=channel_type_id,
    )
    session.add(tracked)
    await session.commit()
    await session.refresh(tracked)
    return tracked


async def set_channel_type(session: AsyncSession, tracked_id: int, channel_type_id: int | None) -> TrackedChannel | None:
    """Asigna (o quita, con `channel_type_id=None`) el tipo de canal de un canal ya trackeado."""
    tracked = await session.get(TrackedChannel, tracked_id)
    if tracked is None:
        return None
    tracked.channel_type_id = channel_type_id
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


# ─────────────────────────────────────────────────────────────────────────
# Catálogo de canales: tipos de canal (YouTube + propios) y cantidades
# ─────────────────────────────────────────────────────────────────────────

async def list_channel_types(session: AsyncSession) -> list[ChannelType]:
    stmt = select(ChannelType).order_by(ChannelType.is_custom, ChannelType.name)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_channel_type(session: AsyncSession, type_id: int) -> ChannelType | None:
    return await session.get(ChannelType, type_id)


async def find_channel_type_by_name(session: AsyncSession, name: str) -> ChannelType | None:
    """Busca un tipo de canal por nombre, sin distinguir mayúsculas/minúsculas."""
    stmt = select(ChannelType).where(func.lower(ChannelType.name) == name.strip().lower())
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create_channel_type(session: AsyncSession, name: str, description: str | None = None) -> ChannelType:
    """
    Crea un tipo de canal propio (`is_custom=True`). Usado por
    `POST /api/v1/catalog/types` — a diferencia de
    `get_or_create_channel_type_by_name`, rechaza duplicados en vez de
    reusar el existente, porque acá el usuario está creando un tipo a
    propósito y un 409 avisa antes de que crea que hizo uno nuevo.
    """
    name = name.strip()
    if await find_channel_type_by_name(session, name) is not None:
        raise DuplicateChannelTypeError(name)
    channel_type = ChannelType(name=name, slug=slugify(name), description=description, is_custom=True)
    session.add(channel_type)
    await session.commit()
    await session.refresh(channel_type)
    return channel_type


async def get_or_create_channel_type_by_name(session: AsyncSession, name: str) -> ChannelType:
    """
    Variante "silenciosa" de `create_channel_type`: reusa el tipo si ya
    existe (comparación case-insensitive) o lo crea de una si no. Pensada
    para `TrackedChannelCreate.channel_type_name` — el flujo de "+ Seguir"
    desde "Por categoría" ya conoce el nombre de la categoría de YouTube y
    no debería fallar con un 409 solo porque otro canal ya la usó antes.
    """
    existing = await find_channel_type_by_name(session, name)
    if existing is not None:
        return existing
    name = name.strip()
    channel_type = ChannelType(name=name, slug=slugify(name), is_custom=True)
    session.add(channel_type)
    await session.commit()
    await session.refresh(channel_type)
    return channel_type


async def delete_channel_type(session: AsyncSession, type_id: int) -> None:
    """
    Borra un tipo de canal. Falla con `ChannelTypeNotFoundError` si no
    existe, o con `ChannelTypeInUseError` si algún canal trackeado
    todavía lo tiene asignado (hay que reasignarlo primero) — evita dejar
    canales apuntando a un `channel_type_id` fantasma.
    """
    channel_type = await session.get(ChannelType, type_id)
    if channel_type is None:
        raise ChannelTypeNotFoundError(type_id)

    count_stmt = select(func.count()).select_from(TrackedChannel).where(TrackedChannel.channel_type_id == type_id)
    in_use = (await session.execute(count_stmt)).scalar_one()
    if in_use > 0:
        raise ChannelTypeInUseError(type_id, in_use)

    await session.delete(channel_type)
    await session.commit()


async def catalog_summary(session: AsyncSession) -> dict:
    """
    Cantidad de canales trackeados ACTIVOS por tipo de canal — la vista de
    "cantidades" del catálogo (pestaña "Catálogo" del dashboard). Los
    inactivos (dados de baja) no se cuentan, igual que en `/tracking/channels`
    sin `include_inactive`. Un canal sin `channel_type_id` cae en el bucket
    "sin tipo" (`channel_type=None` en `ChannelTypeCount`).
    """
    types = await list_channel_types(session)

    count_stmt = (
        select(TrackedChannel.channel_type_id, func.count())
        .where(TrackedChannel.active.is_(True))
        .group_by(TrackedChannel.channel_type_id)
    )
    counts_by_id: dict[int | None, int] = dict((await session.execute(count_stmt)).all())

    by_type = [
        {"channel_type": ct, "channel_count": counts_by_id.get(ct.id, 0)}
        for ct in types
    ]
    unassigned_count = counts_by_id.get(None, 0)
    if unassigned_count:
        by_type.append({"channel_type": None, "channel_count": unassigned_count})
    by_type.sort(key=lambda row: row["channel_count"], reverse=True)

    total = sum(row["channel_count"] for row in by_type)
    return {"total": total, "by_type": by_type}


# ─────────────────────────────────────────────────────────────────────────
# Descubrimiento + alta masiva de canales (manual vía endpoint, o
# automática vía el job de `core/scheduler.py` — ver `ENABLE_AUTO_DISCOVERY`)
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class DiscoverAndTrackCategoryResult:
    platform: Platform
    category: str
    label: str
    channels_found: int
    channels_tracked: int


@dataclass
class DiscoverAndTrackResult:
    total_limit: int
    total_tracked: int
    platforms: list[Platform] = field(default_factory=list)
    by_category: list[DiscoverAndTrackCategoryResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


async def discover_and_track_channels(
    session: AsyncSession, platform: Platform, total_limit: int, sort_by: str = "followers",
) -> DiscoverAndTrackResult:
    """
    Descubre canales reales de todos los temas/categorías (mismo camino que
    `GET /channels/discover/by-category`: trending real si hay
    `YOUTUBE_API_KEY`, mock determinístico si no) y los agrega al
    seguimiento diario hasta `total_limit`, repartidos en ROUND-ROBIN entre
    categorías/temas — así una categoría grande (música, gaming) no agota
    sola todo el cupo. Cada canal queda con su tipo de canal (catálogo)
    asignado según la categoría en la que se descubrió. Un canal que ya
    estaba trackeado no se duplica (`create_tracked` hace upsert por
    `native_id`).

    Lógica compartida entre `POST /api/v1/tracking/discover-and-track`
    (disparo manual, ver `app/api/v1/endpoints/tracking.py`) y el job
    automático de descubrimiento (`app/core/scheduler.py`, activado con
    `ENABLE_AUTO_DISCOVERY=true`) — para que un proyecto de investigación
    con acceso real a las APIs pueda hacer crecer el dataset solo, sin
    tener que disparar el alta a mano cada vez.
    """
    by_platform = await discover_by_category_unified(
        platforms=[platform], limit_per_category=total_limit, sort_by=sort_by,
    )

    # Aplanamos a una lista de "carriles" (uno por categoría/tema de cada
    # plataforma) para repartir `total_limit` en ROUND-ROBIN -- un canal de
    # cada carril por vuelta, no categoría por categoría.
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

    return DiscoverAndTrackResult(
        total_limit=total_limit,
        total_tracked=total_tracked,
        platforms=list(by_platform.keys()),
        by_category=[
            DiscoverAndTrackCategoryResult(
                platform=lane["platform"], category=lane["category"], label=lane["label"],
                channels_found=len(lane["channels"]), channels_tracked=lane["tracked"],
            )
            for lane in lanes
        ],
        errors=errors,
    )
