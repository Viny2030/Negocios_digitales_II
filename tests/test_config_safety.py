"""
Tests de las dos mejoras de "higiene de configuración" agregadas a
`app/core/config.py` / `app/main.py`:

  1. `production_safety_warnings()`: avisa (sin bloquear el arranque) si
     quedó el `JWT_SECRET_KEY` default o `ADMIN_TOKEN` vacío — los dos
     ítems que el README pide resolver antes de un deploy público.
  2. CORS: `allow_origins=["*"]` + `allow_credentials=True` es una
     combinación que los navegadores ignoran (spec de CORS) — con la
     lista default (`["*"]`) la app ahora manda `allow_credentials=False`
     en vez de las dos cabeceras contradictorias a la vez.
"""
from fastapi.testclient import TestClient

from app.core.config import Settings, production_safety_warnings
from app.main import app

# Sin `with`, TestClient no dispara el `lifespan` real (ver test_statistics_api.py).
client = TestClient(app)


def test_default_settings_warn_about_dev_jwt_secret_and_missing_admin_token():
    warnings = production_safety_warnings(Settings())
    assert len(warnings) == 2
    joined = " ".join(warnings)
    assert "JWT_SECRET_KEY" in joined
    assert "ADMIN_TOKEN" in joined


def test_overriding_both_clears_the_warnings():
    settings = Settings(JWT_SECRET_KEY="un-secreto-propio-bien-largo", ADMIN_TOKEN="un-token-propio")
    assert production_safety_warnings(settings) == []


def test_cors_allowed_origins_accepts_comma_separated_string():
    settings = Settings(CORS_ALLOWED_ORIGINS="https://a.com, https://b.com")
    assert settings.CORS_ALLOWED_ORIGINS == ["https://a.com", "https://b.com"]


def test_cors_default_wildcard_does_not_also_send_allow_credentials():
    """
    Con la config default (`CORS_ALLOWED_ORIGINS=["*"]`) el middleware NO
    debe mandar `Access-Control-Allow-Credentials: true` junto al origen
    comodín — esa combinación es la que los navegadores descartan.
    """
    r = client.get("/", headers={"Origin": "https://cualquier-sitio-externo.com"})
    assert r.headers.get("access-control-allow-origin") == "*"
    assert r.headers.get("access-control-allow-credentials") is None
