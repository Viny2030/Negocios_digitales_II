"""La guía se sirve, coincide con su generador y sus grafos están completos."""
import re

import pytest
from fastapi.testclient import TestClient

from app.main import app
from scripts import generar_guia as gg

client = TestClient(app)


@pytest.mark.parametrize(("path", "lang"), [("/guia", "es"), ("/guia/en", "en")])
def test_la_guia_se_sirve(path, lang):
    r = client.get(path)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert f'<html lang="{lang}">' in r.text


@pytest.mark.parametrize("lang", ["es", "en"])
def test_el_html_coincide_con_el_generador(lang):
    saved = (gg.STATIC_DIR / gg.PAGES[lang]["file"]).read_text(encoding="utf-8")
    assert saved == gg.render(lang), "Falta correr: python -m scripts.generar_guia"


@pytest.mark.parametrize("lang", ["es", "en"])
@pytest.mark.parametrize(("nodes", "key"), [(gg.FLOW_NODES, "flow"), (gg.INFO_NODES, "info")])
def test_todos_los_nodos_tienen_nombre_en_cada_idioma(lang, nodes, key):
    texts = gg.GRAPH_TEXT[lang][key]
    assert {node[0] for node in nodes} == set(texts)
    assert all(title.strip() for title, _lines in texts.values())


@pytest.mark.parametrize("lang", ["es", "en"])
def test_los_enlaces_internos_llevan_a_una_seccion(lang):
    html = gg.render(lang)
    targets = set(re.findall(r'href="#([\w-]+)"', html))
    assert targets and targets <= set(re.findall(r'id="([\w-]+)"', html))


def test_el_dashboard_integra_la_guia_y_enlaza_a_la_seccion_de_audiencia():
    assert 'id="audiencia"' in gg.render("es")
    dashboard = client.get("/dashboard").text
    assert 'id="guide-frame"' in dashboard
    assert 'data-guide-section="audiencia"' in dashboard


def test_la_guia_acepta_el_tema_que_le_pasa_el_dashboard():
    assert ':root[data-theme="dark"]' in gg.render("es")
    assert "{{DARK}}" not in gg.render("es")


@pytest.mark.parametrize("lang", ["es", "en"])
def test_la_guia_documenta_las_rutas_de_audiencia(lang):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/analytics/audience-integrity" in paths
    assert "/api/v1/tracking/channels/{tracked_id}/audience-integrity" in paths
    assert "/api/v1/analytics/audience-integrity" in gg.render(lang)
