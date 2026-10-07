"""
Tests HTTP end-to-end (FastAPI TestClient) del flujo de autenticación y
del gating por plan de suscripción sobre los endpoints de estadística.

`settings.REQUIRE_SUBSCRIPTION` es `False` por default (ver
`app/core/config.py`): con el gating desactivado, `/channels/*` y
`/analytics/*` (salvo benchmarks) funcionan SIN login, para no romper el
uso normal del dashboard. Los tests de gating de este archivo activan el
interruptor a mano vía el fixture `require_subscription` (monkeypatch
sobre `app.api.deps.settings`) — así se prueban ambos modos.

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

import app.api.deps as deps
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


@pytest.fixture
def require_subscription(monkeypatch):
    """Activa `REQUIRE_SUBSCRIPTION` solo para el test que lo pida."""
    monkeypatch.setattr(deps.settings, "REQUIRE_SUBSCRIPTION", True)


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


def test_discover_open_by_default_without_login(client):
    """REQUIRE_SUBSCRIPTION=False (default): no hace falta login ni plan."""
    assert client.get("/api/v1/channels/discover?limit=10").status_code == 200


def test_premium_open_by_default_without_login(client):
    r = client.get("/api/v1/premium/channels/999/projections")
    # Pasa el gate de plan (no 401/402 porque el gating está apagado); el
    # canal no existe -> 404.
    assert r.status_code == 404


def test_discover_requires_login_when_subscription_required(client, require_subscription):
    assert client.get("/api/v1/channels/discover?limit=10").status_code == 401


def test_discover_blocked_for_free_plan_with_402_when_subscription_required(client, require_subscription):
    token = _register(client, "free@example.com")["access_token"]
    r = client.get("/api/v1/channels/discover?limit=10", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 402


def test_discover_allowed_after_admin_sets_mensual_plan(client, require_subscription):
    token = _register(client, "mensual@example.com")["access_token"]

    admin = client.post("/api/v1/auth/admin/set-plan", json={"email": "mensual@example.com", "plan": "mensual"})
    assert admin.status_code == 200
    assert admin.json()["has_full_stats_access"] is True

    r = client.get("/api/v1/channels/discover?limit=10", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_admin_set_plan_unknown_email_returns_404(client):
    r = client.post("/api/v1/auth/admin/set-plan", json={"email": "no-existe@example.com", "plan": "mensual"})
    assert r.status_code == 404


def test_unica_plan_un_credito_abre_una_ventana_de_reporte(client, require_subscription):
    """Un crédito 'única' = un reporte: abre una ventana de consultas libres
    (el dashboard hace varias llamadas por pantalla), no una sola llamada."""
    token = _register(client, "unica@example.com")["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    client.post(
        "/api/v1/auth/admin/set-plan",
        json={"email": "unica@example.com", "plan": "unica", "add_report_credits": 1},
    )

    first = client.get("/api/v1/channels/discover?limit=10", headers=headers)
    assert first.status_code == 200
    second = client.get("/api/v1/channels/discover?limit=5", headers=headers)
    assert second.status_code == 200  # misma ventana: no gasta otro crédito

    me = client.get("/api/v1/auth/me", headers=headers).json()
    assert me["report_credits"] == 0
    assert me["unica_access_until"] is not None


def test_unica_request_fallida_no_gasta_credito(client, require_subscription):
    token = _register(client, "fallida@example.com")["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    client.post(
        "/api/v1/auth/admin/set-plan",
        json={"email": "fallida@example.com", "plan": "unica", "add_report_credits": 1},
    )

    # 422 (parámetro inválido) y 400 (platform=all donde no se admite): ninguna gasta el crédito.
    assert client.get("/api/v1/analytics/distribution?platform=youtube", headers=headers).status_code == 422
    assert client.get("/api/v1/analytics/distribution?query=x&platform=all", headers=headers).status_code == 400
    assert client.get("/api/v1/auth/me", headers=headers).json()["report_credits"] == 1

    assert client.get("/api/v1/channels/discover?limit=10", headers=headers).status_code == 200
    assert client.get("/api/v1/auth/me", headers=headers).json()["report_credits"] == 0


def test_tracking_lectura_exige_plan_con_gating_activo(client, require_subscription):
    """El listado y el historial de canales trackeados son justamente lo que se
    cobra: con REQUIRE_SUBSCRIPTION=true no pueden quedar abiertos."""
    assert client.get("/api/v1/tracking/channels").status_code == 401
    assert client.get("/api/v1/tracking/channels/1/history").status_code == 401

    token = _register(client, "lector@example.com")["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/tracking/channels", headers=headers).status_code == 402

    client.post("/api/v1/auth/admin/set-plan", json={"email": "lector@example.com", "plan": "mensual"})
    assert client.get("/api/v1/tracking/channels", headers=headers).status_code == 200


def test_tracking_lectura_abierta_sin_gating(client):
    assert client.get("/api/v1/tracking/channels").status_code == 200


def test_benchmarks_endpoint_stays_public_without_login(client, require_subscription):
    assert client.get("/api/v1/analytics/benchmarks").status_code == 200


def test_premium_endpoints_require_premium_not_just_mensual(client, require_subscription):
    token = _register(client, "solomensual@example.com")["access_token"]
    client.post("/api/v1/auth/admin/set-plan", json={"email": "solomensual@example.com", "plan": "mensual"})

    r = client.get("/api/v1/premium/channels/1/projections", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 402


def test_premium_endpoints_allowed_for_premium_plan_but_404_for_unknown_channel(client, require_subscription):
    token = _register(client, "premiumuser@example.com")["access_token"]
    client.post("/api/v1/auth/admin/set-plan", json={"email": "premiumuser@example.com", "plan": "premium"})

    r = client.get("/api/v1/premium/channels/999/projections", headers={"Authorization": f"Bearer {token}"})
    # Pasa el gate de plan (402 no debería aparecer); el canal no existe -> 404.
    assert r.status_code == 404


def test_login_tiene_limite_de_intentos_por_minuto(client, monkeypatch):
    import app.core.rate_limit as rl

    monkeypatch.setattr(rl.settings, "AUTH_RATE_LIMIT_PER_MINUTE", 3)
    body = {"email": "nadie@example.com", "password": "incorrecta"}
    codes = [client.post("/api/v1/auth/login", json=body).status_code for _ in range(4)]
    assert codes == [401, 401, 401, 429]
