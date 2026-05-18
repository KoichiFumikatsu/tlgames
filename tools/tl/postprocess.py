"""Post-proceso deterministico sobre archivos .rpy traducidos.

Corrige patrones sistematicos que DeepL produce mal:
  - "Don't" (contraccion ingles) interpretado como honorifico "Don":
        "Don no X"  -> "No X"
        "Don No X"  -> "No X"
  - Mayusculas de ciertas palabras preservadas: "Maquinas" -> "Maquinas"
    (placeholder, ver lista EXTRA).

Solo toca LINEAS DE TRADUCCION (las que empiezan por un rol/indentadas con "),
nunca comentarios (lineas #) ni las `old "..."` (fuente).

Uso:
    python postprocess.py <archivo.rpy> [<archivo2.rpy> ...]
    python postprocess.py --all   # todos los .rpy en tl/spanish
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# Default tl dir (FromTheSin legacy). Use --root or pass tl dir to --all.
DEFAULT_GAME_TL = (
    ROOT.parent.parent
    / "proyects Game TL"
    / "FromTheSin"
    / "game"
    / "tl"
    / "spanish"
)

# (regex, reemplazo, descripcion)
# Estrategia: en un solo paso, segun contexto precedente, decidir mayuscula.
# Todos los "Don no"/"Don No" vistos en el corpus siguen a inicio / puntuacion /
# apertura, asi que siempre capitalizamos salvo si el contexto previo
# es claramente intra-oracional (ej. ", Don no ...").

# Contexto que exige mayuscula (inicio de cadena, tras puntuacion fuerte, tras
# apertura de cita/parentesis, tras guion largo/corto al inicio de linea, o
# tras un tag Ren'Py de cierre `}` que abre el contenido visible).
_LEAD_STRONG = r'(?P<lead>^|["\'(\[|¡¿}]|[.!?¡¿…]\s+|—\s*|-\s*)'
# Cualquier otro contexto (coma, espacio normal, palabra previa).
_LEAD_WEAK = r'(?P<lead>,\s+|\s+)'

FIXES: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(_LEAD_STRONG + r"Don\s+[Nn]o\b"), r"\g<lead>No", "Don [Nn]o (inicio) -> No"),
    (re.compile(_LEAD_WEAK   + r"Don\s+[Nn]o\b"), r"\g<lead>no", "Don [Nn]o (medio) -> no"),
    # "I" residual de DeepL: pronombre ingles dejado sin traducir al inicio
    # de oracion (ej. 'I no deberia...', 'I se suponia...', 'I ESTARA...').
    # Patron: I + espacio + palabra que empieza por letra latina/espanola
    # (mayus o minus, incluyendo tildes y enie). Solo en contextos de inicio.
    (re.compile(_LEAD_STRONG + r"I\s+(?=[A-Za-zÁÉÍÓÚÜÑáéíóúüñ])"), r"\g<lead>", "I residual (inicio) eliminado"),
    # "YOU" residual de DeepL en mayusculas: aparece tras tag {font=...} en
    # texto gritado. Eliminamos el "YOU" preservando el lead (tag).
    (re.compile(_LEAD_STRONG + r"YOU\s+(?=[A-ZÁÉÍÓÚÜÑ])"), r"\g<lead>", "YOU residual (mayus) eliminado"),
]


def is_target_line(line: str) -> bool:
    """Una linea es de traduccion si NO empieza por '#' y NO es 'old ...'.

    Ren'Py usa:
        # source (comentario)
        translated_string
    o en strings:
        old "..."
        new "..."
    Editamos la `new` pero no la `old`.
    """
    s = line.lstrip()
    if s.startswith("#"):
        return False
    if s.startswith("old ") or s.startswith('old\t'):
        return False
    # Debe contener una cadena "..." para considerar que hay contenido
    return '"' in line


def fix_line(line: str) -> tuple[str, int]:
    n = 0
    for pat, repl, _ in FIXES:
        new, c = pat.subn(repl, line)
        if c:
            line = new
            n += c
    return line, n


def process_file(path: Path, dry: bool = False) -> tuple[int, int]:
    text = path.read_text(encoding="utf-8")
    out_lines: list[str] = []
    changes = 0
    touched_lines = 0
    for line in text.splitlines(keepends=True):
        if is_target_line(line):
            new_line, n = fix_line(line)
            if n:
                changes += n
                touched_lines += 1
            out_lines.append(new_line)
        else:
            out_lines.append(line)
    if changes and not dry:
        path.write_text("".join(out_lines), encoding="utf-8")
    return changes, touched_lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", help=".rpy a procesar")
    ap.add_argument("--all", action="store_true", help="todos los .rpy en --root o default")
    ap.add_argument("--root", help="directorio tl/<idioma> a procesar con --all")
    ap.add_argument("--dry", action="store_true", help="no escribir, solo reportar")
    args = ap.parse_args()

    if args.all:
        root = Path(args.root) if args.root else DEFAULT_GAME_TL
        targets = sorted(root.glob("*.rpy"))
    else:
        targets = [Path(f) for f in args.files]
    if not targets:
        print("nada que procesar", file=sys.stderr)
        return 1

    grand_changes = 0
    grand_lines = 0
    for p in targets:
        if not p.exists():
            print(f"[skip] no existe: {p}")
            continue
        c, ln = process_file(p, dry=args.dry)
        grand_changes += c
        grand_lines += ln
        marker = "[dry]" if args.dry else "[ok]"
        print(f"{marker} {p.name}: {c} correcciones en {ln} lineas")
    print(f"\nTOTAL: {grand_changes} correcciones en {grand_lines} lineas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
