"""
Puerta de calidad Ren'Py: `renpy.sh <juego> lint` carga todos los scripts (incluidos los .rpy traducidos) y
detecta lo que rompería el juego al arrancar (comilla sin cerrar, sintaxis, traducción duplicada). Si el error
está en `game/tl/<idioma>/`, se **revierte esa línea al inglés original** (que está en el `old "…"` o en el
comentario `# …` de arriba) y se vuelve a pasar el lint, hasta `max_intentos`. Es la autocorrección más
segura posible: nunca inventa texto, solo deja la línea como venía del juego.

Uso: python renpy_lint_gate.py <ruta_juego> [--sdk renpy.sh] [--max 3]
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

_ERROR_RE = re.compile(r'File "([^"]+)", line (\d+)(?::| in [^\n]*\n[^\n]*\n[^\n]*File "[^"]+", line (?:\d+))?\s*(.*)')
_FILE_LINE_RE = re.compile(r'File "([^"]+\.rpy)", line (\d+)')
_STRING_LINE_RE = re.compile(r'^(\s*)(new|old)\s+"')
_DIALOGO_RE = re.compile(r'^(\s*)(?:(\w+)\s+)?"')


def correr_lint(sdk: Path, game_path: Path, timeout: int = 600) -> tuple[int, str]:
    env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    r = subprocess.run([str(sdk), str(game_path), "lint"], capture_output=True, text=True, timeout=timeout,
                       cwd=str(game_path.parent), env=env)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def errores_tl(salida: str, lang: str = "spanish") -> list[tuple[str, int]]:
    """(archivo relativo, línea) de cada error que apunta a game/tl/<lang>/…, sin duplicados y en orden."""
    vistos, out = set(), []
    for archivo, linea in _FILE_LINE_RE.findall(salida):
        archivo = archivo.replace("\\", "/")
        if f"/tl/{lang}/" in f"/{archivo}" and (archivo, int(linea)) not in vistos:
            vistos.add((archivo, int(linea)))
            out.append((archivo, int(linea)))
    return out


def texto_original(lineas: list[str], idx: int) -> str | None:
    """Línea en inglés que corresponde a lineas[idx] (0-based): el `old` de un `new`, o el comentario `# …` de arriba."""
    linea = lineas[idx]
    m = _STRING_LINE_RE.match(linea)
    if m and m.group(2) == "new":
        for j in range(idx - 1, max(-1, idx - 4), -1):
            mo = re.match(r'^(\s*)old\s+(".*")\s*$', lineas[j].rstrip("\n"))
            if mo:
                return f"{m.group(1)}new {mo.group(2)}\n"
        return None
    if _DIALOGO_RE.match(linea):
        for j in range(idx - 1, max(-1, idx - 4), -1):
            mc = re.match(r'^(\s*)#\s?(.*\S)\s*$', lineas[j].rstrip("\n"))
            if mc and '"' in mc.group(2):
                return f"{mc.group(1)}{mc.group(2)}\n"
        return None
    return None


_ESTRUCTURA_RE = re.compile(r'^\w+\s+"')   # `mc "…"`, `ve neu "…"`: línea de diálogo, no texto derramado


def _comillas_abiertas(linea: str) -> bool:
    """True si la línea deja una cadena sin cerrar (número impar de comillas no escapadas)."""
    return len(re.findall(r'(?<!\\)"', linea)) % 2 == 1


def _estructural(linea: str) -> bool:
    s = linea.strip()
    return s.startswith(("translate ", "#", "old ", "new ", "label ", "screen ", "init ", "define ", "default ")) or bool(_ESTRUCTURA_RE.match(s))


def _derrame(lineas: list[str], idx: int) -> int:
    """Cuántas líneas siguientes son texto derramado de la cadena de lineas[idx] (0 si no hay derrame).
    Son derrame las líneas no estructurales hasta la que cierra la cadena (termina en comilla)."""
    for j in range(idx + 1, min(len(lineas), idx + 21)):
        if _estructural(lineas[j]):
            return 0
        if lineas[j].rstrip().endswith('"'):
            return j - idx
    return 0


def revertir_linea(game_path: Path, archivo: str, linea: int) -> dict | None:
    """Deja la línea como el original y borra el texto derramado si el modelo metió saltos de línea reales.
    Si el lint apunta al final del derrame, sube a la línea traducible culpable."""
    ruta = game_path / archivo
    if not ruta.exists():
        return None
    lineas = ruta.read_text(encoding="utf-8-sig", errors="replace").splitlines(keepends=True)
    idx = linea - 1
    if not 0 <= idx < len(lineas):
        return None
    original = texto_original(lineas, idx)
    if original is None:
        for k in range(idx - 1, max(-1, idx - 21), -1):
            candidato = texto_original(lineas, k)
            if candidato and _derrame(lineas, k):
                idx, original, linea = k, candidato, k + 1
                break
    if original is None or original == lineas[idx]:
        return None
    antes = lineas[idx]
    sobrantes = _derrame(lineas, idx)
    if sobrantes:
        del lineas[idx + 1: idx + 1 + sobrantes]
    lineas[idx] = original
    ruta.write_text("".join(lineas), encoding="utf-8")
    return {"archivo": archivo, "linea": linea, "antes": antes.strip(), "despues": original.strip(), "sobrantes": sobrantes}


def puerta(sdk: Path, game_path: Path, lang: str = "spanish", max_intentos: int = 3, log=print) -> dict:
    """Lint → revertir líneas rotas de la traducción → lint… Devuelve {ok, intentos, revertidas, salida}."""
    revertidas = []
    salida = ""
    for intento in range(1, max_intentos + 1):
        rc, salida = correr_lint(sdk, game_path)
        if rc == 0:
            log(f"[LINT] renpy lint OK (intento {intento})")
            return {"ok": True, "intentos": intento, "revertidas": revertidas, "salida": salida[-2000:]}
        errores = errores_tl(salida, lang)
        log(f"[LINT] renpy lint falló (rc={rc}); {len(errores)} error(es) en tl/{lang}")
        if not errores:
            break   # el error no está en la traducción: no hay nada seguro que revertir
        arregladas = 0
        for archivo, linea in errores:
            r = revertir_linea(game_path, archivo, linea)
            if r:
                arregladas += 1
                revertidas.append(r)
                log(f"[LINT] revertida {archivo}:{linea} → {r['despues'][:80]}")
        if not arregladas:
            break
    return {"ok": False, "intentos": min(max_intentos, len(revertidas) + 1), "revertidas": revertidas, "salida": salida[-2000:]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game_path")
    ap.add_argument("--sdk", default=os.environ.get("RENPY_SDK", ""))
    ap.add_argument("--lang", default="spanish")
    ap.add_argument("--max", type=int, default=3)
    a = ap.parse_args(argv)
    sdk = Path(a.sdk)
    if sdk.is_dir():
        sdk = sdk / "renpy.sh"
    if not sdk.exists():
        print("[ABORT] renpy.sh no encontrado (--sdk o RENPY_SDK)")
        return 2
    r = puerta(sdk, Path(a.game_path), a.lang, a.max)
    print(("OK" if r["ok"] else "FALLÓ") + f" · {len(r['revertidas'])} líneas revertidas")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
