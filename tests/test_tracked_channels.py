"""
Tests unitarios de la capa de persistencia del seguimiento diario
(`services/tracked_channels.py`): alta/baja de canales trackeados y
snapshots idempotentes. Usa un engine SQLite propio en memoria por test,
totalmente aislado del `channel_analytics.db` que usa la app real.
"""
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.models.domain import ContentFormat, ContentTier, Platform
from app.models.schemas import UnifiedChannel
from app.services.tracked_channels import (
    create_tracked,
    deactivate_tracked,
    find_by_platform_native_id,
    get_tracked,
    latest_snapshot,
    list_tracked,
    snapshot_history,
    upsert_snapshot_from_channel,
)


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _channel(native_id: str = "UC123", followers: int = 1000, er: float = 2.5) -> UnifiedChannel:
    return UnifiedChannel(
        universal_id=f"youtube:{native_id}",
        native_id=native_id,
        platform=Platform.YOUTUBE,
        content_format=ContentFormat.VOD,
        name="Canal de prueba",
        handle="@prueba",
        url=f"https://www.youtube.com/channel/{native_id}",
        followers=followers,
        total_views=50_000,
        total_posts=100,
        raw_interactions=500,
        normalized_er=er,
        tier=ContentTier.MICRO,
    )


@pytest.mark.asyncio
async def test_create_tracked_new_channel(session):
    tracked = await create_tracked(
        session, platform=Platform.YOUTUBE, native_id="UC123", handle="@prueba",
        label="Competidor A", name="Canal", url="https://youtube.com/x",
    )
    assert tracked.id is not None
    assert tracked.active is True
    assert tracked.platform == "youtube"
    assert tracked.universal_id == "youtube:UC123"


@pytest.mark.asyncio
async def test_create_tracked_upserts_existing_and_reactivates(session):
    first = await create_tracked(
        session, platform=Platform.YOUTUBE, native_id="UC123", handle="@old",
        label="Original", name="Nombre viejo", url="https://youtube.com/x",
    )
    await deactivate_tracked(session, first.id)

    again = await create_tracked(
        session, platform=Platform.YOUTUBE, native_id="UC123", handle="@nuevo",
        label=None, name="Nombre nuevo", url="https://youtube.com/x",
    )
    # Mismo registro (mismo id), reactivado, sin duplicar filas.
    assert again.id == first.id
    assert again.active is True
    assert again.handle == "@nuevo"
    assert again.name == "Nombre nuevo"
    # label=None en el segundo alta no debe pisar el label existente.
    assert again.label == "Original"

    all_tracked = await list_tracked(session, active_only=False)
    assert len(all_tracked) == 1


@pytest.mark.asyncio
async def test_find_by_platform_native_id_not_found_returns_none(session):
    result = await find_by_platform_native_id(session, Platform.YOUTUBE, "UC_no_existe")
    assert result is None


@pytest.mark.asyncio
async def test_deactivate_tracked_unknown_id_returns_false(session):
    ok = await deactivate_tracked(session, 999)
    assert ok is False


@pytest.mark.asyncio
async def test_list_tracked_active_only_excludes_deactivated(session):
    a = await create_tracked(session, Platform.YOUTUBE, "UC1", "@a", None, "A", None)
    b = await create_tracked(session, Platform.YOUTUBE, "UC2", "@b", None, "B", None)
    await deactivate_tracked(session, b.id)

    active = await list_tracked(session, active_only=True)
    everyone = await list_tracked(session, active_only=False)

    assert [tc.id for tc in active] == [a.id]
    assert len(everyone) == 2


@pytest.mark.asyncio
async def test_get_tracked_returns_none_for_missing(session):
    assert await get_tracked(session, 42) is None


@pytest.mark.asyncio
async def test_upsert_snapshot_creates_then_updates_same_day(session):
    tracked = await create_tracked(session, Platform.YOUTUBE, "UC123", "@prueba", None, "Canal", None)

    snap1, created1 = await upsert_snapshot_from_channel(session, tracked.id, _channel(followers=1000))
    assert created1 is True
    assert snap1.followers == 1000

    # Correr el mismo día de nuevo (p. ej. dos disparos manuales del job)
    # no debe duplicar la fila, sino actualizarla in place.
    snap2, created2 = await upsert_snapshot_from_channel(session, tracked.id, _channel(followers=1500))
    assert created2 is False
    assert snap2.id == snap1.id
    assert snap2.followers == 1500

    latest = await latest_snapshot(session, tracked.id)
    assert latest.followers == 1500

    history = await snapshot_history(session, tracked.id, days=30)
    assert len(history) == 1  # sigue habiendo una sola fila para ese día


@pytest.mark.asyncio
async def test_upsert_snapshot_different_days_creates_two_rows(session):
    tracked = await create_tracked(session, Platform.YOUTUBE, "UC123", "@prueba", None, "Canal", None)

    yesterday = date.today() - timedelta(days=1)
    await upsert_snapshot_from_channel(session, tracked.id, _channel(followers=900), snapshot_date=yesterday)
    await upsert_snapshot_from_channel(session, tracked.id, _channel(followers=1000))

    history = await snapshot_history(session, tracked.id, days=30)
    assert len(history) == 2
    assert history[0].followers == 900  # ordenado por fecha ascendente
    assert history[1].followers == 1000


@pytest.mark.asyncio
async def test_snapshot_history_respects_days_window(session):
    tracked = await create_tracked(session, Platform.YOUTUBE, "UC123", "@prueba", None, "Canal", None)
    old = date.today() - timedelta(days=90)
    await upsert_snapshot_from_channel(session, tracked.id, _channel(followers=500), snapshot_date=old)
    await upsert_snapshot_from_channel(session, tracked.id, _channel(followers=1000))

    recent = await snapshot_history(session, tracked.id, days=30)
    assert len(recent) == 1
    assert recent[0].followers == 1000


@pytest.mark.asyncio
async def test_latest_snapshot_none_when_no_snapshots_yet(session):
    tracked = await create_tracked(session, Platform.YOUTUBE, "UC123", "@prueba", None, "Canal", None)
    assert await latest_snapshot(session, tracked.id) is None
