"""Autocorrección: puerta renpy lint (revierte líneas rotas), catálogo de fallas con acciones seguras, doctor (Groq) y
el diagnóstico + reintento del pipeline."""
import json
import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "tl"))

import doctor  # noqa: E402
import incidencias  # noqa: E402
import renpy_lint_gate as gate  # noqa: E402

RPY = '''# game/script.rpy:57
translate spanish rightaway_cf214f74:

    # s "Hi there! How was class?"
    s "¡Hola! ¿Qué tal te ha ido la clase?

translate spanish strings:

    # game/script.rpy:2
    old "Sylvie"
    new "rota sin cerrar

    # game/script.rpy:3
    old "Me"
    new "Yo"
'''


def _juego(tmp_path):
    game = tmp_path / "Juego"
    (game / "game" / "tl" / "spanish").mkdir(parents=True)
    (game / "game" / "tl" / "spanish" / "script.rpy").write_text(RPY, encoding="utf-8")
    return game


def _sdk_falso(tmp_path):
    """renpy.sh de mentira: falla mientras el archivo tenga líneas 'rota' o un diálogo sin cerrar, con el formato real de Ren'Py."""
    sdk = tmp_path / "renpy.py"
    sdk.write_text('''import sys, re
game = sys.argv[1]
p = game + "/game/tl/spanish/script.rpy"
errores = []
for i, l in enumerate(open(p, encoding="utf-8").read().splitlines(), 1):
    s = l.strip()
    if (s.startswith("new ") or s.startswith("s ")) and s.count('"') % 2 == 1:
        errores.append(i)
if errores:
    for i in errores[:1]:
        print('File "game/tl/spanish/script.rpy", line %d: is not terminated with a newline. (Check strings and parenthesis.)' % i)
    sys.exit(1)
print("Lint is not a substitute for thorough testing.")
''', encoding="utf-8")
    return sdk


def test_errores_tl_y_texto_original():
    salida = 'File "game/tl/spanish/script.rpy", line 12: x\nFile "game/script.rpy", line 3: y\nFile "game/tl/spanish/script.rpy", line 12: x'
    assert gate.errores_tl(salida) == [("game/tl/spanish/script.rpy", 12)]
    lineas = RPY.splitlines(keepends=True)
    assert gate.texto_original(lineas, 4) == '    s "Hi there! How was class?"\n'
    assert gate.texto_original(lineas, 10) == '    new "Sylvie"\n'
    assert gate.texto_original(lineas, 0) is None


def test_puerta_revierte_lineas_rotas_hasta_que_lint_pasa(tmp_path, monkeypatch):
    game, sdk = _juego(tmp_path), _sdk_falso(tmp_path)
    monkeypatch.setattr(gate, "correr_lint", lambda s, g, timeout=600: (lambda r: (r.returncode, r.stdout + r.stderr))(
        __import__("subprocess").run([sys.executable, str(s), str(g), "lint"], capture_output=True, text=True)))
    log = []
    r = gate.puerta(sdk, game, "spanish", 3, log=log.append)
    assert r["ok"] is True and r["intentos"] == 3 and [(x["linea"], x["despues"]) for x in r["revertidas"]] == [(5, 's "Hi there! How was class?"'), (11, 'new "Sylvie"')]
    texto = (game / "game" / "tl" / "spanish" / "script.rpy").read_text(encoding="utf-8")
    assert 's "Hi there! How was class?"' in texto and 'new "Sylvie"' in texto and 'new "Yo"' in texto
    # error fuera de la traducción: no toca nada
    monkeypatch.setattr(gate, "correr_lint", lambda s, g, timeout=600: (1, 'File "game/script.rpy", line 9: boom'))
    r = gate.puerta(sdk, game, "spanish", 3, log=log.append)
    assert r["ok"] is False and r["revertidas"] == []


