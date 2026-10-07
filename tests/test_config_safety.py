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
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings, production_safety_warnings
from app.main import app
from app.models.domain import Platform
from app.services import orchestrator

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


# ─────────────────────────────────────────────────────────────────────────
# Entorno de producción: detección automática, modo mock y arranque seguro
# ─────────────────────────────────────────────────────────────────────────


def test_dentro_de_railway_es_produccion_y_apaga_el_mock(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    settings = Settings(_env_file=None)
    assert settings.APP_ENV == "production"
    assert settings.USE_MOCK_DATA_IF_NO_CREDENTIALS is False


def test_fuera_de_railway_es_desarrollo_con_mock(monkeypatch):
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    settings = Settings(_env_file=None)
    assert settings.APP_ENV == "development"
    assert settings.USE_MOCK_DATA_IF_NO_CREDENTIALS is True


def test_en_produccion_se_puede_forzar_el_mock_a_proposito():
    settings = Settings(_env_file=None, APP_ENV="production", USE_MOCK_DATA_IF_NO_CREDENTIALS=True)
    assert settings.USE_MOCK_DATA_IF_NO_CREDENTIALS is True


def test_platform_all_sin_mock_solo_usa_plataformas_con_credenciales(monkeypatch):
    """Con YouTube configurado y TikTok sin credenciales, `all` NO debe traer
    TikTok simulado mezclado con YouTube real."""
    s = get_settings()
    monkeypatch.setattr(s, "USE_MOCK_DATA_IF_NO_CREDENTIALS", False)
    monkeypatch.setattr(s, "YOUTUBE_API_KEY", "clave-real")
    monkeypatch.setattr(s, "TIKTOK_CLIENT_KEY", None)
    assert orchestrator.resolve_platforms([Platform.ALL]) == [Platform.YOUTUBE]


def test_platform_all_con_mock_usa_todas(monkeypatch):
    monkeypatch.setattr(get_settings(), "USE_MOCK_DATA_IF_NO_CREDENTIALS", True)
    assert orchestrator.resolve_platforms([Platform.ALL]) == [Platform.YOUTUBE, Platform.TIKTOK]


def test_en_produccion_la_app_no_arranca_con_config_insegura(monkeypatch):
    import app.main as main_module

    s = main_module.settings
    monkeypatch.setattr(s, "APP_ENV", "production")
    monkeypatch.setattr(s, "ADMIN_TOKEN", None)
    with pytest.raises(RuntimeError, match="ADMIN_TOKEN"):
        with TestClient(main_module.app):
            pass


def test_admin_token_se_compara_en_tiempo_constante_y_rechaza_ausente(monkeypatch):
    import app.api.deps as deps

    monkeypatch.setattr(deps.settings, "ADMIN_TOKEN", "secreto")
    r = client.post("/api/v1/auth/admin/set-plan", json={"email": "x@y.com", "plan": "free"})
    assert r.status_code == 401
    r = client.post(
        "/api/v1/auth/admin/set-plan", json={"email": "x@y.com", "plan": "free"},
        headers={"X-Admin-Token": "otro"},
    )
    assert r.status_code == 401
