"""
Revisión manual de una traducción Ren'Py desde el taller, sin tocar archivos a mano ni depender del asistente:
listar líneas (diálogos y strings) con filtros, editar una línea, marcar líneas para retraducir (se vacían y el
pipeline las vuelve a traducir) y ver cuánto falta por hablante.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_rpy import parse_dialogue_file, parse_strings_file, partir_dialogo, write_target_line  # noqa: E402

PROTEGIDO_RE = re.compile(r"\{[^{}]+\}|\[[^\[\]]+\]|\|[A-Za-z0-9_]+\|")


def _sin_traducir(source: str, target: str) -> bool:
    s, t = PROTEGIDO_RE.sub("", source).strip(), PROTEGIDO_RE.sub("", target).strip()
    return (not t or t == s) and len(s) >= 4 and any(c.isalpha() for c in s)


def tl_dir(game_path: Path, lang: str = "spanish") -> Path:
    return Path(game_path) / "game" / "tl" / lang


def lineas(game_path: Path, lang: str = "spanish") -> list[dict]:
    """Todas las líneas traducibles de game/tl/<lang>/ con archivo, línea (1-based del target), hablante, source, target."""
    base = tl_dir(game_path, lang)
    out = []
    if not base.is_dir():
        return out
    for rpy in sorted(base.rglob("*.rpy")):
        rel = rpy.relative_to(base).as_posix()
        for b in parse_dialogue_file(str(rpy)):
            out.append({"archivo": rel, "linea": b.line_target + 1, "tipo": "dialogo", "hablante": b.char or "(narrador)",
                        "source": b.source, "target": b.current_target, "sin_traducir": _sin_traducir(b.source, b.current_target)})
        for s in parse_strings_file(str(rpy)):
            out.append({"archivo": rel, "linea": s.line_new + 1, "tipo": "string", "hablante": "(interfaz)",
                        "source": s.source, "target": s.current_target, "sin_traducir": _sin_traducir(s.source, s.current_target)})
    return out


def resumen(items: list[dict]) -> dict:
    por = {}
    for it in items:
        d = por.setdefault(it["hablante"], {"total": 0, "sin_traducir": 0})
        d["total"] += 1
        d["sin_traducir"] += int(it["sin_traducir"])
    return {"total": len(items), "sin_traducir": sum(1 for i in items if i["sin_traducir"]),
            "hablantes": [{"hablante": h, **v} for h, v in sorted(por.items(), key=lambda kv: (-kv[1]["sin_traducir"], -kv[1]["total"]))]}


def listar(game_path: Path, lang: str = "spanish", filtro: str = "todo", q: str = "", hablante: str = "", pagina: int = 1, por_pagina: int = 30) -> dict:
    items = lineas(game_path, lang)
    res = resumen(items)
    if filtro == "sin_traducir":
        items = [i for i in items if i["sin_traducir"]]
    if hablante:
        items = [i for i in items if i["hablante"] == hablante]
    if q:
        ql = q.lower()
        items = [i for i in items if ql in i["source"].lower() or ql in i["target"].lower()]
    total = len(items)
    paginas = max(1, -(-total // por_pagina))
    pagina = min(max(1, int(pagina or 1)), paginas)
    return {"lineas": items[(pagina - 1) * por_pagina: pagina * por_pagina], "total": total, "pagina": pagina, "paginas": paginas,
            "por_pagina": por_pagina, "resumen": res}


def _leer(base: Path, archivo: str) -> tuple[Path, list[str]]:
    ruta = (base / archivo).resolve()
    if base.resolve() not in ruta.parents or ruta.suffix != ".rpy" or not ruta.is_file():
        raise ValueError("archivo fuera de la traducción")
    return ruta, ruta.read_text(encoding="utf-8-sig", errors="replace").splitlines(keepends=True)


def editar(game_path: Path, archivo: str, linea: int, texto: str, lang: str = "spanish") -> dict:
    """Reescribe el texto traducido de esa línea (diálogo `who "…"` o `new "…"`), conservando prefijo/sufijo."""
    base = tl_dir(game_path, lang)
    ruta, ls = _leer(base, archivo)
    idx = int(linea) - 1
    if not 0 <= idx < len(ls):
        raise ValueError("línea fuera de rango")
    original = ls[idx]
    s = original.strip()
    if s.startswith("#") or s.startswith("old ") or not partir_dialogo(s.removeprefix("new ").strip() if s.startswith("new ") else s):
        raise ValueError("esa línea no es una línea traducible")
    if "\n" in texto or "\r" in texto:
        raise ValueError("el texto no puede tener saltos de línea reales (usa \\n)")
    ls[idx] = write_target_line(original, texto)
    ruta.write_text("".join(ls), encoding="utf-8")
    return {"archivo": archivo, "linea": linea, "antes": s, "despues": ls[idx].strip()}


def vaciar(game_path: Path, items: list[dict], lang: str = "spanish") -> int:
    """Deja vacío el target de esas líneas para que el pipeline las vuelva a traducir."""
    base = tl_dir(game_path, lang)
    por_archivo: dict[str, list[int]] = {}
    for it in items:
        por_archivo.setdefault(str(it.get("archivo", "")), []).append(int(it.get("linea", 0)))
    n = 0
    for archivo, lns in por_archivo.items():
        ruta, ls = _leer(base, archivo)
        for linea in lns:
            idx = linea - 1
            if 0 <= idx < len(ls):
                s = ls[idx].strip()
                if s.startswith("#") or s.startswith("old "):
                    continue
                ls[idx] = write_target_line(ls[idx], "")
                n += 1
        ruta.write_text("".join(ls), encoding="utf-8")
    return n
