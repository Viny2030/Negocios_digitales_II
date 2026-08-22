"""
Fixtures compartidas por todo el test suite.

Los tests están escritos para correr en modo mock (canales "UC_mock_...",
"tt_mock_...") sin importar si `.env` tiene o no credenciales reales
cargadas (p. ej. para probar el pipeline a mano con `uvicorn` contra la
API real). Sin este fixture, tener una `YOUTUBE_API_KEY`/`TIKTOK_CLIENT_KEY`
real en `.env` hace que `is_configured()` devuelva True y los colectores le
peguen a la API real con identificadores mock inexistentes — lo que rompe
el suite con errores confusos ("no devuelto por la API") en vez de datos
simulados determinísticos.
"""
import pytest

import app.services.collectors.tiktok as tiktok_module
import app.services.collectors.youtube as youtube_module


@pytest.fixture(autouse=True)
def force_mock_mode(monkeypatch):
    """Fuerza modo mock en todos los tests, sin importar el contenido de `.env`."""
    monkeypatch.setattr(youtube_module.settings, "YOUTUBE_API_KEY", None)
    monkeypatch.setattr(tiktok_module.settings, "TIKTOK_CLIENT_KEY", None)
    monkeypatch.setattr(tiktok_module.settings, "TIKTOK_CLIENT_SECRET", None)
