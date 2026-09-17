"""
Tests HTTP end-to-end (FastAPI TestClient) de `/api/v1/analytics/*`.

Regresión del bug de `platform=all`: `/distribution`, `/correlation` y
`/anomalies` devuelven estadísticas de UNA sola plataforma (el campo
`platform` de la respuesta es singular) — antes aceptaban `platform=all`
sin validar, consultaban YouTube y TikTok igual (gastando cuota de las dos
APIs para nada) y terminaban haciendo `channels_by_platform.get(platform,
[])` con la clave `Platform.ALL`, que nunca está en ese diccionario —
siempre daba lista vacía y respondían 422 "no hay canales suficientes"
aunque sí había datos reales. Ver `app/api/v1/endpoints/statistics.py::
_require_single_platform`.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app

# Sin `with`, TestClient NO dispara el `lifespan` real de la app (no toca
# `init_db()` ni arranca el scheduler) — mismo truco que `test_auth_api.py`
# / `test_catalog.py`. Estos endpoints no necesitan sesión de base de datos
# real: `require_full_access` la resuelve pero no la consulta mientras
# `REQUIRE_SUBSCRIPTION` esté en `False` (default).
client = TestClient(app)

ANALYTICS_ENDPOINTS_REQUIRING_SINGLE_PLATFORM = [
    "/api/v1/analytics/distribution",
    "/api/v1/analytics/correlation",
    "/api/v1/analytics/anomalies",
]


@pytest.mark.parametrize("endpoint", ANALYTICS_ENDPOINTS_REQUIRING_SINGLE_PLATFORM)
def test_platform_all_is_rejected_with_a_clear_400(endpoint):
    r = client.get(endpoint, params={"query": "musica", "platform": "all", "limit": 10})
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["error"] == "SinglePlatformRequiredError"
    assert "platform='all'" in body["message"]
    assert "/analytics/overview" in body["message"]


@pytest.mark.parametrize("endpoint", ANALYTICS_ENDPOINTS_REQUIRING_SINGLE_PLATFORM)
def test_platform_youtube_or_tiktok_still_works(endpoint):
    r = client.get(endpoint, params={"query": "musica", "platform": "youtube", "limit": 10})
    assert r.status_code == 200, r.text


def test_benchmarks_endpoint_still_accepts_platform_all():
    """`/benchmarks` sí soporta `all` (es referencia estática, no indexa por plataforma) — no debe romperse."""
    r = client.get("/api/v1/analytics/benchmarks", params={"platform": "all"})
    assert r.status_code == 200
    assert len(r.json()["benchmarks"]) == 2
