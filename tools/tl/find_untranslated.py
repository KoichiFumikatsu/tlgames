"""Reporta palabras en ingles que quedaron sin traducir en los .rpy.

Estrategia:
  - Parsear cada .rpy con lib_rpy (formatos dialogue + strings)
  - Para cada par (fuente EN, traduccion ES), localizar palabras del
    objetivo que coinciden literalmente con palabras de la fuente y NO
    estan en una lista permitida (glosario, nombres propios canonicos,
    onomatopeyas comunes, palabras EN/ES homografas como 'no', 'a', etc.)
  - Salida: reporte CSV-friendly por consola y archivo .txt con
    `archivo:linea  palabras  ->  traduccion`

Uso:
    python find_untranslated.py --all
    python find_untranslated.py "ruta/script.rpy"
    python find_untranslated.py --all --out report.txt
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from lib_rpy import (  # type: ignore
    parse_dialogue_file,
    parse_strings_file,
    TOKEN_PATTERNS,
)

GAME_TL_DEFAULT = (
    ROOT.parent.parent
    / "proyects Game TL"
    / "FromTheSin"
    / "game"
    / "tl"
    / "spanish"
)
GLOSSARY_FILE = ROOT / "tl-es-glossary.json"

# Palabras que pueden aparecer en ambos idiomas o son aceptables sin traducir.
# - articulos/preps cortas (a, no, etc) -> homografas ES/EN
# - onomatopeyas / interjecciones -> intencional dejarlas
# - signos: se filtran por regex
ALLOWLIST = {
    # homografas o cortas (ES==EN)
    "a", "no", "si", "ti", "mi", "yo", "tu", "su", "la", "el", "los", "las",
    "un", "ah", "oh", "ay", "eh", "uh", "uhm", "hmm", "hmmm", "hm",
    "que", "como", "ver", "fin", "ser", "este", "esta", "esto",
    # interjecciones / onomatopeyas comunes
    "haha", "hehe", "hihi", "hoho", "huh", "hah", "heh", "hyah", "wah",
    "yay", "yahoo", "yup", "nope", "ew", "ow", "ouch", "ugh", "tsk",
    "mhm", "mmm", "mmmm", "mmmmm", "hmph", "phew", "whew", "argh", "grr",
    "shh", "psst", "yawn", "sigh", "gasp", "sniff", "slurp", "munch",
    "gulp", "burp", "snore", "thud", "boom", "bang", "pow", "zap",
    "ding", "dong", "tick", "tock", "click", "clack", "bzzt", "buzz",
    "zoom", "vroom", "splash", "plop", "drip", "drop", "ring", "ahem",
    "okay", "ok",
    # palabras de RPG / proyecto que se mantienen en ingles intencional
    "mana", "ki", "hp", "mp",
    # cognados ES/EN comunes (misma escritura)
    "bar", "horizontal", "vertical", "ego", "auto", "audio", "video",
    "menu", "internet", "online", "web", "email", "fax", "radio",
    "sandwich", "ok", "iglu", "set", "test", "stop", "hotel", "motel",
    "metro", "taxi", "robot", "club", "tribu", "popular", "natural",
    "general", "individual", "social", "moral", "real", "ideal", "central",
    "local", "global", "total", "final", "personal", "normal", "actual",
    "formal", "legal", "vital", "fatal", "rural", "neutral", "fundamental",
    "musical", "tropical", "digital", "virtual", "manual", "casual",
    "criminal", "espiritual", "intelectual", "festival", "animal",
    "color", "sector", "doctor", "factor", "actor", "motor", "honor",
    "error", "humor", "rumor", "valor", "horror", "terror", "favor",
    "panel", "hotel", "nivel", "cruel", "fiel", "miel", "papel",
    "mente", "frente", "dental", "mental", "literal", "industrial",
    "hostal", "cardinal", "criminal", "judicial", "espiritual",
    # Ren'Py / tecnicos que NO se traducen
    "joystick", "software", "hardware", "mit", "gnu", "lesser", "public",
    "license", "licenses", "renpy", "python", "github", "discord", "twitter",
    "patreon", "steam", "fanbox", "dejavu", "sans", "serif", "ttf", "otf",
    "directory", "developer", "developers", "developer's",
    # Nombres propios del juego (personajes / lugares / razas)
    "linea", "linea'd", "eris", "cluster", "lily", "nova", "silika", "altra",
    "rika", "cetia", "yurei", "kironomiya", "rinoa", "ada", "zell",
    "endo", "omnium", "koikatsu", "yumeko",
    "monstergirl", "monstergirls",
}

# Palabras propias del proyecto / nombres / placeholders (casing-sensitive)
PROPER_NAMES_INSENSITIVE: set[str] = set()


def load_glossary_words() -> set[str]:
    """Devuelve TODOS los terminos (lowercase) presentes en el glosario,
    tanto en source como target."""
    if not GLOSSARY_FILE.exists():
        return set()
    data = json.loads(GLOSSARY_FILE.read_text(encoding="utf-8"))
    out: set[str] = set()
    for entry in data.values() if isinstance(data, dict) else data:
        if isinstance(entry, dict):
            for key in ("source", "target", "name", "translation", "es", "en"):
                v = entry.get(key)
                if isinstance(v, str):
                    for w in re.findall(r"[A-Za-z]+", v):
                        out.add(w.lower())
        elif isinstance(entry, str):
            for w in re.findall(r"[A-Za-z]+", entry):
                out.add(w.lower())
    return out


def load_glossary_keys_simple() -> set[str]:
    """Soporta ambos formatos: dict plano {EN: ES} o estructurado."""
    if not GLOSSARY_FILE.exists():
        return set()
    out: set[str] = set()
    try:
        data = json.loads(GLOSSARY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return out
    def _eat(s: str) -> None:
        for w in re.findall(r"[A-Za-z]+", s):
            out.add(w.lower())
    if isinstance(data, dict):
        for k, v in data.items():
            _eat(k)
            if isinstance(v, str):
                _eat(v)
            elif isinstance(v, dict):
                for vv in v.values():
                    if isinstance(vv, str):
                        _eat(vv)
    elif isinstance(data, list):
        for it in data:
            if isinstance(it, str):
                _eat(it)
            elif isinstance(it, dict):
                for vv in it.values():
                    if isinstance(vv, str):
                        _eat(vv)
    return out


def strip_tokens(text: str) -> str:
    """Elimina tags/vars/placeholders/escapes para no analizarlos."""
    out = text
    for pat, _ in TOKEN_PATTERNS:
        out = pat.sub(" ", out)
    return out


WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’]*")


def extract_words(text: str) -> list[str]:
    return WORD_RE.findall(strip_tokens(text))


def find_leaks(source: str, target: str, allowed: set[str]) -> list[str]:
    """Palabras del source que aparecen tal cual en target y no estan permitidas."""
    src_words = {w.lower() for w in extract_words(source) if len(w) >= 2}
    leaks: list[str] = []
    for w in extract_words(target):
        if len(w) < 2:
            continue
        wl = w.lower()
        if wl in allowed:
            continue
        if wl not in src_words:
            continue  # palabra extranjera no proviene del source -> ignorar
        # Excluir si arranca con mayuscula y aparece exactamente igual en source
        # (probable nombre propio / variable).
        if w[0].isupper() and w in source:
            # Solo marcar si NO empieza la cadena (que seria normal por mayuscula tras .)
            # Conservador: marcar para revision pero con nota
            leaks.append(w)
            continue
        leaks.append(w)
    # Deduplicar conservando orden
    seen = set()
    uniq = []
    for w in leaks:
        if w not in seen:
            seen.add(w)
            uniq.append(w)
    return uniq


def collect_blocks(path: Path):
    """Devuelve lista de (line_target, source, target, kind)."""
    items: list[tuple[int, str, str, str]] = []
    text = path.read_text(encoding="utf-8")
    has_strings = "translate spanish strings:" in text.lower()
    has_dialog = re.search(r"^translate\s+spanish\s+\S+:\s*$", text, re.MULTILINE | re.IGNORECASE) is not None
    if has_dialog:
        for b in parse_dialogue_file(str(path)):
            items.append((b.line_target + 1, b.source, b.current_target, "dialogue"))
    if has_strings:
        for b in parse_strings_file(str(path)):
            items.append((b.line_new + 1, b.source, b.current_target, "string"))
    return items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--root", help="directorio tl/<idioma> para --all")
    ap.add_argument("--out", default="", help="archivo de salida (.txt)")
    ap.add_argument("--min-words", type=int, default=1,
                    help="reportar solo si encuentra al menos N palabras")
    ap.add_argument("--min-len", type=int, default=4,
                    help="ignorar palabras mas cortas que N (default 4)")
    ap.add_argument("--by-word", action="store_true",
                    help="agrupar por palabra con frecuencia y muestras")
    ap.add_argument("--add-markers", action="store_true",
                    help="insertar comentarios # TODO[en]: ... antes de cada linea sospechosa "
                         "para que puedas buscar TODO[en] en el editor")
    args = ap.parse_args()

    if args.all:
        root = Path(args.root) if args.root else GAME_TL_DEFAULT
        targets = sorted(root.glob("*.rpy"))
    else:
        targets = [Path(f) for f in args.files]
    if not targets:
        print("nada que procesar", file=sys.stderr)
        return 1

    glossary_words = load_glossary_keys_simple()
    allowed = ALLOWLIST | glossary_words

    rows: list[str] = []
    word_index: dict[str, list[str]] = {}  # palabra -> [archivo:linea, ...]
    total = 0
    files_to_mark: dict[Path, set[int]] = {}

    for p in targets:
        if not p.exists():
            print(f"[skip] no existe: {p}")
            continue
        blocks = collect_blocks(p)
        file_hits = 0
        for line_no, src, tgt, kind in blocks:
            if not tgt.strip():
                continue
            leaks = [w for w in find_leaks(src, tgt, allowed) if len(w) >= args.min_len]
            if len(leaks) < args.min_words:
                continue
            file_hits += 1
            row = f"{p.name}:{line_no}\t[{','.join(leaks)}]\tEN: {src[:120]}\tES: {tgt[:160]}"
            rows.append(row)
            for w in leaks:
                word_index.setdefault(w.lower(), []).append(f"{p.name}:{line_no}")
            files_to_mark.setdefault(p, set()).add(line_no)
        print(f"{p.name}: {file_hits} lineas con posible ingles")
        total += file_hits

    print(f"\nTOTAL: {total} lineas con posible ingles sin traducir")
    print(f"      {len(word_index)} palabras distintas")

    if args.add_markers:
        marker_count = 0
        for p, line_set in files_to_mark.items():
            text_lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
            new_lines: list[str] = []
            for i, line in enumerate(text_lines, 1):
                # remover marcadores existentes para idempotencia
                if line.lstrip().startswith("# TODO[en]"):
                    continue
                new_lines.append(line)
                if i in line_set:
                    indent = len(line) - len(line.lstrip())
                    new_lines.append(" " * indent + "# TODO[en]: revisar palabras inglesas\n")
                    marker_count += 1
            p.write_text("".join(new_lines), encoding="utf-8")
        print(f"insertados {marker_count} marcadores TODO[en]")

    out_text_parts: list[str] = []
    if args.by_word:
        out_text_parts.append("=== POR PALABRA (frecuencia, muestras) ===")
        for w, locs in sorted(word_index.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            sample = ", ".join(locs[:5])
            extra = f" (+{len(locs)-5} mas)" if len(locs) > 5 else ""
            out_text_parts.append(f"{len(locs):4d}  {w:24s}  {sample}{extra}")
        out_text_parts.append("")
    out_text_parts.append("=== POR LINEA ===")
    out_text_parts.extend(rows)

    if args.out:
        Path(args.out).write_text("\n".join(out_text_parts) + "\n", encoding="utf-8")
        print(f"reporte: {args.out}")
    elif rows:
        if args.by_word:
            print("\n--- top 30 palabras ---")
            for w, locs in sorted(word_index.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:30]:
                print(f"{len(locs):4d}  {w:24s}  {locs[0]}")
        else:
            print("\n--- primeros 40 ---")
            for r in rows[:40]:
                print(r)
            if len(rows) > 40:
                print(f"... ({len(rows) - 40} mas; usa --out para volcar todo)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
