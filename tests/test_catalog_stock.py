"""
Stock de canales por tipo y actualización diaria (`catalog_stock` y GET /api/v1/catalog/stock).

La lógica se prueba contra una base SQLite en memoria con fotos fechadas a mano (y un `today`
fijo), así los días con y sin corrida del job quedan bajo control; el endpoint se prueba aparte
con el mismo patrón de fixture que `test_catalog.py`.
"""
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.models import Base, ChannelMetricSnapshot, ChannelType, TrackedChannel
from app.db.session import get_session
from app.main import app
from app.services.tracked_channels import catalog_stock

TODAY = date(2026, 11, 27)


def _engine():
    return create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )


async def _seed(session):
    gaming = ChannelType(name="Gaming", slug="gaming", is_custom=False)
    music = ChannelType(name="Música", slug="musica", is_custom=False)
    empty = ChannelType(name="Vacía", slug="vacia", is_custom=True)
    session.add_all([gaming, music, empty])
    await session.flush()

    channels = [
        TrackedChannel(platform="youtube", native_id="UC_g1", channel_type_id=gaming.id, country="AR"),
        TrackedChannel(platform="youtube", native_id="UC_g2", channel_type_id=gaming.id, country="AR"),
        TrackedChannel(platform="youtube", native_id="UC_m1", channel_type_id=music.id, country="MX"),
        TrackedChannel(platform="youtube", native_id="UC_none"),
        TrackedChannel(platform="youtube", native_id="UC_baja", channel_type_id=gaming.id, active=False, country="AR"),
    ]
    session.add_all(channels)
    await session.flush()
    g1, g2, m1, none, baja = channels

    def snap(channel, day):
        return ChannelMetricSnapshot(
            tracked_channel_id=channel.id, snapshot_date=day, followers=10, fetched_at=datetime(2026, 11, day.day, 15),
        )

    session.add_all([
        snap(g1, date(2026, 11, 27)), snap(g2, date(2026, 11, 27)), snap(m1, date(2026, 11, 27)),
        snap(g1, date(2026, 11, 26)), snap(m1, date(2026, 11, 26)),
        # 25/11 sin corrida del job
        snap(g1, date(2026, 11, 24)), snap(none, date(2026, 11, 24)),
        snap(g1, date(2026, 11, 1)),  # fuera de la ventana de 4 días
        snap(baja, date(2026, 11, 27)),  # dado de baja: no cuenta
    ])
    await session.commit()


@pytest.fixture
async def session():
    engine = _engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        await _seed(s)
        yield s
    await engine.dispose()


async def test_stock_por_tipo_y_dia(session):
    stock = await catalog_stock(session, days=4, today=TODAY)

    assert stock["total"] == 4  # el dado de baja no entra en el stock
    assert stock["dates"] == [date(2026, 11, 27), date(2026, 11, 26), date(2026, 11, 25), date(2026, 11, 24)]

    rows = {(r["channel_type"].name if r["channel_type"] else None): r for r in stock["rows"]}
    assert set(rows) == {"Gaming", "Música", None}  # el tipo sin canales no aparece
    assert rows["Gaming"]["channel_count"] == 2
    assert rows["Gaming"]["snapshots_by_date"] == [2, 1, 0, 1]
    assert rows["Música"]["snapshots_by_date"] == [1, 1, 0, 0]
    assert rows[None]["snapshots_by_date"] == [0, 0, 0, 1]
    assert rows[None]["last_snapshot_date"] == date(2026, 11, 24)

    assert stock["totals_by_date"] == [3, 2, 0, 2]
    assert stock["latest_snapshot_date"] == TODAY
    assert stock["days_since_last_snapshot"] == 0
    assert stock["last_fetched_at"] == datetime(2026, 11, 27, 15)


async def test_dias_sin_actualizar(session):
    stock = await catalog_stock(session, days=3, today=date(2026, 12, 7))
    assert stock["days_since_last_snapshot"] == 10
    assert stock["totals_by_date"] == [0, 0, 0]
    # La última foto quedó fuera de la ventana, pero su cobertura se informa igual.
    assert stock["latest_snapshot_count"] == 3


async def test_base_vacia():
    engine = _engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine)() as s:
        stock = await catalog_stock(s, days=2, today=TODAY)
    await engine.dispose()
    assert stock["total"] == 0
    assert stock["rows"] == []
    assert stock["latest_snapshot_date"] is None
    assert stock["latest_snapshot_count"] == 0
    assert stock["days_since_last_snapshot"] is None
    assert stock["last_fetched_at"] is None


@pytest.fixture
def client():
    engine = _engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    state = {"initialized": False}

    async def override_get_session():
        if not state["initialized"]:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with factory() as s:
                await _seed(s)
            state["initialized"] = True
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = override_get_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_endpoint_stock(client):
    r = client.get("/api/v1/catalog/stock", params={"days": 7})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total_channels"] == 4
    assert len(data["dates"]) == 7
    assert all(len(row["snapshots_by_date"]) == 7 for row in data["rows"])
    assert len(data["totals_by_date"]) == 7
    assert data["dates"] == sorted(data["dates"], reverse=True)


@pytest.mark.parametrize("days", [0, 91])
def test_endpoint_valida_la_ventana(client, days):
    assert client.get("/api/v1/catalog/stock", params={"days": days}).status_code == 422


async def test_stock_por_pais_siempre_sobre_todos(session):
    stock = await catalog_stock(session, days=4, today=TODAY, country="ar")
    assert stock["country_filter"] == "AR"
    # El dado de baja no cuenta; los sin país van al final.
    assert stock["by_country"] == [
        {"country": "AR", "channel_count": 2},
        {"country": "MX", "channel_count": 1},
        {"country": None, "channel_count": 1},
    ]


async def test_filtro_por_pais(session):
    stock = await catalog_stock(session, days=4, today=TODAY, country="AR")
    assert stock["total"] == 2
    assert [r["channel_type"].name for r in stock["rows"]] == ["Gaming"]
    assert stock["totals_by_date"] == [2, 1, 0, 1]
    assert stock["latest_snapshot_count"] == 2


async def test_filtro_sin_pais(session):
    stock = await catalog_stock(session, days=4, today=TODAY, country="none")
    assert stock["country_filter"] == "none"
    assert stock["total"] == 1
    assert stock["rows"][0]["channel_type"] is None
    assert stock["latest_snapshot_date"] == date(2026, 11, 24)


def test_endpoint_filtra_por_pais(client):
    data = client.get("/api/v1/catalog/stock", params={"days": 4, "country": "MX"}).json()
    assert data["country_filter"] == "MX"
    assert data["total_channels"] == 1
    assert len(data["by_country"]) == 3


@pytest.mark.parametrize("country", ["ARG", "1A", "todos"])
def test_endpoint_valida_el_pais(client, country):
    assert client.get("/api/v1/catalog/stock", params={"country": country}).status_code == 422
