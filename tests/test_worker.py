"""
Tests del worker diario (`services/worker.py`) en modo mock (sin
credenciales configuradas, que es el estado por default de los tests).
Redirige la persistencia a un engine SQLite en memoria propio de cada test
vía monkeypatch de `app.db.session.async_session_factory`, para no tocar
el `channel_analytics.db` real del proyecto.
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.session as db_session
from app.db.models import Base
from app.models.domain import Platform
from app.services.tracked_channels import (
    create_tracked,
    deactivate_tracked,
    latest_snapshot,
    list_tracked,
    snapshot_history,
)
from app.services.worker import run_daily_snapshot


@pytest_asyncio.fixture
async def isolated_db(monkeypatch):
    """Apunta get_session_ctx() (usado por el worker) a un engine descartable."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "async_session_factory", factory)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_run_daily_snapshot_no_tracked_channels_is_noop(isolated_db):
    result = await run_daily_snapshot()
    assert result.channels_evaluated == 0
    assert result.snapshots_created == 0
    assert result.errors == []


@pytest.mark.asyncio
async def test_run_daily_snapshot_creates_first_snapshot_for_youtube_and_tiktok(isolated_db):
    factory = isolated_db
    async with factory() as session:
        await create_tracked(session, Platform.YOUTUBE, "UC_mock_testchan", "@testchan", None, None, None)
        await create_tracked(session, Platform.TIKTOK, "tt_mock_testuser", "@testuser", None, None, None)

    result = await run_daily_snapshot()

    assert result.channels_evaluated == 2
    assert result.snapshots_created == 2
    assert result.snapshots_updated == 0
    assert result.errors == []

    async with factory() as session:
        tracked_list = await list_tracked(session)
        for tc in tracked_list:
            snap = await latest_snapshot(session, tc.id)
            assert snap is not None
            assert snap.followers > 0


@pytest.mark.asyncio
async def test_run_daily_snapshot_is_idempotent_same_day(isolated_db):
    factory = isolated_db
    async with factory() as session:
        tracked = await create_tracked(session, Platform.YOUTUBE, "UC_mock_testchan", "@testchan", None, None, None)
        tracked_id = tracked.id

    first = await run_daily_snapshot()
    second = await run_daily_snapshot()

    assert first.snapshots_created == 1
    assert second.snapshots_created == 0
    assert second.snapshots_updated == 1

    async with factory() as session:
        history = await snapshot_history(session, tracked_id, days=30)
        assert len(history) == 1  # no se duplicó la fila del día


@pytest.mark.asyncio
async def test_run_daily_snapshot_mock_data_is_deterministic_across_runs(isolated_db):
    """
    Regresión del bug encontrado en QA manual: el mock debe dar los mismos
    seguidores tanto en el primer snapshot (alta manual por @handle) como
    en los snapshots que toma el worker (que siempre re-consulta por
    native_id) — de lo contrario el historial mostraría saltos irreales.
    """
    factory = isolated_db
    async with factory() as session:
        tracked = await create_tracked(session, Platform.YOUTUBE, "UC_mock_testchan", "@testchan", None, None, None)
        tracked_id = tracked.id

    await run_daily_snapshot()
    async with factory() as session:
        first_snap = await latest_snapshot(session, tracked_id)
        first_followers = first_snap.followers

    await run_daily_snapshot()
    async with factory() as session:
        second_snap = await latest_snapshot(session, tracked_id)
        assert second_snap.followers == first_followers


@pytest.mark.asyncio
async def test_run_daily_snapshot_excludes_deactivated_channels(isolated_db):
    factory = isolated_db
    async with factory() as session:
        tracked = await create_tracked(session, Platform.YOUTUBE, "UC_mock_testchan", "@testchan", None, None, None)
        await deactivate_tracked(session, tracked.id)

    result = await run_daily_snapshot()
    assert result.channels_evaluated == 0
    assert result.snapshots_created == 0
