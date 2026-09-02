"""
Tests HTTP end-to-end (FastAPI TestClient) de
`POST /api/v1/tracking/discover-and-track` -- la solución a "tengo pocos
canales trackeados": descubre canales reales de todos los temas y los
trackea de una sola vez, en vez de agregarlos uno por uno.

Mismo patrón de fixture que `test_catalog.py`: engine SQLite en memoria
que sobreescribe `get_session`, sin correr el `lifespan` real (el seed
automático de tipos nativos de YouTube no aplica acá). El modo mock queda
forzado por el fixture autouse `force_mock_mode` de `conftest.py`, así que
estos tests no pegan a la API real ni dependen de si hay `YOUTUBE_API_KEY`
cargada.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.db.session import get_session
from app.main import app


@pytest.fixture
def client():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    state = {"initialized": False}

    async def override_get_session():
        if not state["initialized"]:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            state["initialized"] = True
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _discover_and_track(client, total_limit=12, platform="youtube", sort_by="followers"):
    r = client.post(
        "/api/v1/tracking/discover-and-track",
        params={"platform": platform, "total_limit": total_limit, "sort_by": sort_by},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_discover_and_track_respects_total_limit(client):
    data = _discover_and_track(client, total_limit=12)
    assert 0 < data["total_tracked"] <= 12
    assert data["total_limit"] == 12
    assert data["errors"] == []

    tracked = client.get("/api/v1/tracking/channels").json()["channels"]
    assert len(tracked) == data["total_tracked"]


def test_discover_and_track_by_category_breakdown_sums_to_total(client):
    data = _discover_and_track(client, total_limit=15)
    assert sum(row["channels_tracked"] for row in data["by_category"]) == data["total_tracked"]
    # Con el fallback mock (sin YOUTUBE_API_KEY en el entorno de test),
    # `discover_by_category` reparte entre varios tópicos semilla -- tiene
    # que haber más de una categoría representada.
    assert len(data["by_category"]) > 1
    for row in data["by_category"]:
        assert row["channels_tracked"] <= row["channels_found"]
        assert row["label"]


def test_discover_and_track_assigns_channel_type_per_category(client):
    _discover_and_track(client, total_limit=10)
    tracked = client.get("/api/v1/tracking/channels").json()["channels"]
    assert all(ch["channel_type"] is not None for ch in tracked)

    # Los tipos creados tienen que coincidir con las etiquetas de categoría
    # devueltas por el propio endpoint (no un valor genérico/hardcodeado).
    types = {t["name"] for t in client.get("/api/v1/catalog/types").json()["types"]}
    assert types
    used_types = {ch["channel_type"]["name"] for ch in tracked}
    assert used_types <= types


def test_discover_and_track_does_not_duplicate_channels_already_tracked(client):
    """Correrlo dos veces con los mismos parámetros no debería duplicar
    canales: el mock es determinístico por tópico, así que la segunda
    corrida vuelve a encontrar los mismos canales y `create_tracked` los
    reactiva/actualiza en vez de crear filas nuevas."""
    _discover_and_track(client, total_limit=10)
    first_count = len(client.get("/api/v1/tracking/channels").json()["channels"])

    _discover_and_track(client, total_limit=10)
    second_count = len(client.get("/api/v1/tracking/channels").json()["channels"])

    assert second_count == first_count


def test_discover_and_track_rejects_invalid_sort_by(client):
    r = client.post(
        "/api/v1/tracking/discover-and-track",
        params={"platform": "youtube", "total_limit": 5, "sort_by": "not_a_real_field"},
    )
    assert r.status_code == 422
