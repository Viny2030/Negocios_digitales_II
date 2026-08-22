"""
Tests HTTP end-to-end (FastAPI TestClient) del flujo de autenticación y
del gating por plan de suscripción sobre los endpoints de estadística.

El `TestClient` se instancia con `get_session` sobreescrito hacia un
engine SQLite en memoria con `StaticPool` (una sola conexión compartida
por TODAS las requests del test, para que lo que se crea en una llamada
—p. ej. registrar un usuario— sea visible en la siguiente —p. ej. loguearse
o consultar `/me`—), y las tablas se crean de forma perezosa en la
primera request para evitar tocar el `lifespan` real de la app (que usa
el `DATABASE_URL` de `.env` y arranca el scheduler semanal) — mismo
espíritu que las fixtures de `test_tracked_channels.py`/`test_users.py`,
pero probando la capa HTTP completa en vez de las funciones de servicio.
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


def _register(client, email="user@example.com", password="password123"):
    r = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def test_register_then_login_roundtrip(client):
    data = _register(client, "roundtrip@example.com")
    assert data["user"]["plan"] == "free"
    token = data["access_token"]

    login = client.post("/api/v1/auth/login", json={"email": "roundtrip@example.com", "password": "password123"})
    assert login.status_code == 200
    assert login.json()["user"]["email"] == "roundtrip@example.com"

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["plan"] == "free"


def test_register_duplicate_email_returns_409(client):
    _register(client, "dup@example.com")
    r = client.post("/api/v1/auth/register", json={"email": "dup@example.com", "password": "otraClave123"})
    assert r.status_code == 409


def test_login_wrong_password_returns_401(client):
    _register(client, "wrongpass@example.com")
    r = client.post("/api/v1/auth/login", json={"email": "wrongpass@example.com", "password": "incorrecta"})
    assert r.status_code == 401


def test_me_without_token_returns_401(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_discover_requires_login(client):
    assert client.get("/api/v1/channels/discover?limit=10").status_code == 401


def test_discover_blocked_for_free_plan_with_402(client):
    token = _register(client, "free@example.com")["access_token"]
    r = client.get("/api/v1/channels/discover?limit=10", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 402


def test_discover_allowed_after_admin_sets_mensual_plan(client):
    token = _register(client, "mensual@example.com")["access_token"]

    admin = client.post("/api/v1/auth/admin/set-plan", json={"email": "mensual@example.com", "plan": "mensual"})
    assert admin.status_code == 200
    assert admin.json()["has_full_stats_access"] is True

    r = client.get("/api/v1/channels/discover?limit=10", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_admin_set_plan_unknown_email_returns_404(client):
    r = client.post("/api/v1/auth/admin/set-plan", json={"email": "no-existe@example.com", "plan": "mensual"})
    assert r.status_code == 404


def test_unica_plan_consumes_one_report_credit_per_call(client):
    token = _register(client, "unica@example.com")["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    client.post(
        "/api/v1/auth/admin/set-plan",
        json={"email": "unica@example.com", "plan": "unica", "add_report_credits": 1},
    )

    first = client.get("/api/v1/channels/discover?limit=10", headers=headers)
    assert first.status_code == 200

    # El crédito ya se consumió en la llamada anterior: la siguiente debe rechazarse.
    second = client.get("/api/v1/channels/discover?limit=10", headers=headers)
    assert second.status_code == 402


def test_benchmarks_endpoint_stays_public_without_login(client):
    assert client.get("/api/v1/analytics/benchmarks").status_code == 200


def test_premium_endpoints_require_premium_not_just_mensual(client):
    token = _register(client, "solomensual@example.com")["access_token"]
    client.post("/api/v1/auth/admin/set-plan", json={"email": "solomensual@example.com", "plan": "mensual"})

    r = client.get("/api/v1/premium/channels/1/projections", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 402


def test_premium_endpoints_allowed_for_premium_plan_but_404_for_unknown_channel(client):
    token = _register(client, "premiumuser@example.com")["access_token"]
    client.post("/api/v1/auth/admin/set-plan", json={"email": "premiumuser@example.com", "plan": "premium"})

    r = client.get("/api/v1/premium/channels/999/projections", headers={"Authorization": f"Bearer {token}"})
    # Pasa el gate de plan (402 no debería aparecer); el canal no existe -> 404.
    assert r.status_code == 404
