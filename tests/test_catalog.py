"""
Tests HTTP end-to-end (FastAPI TestClient) del catálogo de canales:
tipos de canal (`/api/v1/catalog/types`), cantidades por tipo
(`/api/v1/catalog/summary`) y asignación de tipo sobre un canal ya
trackeado (`/api/v1/catalog/channels/{id}/type`).

Mismo patrón de fixture que `test_auth_api.py`: un engine SQLite en
memoria con `StaticPool` sobreescribe `get_session`, con las tablas
creadas de forma perezosa en la primera request (no se toca el
`lifespan` real, así que el seed automático de tipos de YouTube de
`db/session.py::_seed_default_channel_types` NO corre acá — cada test
crea explícitamente los tipos que necesita).
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


def _track_channel(client, identifier="UC123", label=None, channel_type_id=None, channel_type_name=None):
    payload = {"platform": "youtube", "identifier": identifier, "label": label}
    if channel_type_id is not None:
        payload["channel_type_id"] = channel_type_id
    if channel_type_name is not None:
        payload["channel_type_name"] = channel_type_name
    r = client.post("/api/v1/tracking/channels", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def test_list_types_empty_by_default(client):
    r = client.get("/api/v1/catalog/types")
    assert r.status_code == 200
    assert r.json()["types"] == []


def test_create_channel_type(client):
    r = client.post("/api/v1/catalog/types", json={"name": "Finanzas personales", "description": "Canales de plata"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["name"] == "Finanzas personales"
    assert data["slug"] == "finanzas-personales"
    assert data["is_custom"] is True

    listing = client.get("/api/v1/catalog/types").json()
    assert len(listing["types"]) == 1


def test_create_duplicate_channel_type_returns_409(client):
    client.post("/api/v1/catalog/types", json={"name": "Gaming"})
    r = client.post("/api/v1/catalog/types", json={"name": "gaming"})  # case-insensitive
    assert r.status_code == 409


def test_delete_channel_type_not_in_use(client):
    created = client.post("/api/v1/catalog/types", json={"name": "Cocina"}).json()
    r = client.delete(f"/api/v1/catalog/types/{created['id']}")
    assert r.status_code == 200
    assert client.get("/api/v1/catalog/types").json()["types"] == []


def test_delete_channel_type_in_use_returns_409(client):
    created = client.post("/api/v1/catalog/types", json={"name": "Música"}).json()
    _track_channel(client, "UC1", channel_type_id=created["id"])

    r = client.delete(f"/api/v1/catalog/types/{created['id']}")
    assert r.status_code == 409


def test_delete_unknown_channel_type_returns_404(client):
    assert client.delete("/api/v1/catalog/types/999").status_code == 404


def test_track_channel_with_channel_type_id(client):
    ctype = client.post("/api/v1/catalog/types", json={"name": "Educación"}).json()
    tracked = _track_channel(client, "UC1", channel_type_id=ctype["id"])
    assert tracked["channel_type"]["name"] == "Educación"


def test_track_channel_with_channel_type_name_creates_type_if_missing(client):
    tracked = _track_channel(client, "UC1", channel_type_name="Noticias y política")
    assert tracked["channel_type"]["name"] == "Noticias y política"
    assert tracked["channel_type"]["is_custom"] is True

    # Un segundo canal con el mismo nombre reusa el tipo, no crea otro.
    tracked2 = _track_channel(client, "UC2", channel_type_name="noticias y política")
    assert tracked2["channel_type"]["id"] == tracked["channel_type"]["id"]
    assert len(client.get("/api/v1/catalog/types").json()["types"]) == 1


def test_track_channel_without_type_leaves_it_unassigned(client):
    tracked = _track_channel(client, "UC1")
    assert tracked["channel_type"] is None


def test_update_channel_type_on_tracked_channel(client):
    ctype_a = client.post("/api/v1/catalog/types", json={"name": "Deportes"}).json()
    ctype_b = client.post("/api/v1/catalog/types", json={"name": "Autos"}).json()
    tracked = _track_channel(client, "UC1", channel_type_id=ctype_a["id"])

    r = client.patch(f"/api/v1/catalog/channels/{tracked['id']}/type", json={"channel_type_id": ctype_b["id"]})
    assert r.status_code == 200
    assert r.json()["channel_type"]["name"] == "Autos"

    # channel_type_id: null quita el tipo asignado.
    cleared = client.patch(f"/api/v1/catalog/channels/{tracked['id']}/type", json={"channel_type_id": None})
    assert cleared.json()["channel_type"] is None


def test_update_channel_type_with_unknown_type_returns_404(client):
    tracked = _track_channel(client, "UC1")
    r = client.patch(f"/api/v1/catalog/channels/{tracked['id']}/type", json={"channel_type_id": 999})
    assert r.status_code == 404


def test_update_channel_type_on_unknown_tracked_channel_returns_404(client):
    r = client.patch("/api/v1/catalog/channels/999/type", json={"channel_type_id": None})
    assert r.status_code == 404


def test_catalog_summary_counts_by_type(client):
    music = client.post("/api/v1/catalog/types", json={"name": "Música"}).json()
    gaming = client.post("/api/v1/catalog/types", json={"name": "Gaming"}).json()
    _track_channel(client, "UC1", channel_type_id=music["id"])
    _track_channel(client, "UC2", channel_type_id=music["id"])
    _track_channel(client, "UC3", channel_type_id=gaming["id"])
    _track_channel(client, "UC4")  # sin tipo

    r = client.get("/api/v1/catalog/summary")
    assert r.status_code == 200
    data = r.json()
    assert data["total_channels"] == 4

    by_name = {(row["channel_type"]["name"] if row["channel_type"] else None): row["channel_count"] for row in data["by_type"]}
    assert by_name["Música"] == 2
    assert by_name["Gaming"] == 1
    assert by_name[None] == 1


def test_catalog_summary_excludes_deactivated_channels(client):
    ctype = client.post("/api/v1/catalog/types", json={"name": "Viajes"}).json()
    tracked = _track_channel(client, "UC1", channel_type_id=ctype["id"])
    client.delete(f"/api/v1/tracking/channels/{tracked['id']}")

    data = client.get("/api/v1/catalog/summary").json()
    assert data["total_channels"] == 0