def test_catalogo_analiza_y_aplica_acciones_seguras(tmp_path, monkeypatch):
    r = incidencias.analizar("Traceback...\nModuleNotFoundError: No module named 'UnityPy'")
    assert r["id"] == "modulo_faltante" and r["captura"] == "UnityPy" and r["reintentar"] is True
    llamadas = []
    monkeypatch.setattr(incidencias.subprocess, "run", lambda cmd, **k: llamadas.append(cmd) or type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    assert incidencias.aplicar(r) == (True, "instalado UnityPy") and llamadas[0][-1] == "UnityPy"
    assert incidencias.aplicar({**r, "captura": "cosa_rara"})[0] is False           # fuera de la lista permitida: no instala
    assert incidencias.analizar("DeepL HTTP 456: quota exceeded")["id"] == "deepl_agotado"
    assert incidencias.analizar("qa_server no respondio en 1800s")["accion"] == "reiniciar_qa"
    assert incidencias.analizar('File "game/tl/spanish/x.rpy", line 3: bad')["id"] == "parse_tl"
    assert incidencias.analizar("todo bien") is None
    # chmod solo dentro del juego
    game = tmp_path / "J"; game.mkdir(); f = game / "run.sh"; f.write_text("#!/bin/sh"); os.chmod(f, 0o644)
    ok, msg = incidencias.aplicar({"accion": "chmod_exec", "captura": f"'{f}'"}, game)
    assert ok and (os.name != "posix" or os.stat(f).st_mode & stat.S_IXUSR)
    assert incidencias.aplicar({"accion": "chmod_exec", "captura": str(tmp_path / "otro")}, game)[0] is False
    # incidencias + catálogo del usuario
    monkeypatch.setattr(incidencias, "INCIDENCIAS", tmp_path / "inc.jsonl"); monkeypatch.setattr(incidencias, "LOGS", tmp_path)
    monkeypatch.setattr(incidencias, "CATALOGO_USUARIO", tmp_path / "cat.json")
    incidencias.registrar("j1", "translate", "modulo_faltante", "falta", "pip_install", "instalado", "catalogo")
    assert incidencias.ultimas()[0]["job_id"] == "j1"
    rec = incidencias.aprobar_receta({"id": "Mi Receta!", "patron": r"Error raro (\d+)", "causa": "c", "que_hacer": "q", "accion": "rm -rf"})
    assert rec["id"] == "mi_receta_" and rec["accion"] is None and incidencias.analizar("Error raro 7")["id"] == "mi_receta_"
    with pytest.raises(Exception):
        incidencias.aprobar_receta({"id": "x", "patron": "(("})


def test_doctor_parsea_y_valida(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    cat = incidencias.catalogo()
    resp = '```json\n{"causa": "El zip trae el juego anidado", "receta_id": "estructura", "que_hacer": "Subir la carpeta correcta", "confianza": 0.8, "receta_propuesta": {"id": "zip_anidado", "patron": "carpeta anidada", "causa": "c", "que_hacer": "q"}}\n```'
    d = doctor.diagnosticar("estructura no reconocida", "log...", cat, "renpy", fetch=lambda body: resp)
    assert d["receta_id"] == "estructura" and d["confianza"] == 0.8 and d["receta_propuesta"]["id"] == "zip_anidado" and d["modelo"]
    d = doctor.diagnosticar("x", "y", cat, fetch=lambda body: '{"causa":"?","receta_id":"inventada","confianza":2,"receta_propuesta":{"patron":"(("}}')
    assert d["receta_id"] is None and d["confianza"] == 1.0 and d["receta_propuesta"] is None
    monkeypatch.delenv("GROQ_API_KEY")
    assert doctor.diagnosticar("x", "y", cat)["error"] == "sin GROQ_API_KEY"


def test_diagnostico_del_job_aplica_receta_y_pide_reintento(tmp_path, monkeypatch):
    import pipeline_server as ps
    monkeypatch.setattr(incidencias, "INCIDENCIAS", tmp_path / "inc.jsonl"); monkeypatch.setattr(incidencias, "LOGS", tmp_path)
    monkeypatch.setattr(incidencias.subprocess, "run", lambda cmd, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    job = {"job_id": "j9", "status": "error", "error": "ModuleNotFoundError: No module named 'openpyxl'", "events": [], "progress": ["x"], "current_stage": "translate", "engine": {"engine": "rpgmaker"}}
    assert ps._diagnosticar_job(job, tmp_path) is True
    d = job["diagnostico"]
    assert d["origen"] == "catalogo" and d["receta_id"] == "modulo_faltante" and d["accion"] == "pip_install" and d["accion_ok"] is True
    job["reintentado"] = True
    assert ps._diagnosticar_job(job, tmp_path) is False          # nunca más de un reintento
    # sin receta → doctor (sustituido)
    monkeypatch.setattr(ps, "_texto_falla", lambda j: "algo nunca visto")
    monkeypatch.setattr(doctor, "diagnosticar", lambda *a, **k: {"causa": "C", "receta_id": None, "que_hacer": "Q", "confianza": 0.4, "receta_propuesta": None, "modelo": "m"})
    job2 = {"job_id": "j10", "status": "error", "error": "algo nunca visto", "events": [], "progress": [], "current_stage": "package"}
    assert ps._diagnosticar_job(job2, tmp_path) is False and job2["diagnostico"]["origen"] == "doctor" and job2["diagnostico"]["que_hacer"] == "Q"
    # job OK sin avisos: nada
    assert ps._diagnosticar_job({"job_id": "j11", "status": "done", "events": [], "progress": []}, tmp_path) is False
    assert [i["job_id"] for i in incidencias.ultimas()] == ["j9", "j9", "j10"]


def test_sdk_por_version_del_juego(tmp_path, monkeypatch):
    import pipeline_server as ps
    apps = tmp_path / "apps"
    for v in ("8.3.7", "8.5.3", "7.4.11"):
        (apps / f"renpy-{v}-sdk").mkdir(parents=True); (apps / f"renpy-{v}-sdk" / "renpy.sh").write_text("#!/bin/sh")
    monkeypatch.setattr(ps.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("RENPY_SDK", raising=False)
    def juego(ver):
        g = tmp_path / f"J{ver}"; (g / "renpy").mkdir(parents=True)
        (g / "renpy" / "vc_version.py").write_text(f"version_tuple = ({ver.replace('.', ', ')}, vc_version)\n")
        return g
    assert ps.find_renpy_sdk(juego("8.5.0")).parent.name == "renpy-8.5.3-sdk"      # mismo mayor.menor
    assert ps.find_renpy_sdk(juego("8.3.2")).parent.name == "renpy-8.3.7-sdk"
    assert ps.find_renpy_sdk(juego("8.4.1")).parent.name == "renpy-8.5.3-sdk"      # sin 8.4: el menor SDK >= juego
    assert ps.find_renpy_sdk(juego("7.4.11")).parent.name == "renpy-7.4.11-sdk"
    assert ps.find_renpy_sdk(juego("9.0.0")).parent.name == "renpy-8.5.3-sdk"      # nada >=: el más nuevo
    assert ps.find_renpy_sdk(tmp_path / "sin-renpy").parent.name in ("renpy-7.4.11-sdk", "renpy-8.3.7-sdk", "renpy-8.5.3-sdk")
    assert ps.find_renpy_sdk(None) is not None
    monkeypatch.setenv("RENPY_SDK", str(apps / "renpy-8.3.7-sdk"))
    assert ps.find_renpy_sdk(None).parent.name == "renpy-8.3.7-sdk"                 # sin versión: RENPY_SDK manda
    assert incidencias.analizar('renpy.sh translate spanish fallo: \nFile "game/x.rpy", line 3: expected statement.')["id"] == "renpy_version"
    assert incidencias.analizar("[STAGE] analyze decompile_done") is None


def test_version_del_juego_renpy_84_y_script_version(tmp_path):
    import pipeline_server as ps
    g = tmp_path / "G"; (g / "renpy").mkdir(parents=True); (g / "game").mkdir()
    (g / "renpy" / "vc_version.py").write_text("branch = 'fix'\nversion = '8.5.3.26051504'\nversion_name = 'x'\n")
    (g / "renpy" / "__init__.py").write_text('version_tuple = VersionTuple(*(int(i) for i in version.split(".")))\n')
    assert ps.version_renpy_juego(g) == (8, 5, 3)
    (g / "renpy" / "vc_version.py").unlink(); (g / "renpy" / "__init__.py").unlink()
    (g / "game" / "script_version.txt").write_text("(8, 5, 3)\n")
    assert ps.version_renpy_juego(g) == (8, 5, 3)
    import apk_patch
    assert apk_patch.version_renpy(g) == (8, 5, 3)
    assert ps.version_renpy_juego(tmp_path / "nada") is None


ROTO = (
    "# game/options.rpy:32\n"
    "translate spanish strings:\n"
    "\n"
    "    # game/options.rpy:32\n"
    '    old "Line one. Line two."\n'
    '    new "Línea uno.\n'            # el modelo devolvió un salto real → cadena sin cerrar
    'Línea dos derramada."\n'
    "\n"
    "    # game/options.rpy:40\n"
    '    old "Otra"\n'
    '    new "Otra"\n'
)


def test_revertir_limpia_las_lineas_derramadas_de_una_cadena_multilinea(tmp_path):
    game = tmp_path / "J"; tl = game / "game" / "tl" / "spanish"; tl.mkdir(parents=True)
    f = tl / "options.rpy"; f.write_text(ROTO, encoding="utf-8")
    r = gate.revertir_linea(game, "game/tl/spanish/options.rpy", 6)
    assert r["sobrantes"] == 1 and r["despues"] == 'new "Line one. Line two."'
    texto = f.read_text(encoding="utf-8")
    assert "Línea dos derramada" not in texto and 'new "Otra"' in texto and texto.count("translate spanish strings:") == 1
    # si lo que sigue es estructural (otro bloque), no se borra nada
    f.write_text('    new "sin cerrar\n\n    # x\n    old "a"\n    new "a"\n', encoding="utf-8")
    assert gate.revertir_linea(game, "game/tl/spanish/options.rpy", 1) is None or f.read_text(encoding="utf-8").count("old") == 1
