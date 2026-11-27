"""
Levantamiento diario desde GitHub Actions: las salvaguardas de `scripts/levantar_canales.py`,
el armado del mail de `scripts/notificar_mail.py` y las reglas de los dos workflows.
"""
from datetime import date
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.worker import DailyJobResult
from scripts import levantar_canales as lc
from scripts import notificar_mail as nm

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def _settings(**overrides) -> Settings:
    base = {"YOUTUBE_API_KEY": "clave", "USE_MOCK_DATA_IF_NO_CREDENTIALS": False}
    return Settings(_env_file=None, **{**base, **overrides})


def test_configuracion_real_no_tiene_problemas():
    assert lc.config_problems(_settings()) == []


def test_sin_clave_o_con_mock_no_corre():
    assert lc.config_problems(_settings(YOUTUBE_API_KEY=None))
    assert lc.config_problems(_settings(USE_MOCK_DATA_IF_NO_CREDENTIALS=True))


async def test_run_se_niega_sin_configuracion_real(monkeypatch):
    monkeypatch.setattr(lc, "get_settings", lambda: _settings(YOUTUBE_API_KEY=None))
    assert await lc.run() == lc.EXIT_UNSAFE_CONFIG


@pytest.mark.parametrize(
    ("hoy", "activos", "esperado"),
    [(802, 802, True), (787, 802, True), (700, 802, False), (0, 802, False), (0, 0, False)],
)
def test_ya_estaba_tomada(hoy, activos, esperado):
    assert lc.already_done(hoy, activos) is esperado


def test_resumen_incluye_conteos_y_recorta_errores():
    result = DailyJobResult(channels_evaluated=3, snapshots_created=2, errors=[f"e{i}" for i in range(60)])
    md = lc.summary_markdown(result, active_channels=3)
    assert "| 3 | 2 | 0 | 60 |" in md
    assert "- e49" in md and "- e50" not in md
    assert "10 más" in md


def test_resumen_ya_estaba():
    md = lc.already_done_markdown(802, 802, date(2026, 11, 28))
    assert "28/11/2026" in md and "802 de 802" in md


@pytest.mark.parametrize(
    ("estado", "modo", "foto", "texto"),
    [
        ("success", "principal", "tomada", "Levantamiento diario: OK"),
        ("success", "respaldo", "tomada", "Levantamiento de respaldo: OK"),
        ("success", "respaldo", "ya_estaba", "ya estaba tomada"),
        ("failure", "principal", "", "FALLÓ"),
        ("cancelled", "principal", "", "CANCELADO"),
    ],
)
def test_asunto_del_mail(estado, modo, foto, texto):
    subject = nm.build_subject(estado, modo, foto)
    assert subject.startswith(nm.PREFIX)
    assert texto in subject


def test_cuerpo_del_mail_con_falla_explica_que_sigue():
    body = nm.build_body("failure", "https://github.com/x/y/actions/runs/1", "")
    assert "respaldo" in body
    assert "falló antes de tomar la foto" in body
    assert "actions/runs/1" in body


def test_mail_sin_configurar_no_falla(monkeypatch):
    for name in ("SMTP_USERNAME", "SMTP_PASSWORD", "MAIL_TO"):
        monkeypatch.delenv(name, raising=False)
    assert nm.main() == 0


def test_los_dos_workflows_existen_y_comparten_la_logica():
    principal = (WORKFLOWS / "levantamiento-canales.yml").read_text(encoding="utf-8")
    respaldo = (WORKFLOWS / "levantamiento-canales-respaldo.yml").read_text(encoding="utf-8")
    assert "workflow_call:" in principal
    assert "uses: ./.github/workflows/levantamiento-canales.yml" in respaldo
    assert "modo: respaldo" in respaldo
    assert 'cron: "0 15 * * *"' in principal and 'cron: "0 21 * * *"' in respaldo
    # Nunca dos corridas a la vez sobre la misma base.
    assert "group: levantamiento-canales" in principal


def test_el_workflow_no_usa_mock_ni_sube_la_base_sin_cifrar():
    principal = (WORKFLOWS / "levantamiento-canales.yml").read_text(encoding="utf-8")
    assert 'USE_MOCK_DATA_IF_NO_CREDENTIALS: "false"' in principal
    assert "--symmetric --cipher-algo AES256" in principal
    assert "path: channel_analytics.db.gpg" in principal
    assert "path: channel_analytics.db\n" not in principal
    # La base solo se reemplaza si la foto se tomó de verdad.
    assert principal.count("steps.foto.outputs.resultado == 'tomada'") >= 2
