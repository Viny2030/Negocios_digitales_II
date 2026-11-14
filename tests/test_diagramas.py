"""Los grafos técnicos se sirven, coinciden con su generador y los dos idiomas están parejos."""

import re

import pytest
from fastapi.testclient import TestClient

from app.main import app
from scripts import generar_diagramas as gd

client = TestClient(app)


@pytest.mark.parametrize(
    ("path", "lang"), [("/guia/diagramas", "es"), ("/guia/en/diagramas", "en")]
)
def test_los_diagramas_se_sirven(path, lang):
    r = client.get(path)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert f'<html lang="{lang}">' in r.text
    assert r.text.count('<pre class="mermaid">') == len(gd.DIAGRAM_KEYS)


@pytest.mark.parametrize("path", list(gd.outputs()))
def test_los_archivos_coinciden_con_el_generador(path):
    assert path.exists(), (
        f"Falta {path.name}: correr `python -m scripts.generar_diagramas`"
    )
    assert path.read_text(encoding="utf-8") == gd.outputs()[path]


@pytest.mark.parametrize("key", gd.DIAGRAM_KEYS)
def test_los_dos_idiomas_tienen_el_mismo_diagrama(key):
    es = gd.PAGES["es"]["diagrams"][key][2].splitlines()
    en = gd.PAGES["en"]["diagrams"][key][2].splitlines()
    assert len(es) == len(en)
    # misma primera palabra por línea (tipo de diagrama, ids de nodos, flechas, subgraph/end)
    ids = re.compile(r"^\s*([\w-]+)")
    assert [m.group(1) if (m := ids.match(x)) else "" for x in es] == [
        m.group(1) if (m := ids.match(x)) else "" for x in en
    ]


def test_mermaid_se_carga_con_version_fija_y_sri():
    html = gd.render("es")
    assert f"mermaid@{gd.MERMAID_VERSION}/" in html
    assert f'integrity="{gd.MERMAID_SRI}"' in html
    assert 'securityLevel: "strict"' in html


def test_la_postura_etica_esta_en_ambas_paginas():
    assert "no detecta bots" in gd.render("es")
    assert "does not detect bots" in gd.render("en")


@pytest.mark.parametrize("lang", ["es", "en"])
def test_los_enlaces_internos_llevan_a_una_seccion(lang):
    html = gd.render(lang)
    targets = set(re.findall(r'href="#([\w-]+)"', html))
    ids = set(re.findall(r'id="([\w-]+)"', html))
    assert targets <= ids
