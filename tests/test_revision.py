"""Revisión manual desde el taller: listar con filtros, editar una línea, marcar para retraducir; rutas y modo sin QA."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "tl"))

import revision  # noqa: E402

SCRIPT = '''# game/x.rpy:5
translate spanish start_1:

    # ve neu "Hello there, [mc]!"
    ve neu "Hello there, [mc]!"

# game/x.rpy:7
translate spanish start_2:

    # mc "I am fine, thanks."
    mc "Estoy bien, gracias."

# game/x.rpy:9
translate spanish start_3:

    # "The tavern is quiet tonight." with vpunch
    "The tavern is quiet tonight." with vpunch

translate spanish strings:

    # game/x.rpy:2
    old "Start game"
    new "Empezar partida"

    # game/x.rpy:3
    old "Quit to menu"
    new "Quit to menu"
'''


def _juego(tmp_path):
    g = tmp_path / "Juego"
    (g / "game" / "tl" / "spanish" / "sub").mkdir(parents=True)
    (g / "game" / "tl" / "spanish" / "x.rpy").write_text(SCRIPT, encoding="utf-8")
    (g / "game" / "tl" / "spanish" / "sub" / "y.rpy").write_text('# game/y.rpy:1\ntranslate spanish y_1:\n\n    # ve "Bye."\n    ve "Adiós."\n', encoding="utf-8")
    return g


def test_listar_resumen_filtros_y_paginacion(tmp_path):
    g = _juego(tmp_path)
    d = revision.listar(g)
    assert d["total"] == 6 and (d["resumen"]["total"], d["resumen"]["sin_traducir"]) == (6, 3)
    hab = d["resumen"]["hablantes"]
    assert hab[0] == {"hablante": "(interfaz)", "total": 2, "sin_traducir": 1} and {h["hablante"] for h in hab[1:3]} == {"ve neu", "(narrador)"}
    assert {h["hablante"] for h in hab[3:]} == {"mc", "ve"} and all(h["sin_traducir"] == 0 for h in hab[3:])
    assert [l["source"] for l in revision.listar(g, filtro="sin_traducir")["lineas"]] == ["Hello there, [mc]!", "The tavern is quiet tonight.", "Quit to menu"]
    assert [l["archivo"] for l in revision.listar(g, hablante="ve")["lineas"]] == ["sub/y.rpy"]
    assert [l["target"] for l in revision.listar(g, q="gracias")["lineas"]] == ["Estoy bien, gracias."]
    p = revision.listar(g, por_pagina=4, pagina=2)
    assert (p["total"], p["paginas"], p["pagina"], len(p["lineas"])) == (6, 2, 2, 2)
    assert revision.listar(tmp_path / "nada")["total"] == 0


def test_editar_y_vaciar(tmp_path):
    g = _juego(tmp_path)
    r = revision.editar(g, "x.rpy", 5, "¡Hola, [mc]!")
    assert r["despues"] == 've neu "¡Hola, [mc]!"'
    r = revision.editar(g, "x.rpy", 27, "Salir al menú")
    assert r["despues"] == 'new "Salir al menú"'
    r = revision.editar(g, "x.rpy", 17, 'Hoy la taberna "duerme".')
    assert r["despues"] == '"Hoy la taberna \\"duerme\\"." with vpunch'
    assert revision.listar(g)["resumen"]["sin_traducir"] == 0
    for archivo, linea, texto in (("x.rpy", 4, "x"), ("x.rpy", 26, "x"), ("x.rpy", 999, "x"), ("../x.rpy", 5, "x"), ("x.rpy", 5, "a\nb")):
        with pytest.raises(ValueError):
            revision.editar(g, archivo, linea, texto)
    assert revision.vaciar(g, [{"archivo": "x.rpy", "linea": 11}, {"archivo": "x.rpy", "linea": 4}, {"archivo": "sub/y.rpy", "linea": 5}]) == 2
    texto = (g / "game" / "tl" / "spanish" / "x.rpy").read_text(encoding="utf-8")
    assert '    mc ""\n' in texto and (g / "game" / "tl" / "spanish" / "sub" / "y.rpy").read_text(encoding="utf-8").endswith('    ve ""\n')
    assert revision.listar(g, filtro="sin_traducir")["total"] == 2


def test_rutas_de_revision_y_reempaquetar_sin_qa(server):
    g = _juego(server.entrada)
    d = server.call("GET", "/revision?juego=Juego&filtro=sin_traducir").json()
    assert d["juego"] == "Juego" and d["total"] == 3 and d["resumen"]["sin_traducir"] == 3
    assert server.call("GET", "/revision?juego=NoExiste").status == 404
    r = server.call("POST", "/revision/editar", {"juego": "Juego", "archivo": "x.rpy", "linea": 5, "texto": "¡Hola!"})
    assert r.status == 200 and r.json()["despues"] == 've neu "¡Hola!"'
    assert server.call("POST", "/revision/editar", {"juego": "Juego", "archivo": "x.rpy", "linea": 4, "texto": "x"}).status == 400
    r = server.call("POST", "/revision/vaciar", {"juego": "Juego", "lineas": [{"archivo": "x.rpy", "linea": 11}]})
    assert r.status == 200 and r.json()["vaciadas"] == 1
    assert server.call("GET", "/revision?juego=Juego&filtro=sin_traducir").json()["total"] == 3
    html = server.call("GET", "/dashboard").body.decode()
    assert 'id="revision"' in html and "/revision/editar" in html and "sin_qa" in html
