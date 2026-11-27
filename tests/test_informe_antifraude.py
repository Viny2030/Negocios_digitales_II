"""El informe antifraude se sirve, coincide con su generador y los dos idiomas están parejos."""

import re

import pytest
from fastapi.testclient import TestClient

from app.main import app
from scripts import generar_informe_antifraude as gi

client = TestClient(app)


@pytest.mark.parametrize(("path", "lang"), [("/guia/antifraude", "es"), ("/guia/en/antifraude", "en")])
def test_el_informe_se_sirve(path, lang):
    r = client.get(path)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert f'<html lang="{lang}">' in r.text
    assert r.text.count("<section id=") == len(gi.SECTION_KEYS)


@pytest.mark.parametrize("path", list(gi.outputs()))
def test_los_archivos_coinciden_con_el_generador(path):
    assert path.exists(), f"Falta {path.name}: correr `python -m scripts.generar_informe_antifraude`"
    assert path.read_text(encoding="utf-8") == gi.outputs()[path]


@pytest.mark.parametrize("key", gi.SECTION_KEYS)
def test_los_dos_idiomas_tienen_la_misma_forma(key):
    es = gi.PAGES["es"]["sections"][key][1]
    en = gi.PAGES["en"]["sections"][key][1]
    shape = lambda blocks: [(kind, len(c) if isinstance(c, list) else 1) for kind, c in blocks]  # noqa: E731
    assert shape(es) == shape(en)


@pytest.mark.parametrize("key", gi.SECTION_KEYS)
def test_los_dos_idiomas_citan_las_mismas_fuentes(key):
    urls = re.compile(r"\]\((https://[^)\s]+)\)")
    texts = lambda lang: str(gi.PAGES[lang]["sections"][key][1])  # noqa: E731
    assert urls.findall(texts("es")) == urls.findall(texts("en"))


@pytest.mark.parametrize("lang", ["es", "en"])
def test_los_enlaces_internos_llevan_a_una_seccion(lang):
    html = gi.render(lang)
    targets = set(re.findall(r'href="#([\w-]+)"', html))
    ids = set(re.findall(r'id="([\w-]+)"', html))
    assert targets <= ids


@pytest.mark.parametrize("lang", ["es", "en"])
def test_no_queda_marcado_sin_convertir(lang):
    html = gi.render(lang)
    assert "**" not in html
    assert "`" not in html
    assert "](" not in html


def test_los_enlaces_externos_son_https_y_abren_aparte():
    for lang in ("es", "en"):
        html = gi.render(lang)
        external = re.findall(r'<a href="(http[^"]*)"([^>]*)>', html)
        assert external
        for url, attrs in external:
            assert url.startswith("https://")
            assert 'rel="noopener"' in attrs


def test_la_postura_etica_esta_en_ambas_paginas():
    assert "no detecta bots" in gi.render("es")
    assert "does not detect bots" in gi.render("en")
