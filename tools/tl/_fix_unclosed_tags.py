"""Detecta y opcionalmente arregla tags Ren'Py abiertas pero no cerradas en
targets de traducción. Compara el target con el comentario source-of-truth
inmediatamente anterior y si el source tenía pares matched (ej. {sc=3}...{/sc})
y el target perdió el cierre, lo añade al final del string.

Uso:
  python tools\\tl\\_fix_unclosed_tags.py <archivo.rpy>           # dry-run
  python tools\\tl\\_fix_unclosed_tags.py <archivo.rpy> --apply   # escribe
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

# Tags pareadas conocidas en Ren'Py (las que requieren cierre)
PAIRED_TAGS = {
    "b", "i", "u", "s", "k", "color", "outlinecolor", "size", "alpha",
    "alt", "noalt", "art", "font", "plain", "cps", "vspace", "space",
    # Custom tags vistos en BD
    "sc",
}

TAG_RE = re.compile(r"\{(/?)([a-zA-Z_]+)(?:=[^}]*)?\}")


def extract_tags(text: str) -> list[tuple[str, str]]:
    """Devuelve [(open_or_close, name), ...]"""
    return [(m.group(1), m.group(2).lower()) for m in TAG_RE.finditer(text)]


def find_unclosed(text: str) -> list[str]:
    """Devuelve lista de tags abiertas sin cerrar (en orden de apertura).

    Permite cierres mal anidados: un {/X} cierra el último {X} abierto en el
    stack aunque no sea el top. Es lo que hace Ren'Py en la práctica.
    """
    stack: list[str] = []
    for kind, name in extract_tags(text):
        if name not in PAIRED_TAGS:
            continue
        if kind == "":  # opening
            stack.append(name)
        else:  # closing — buscar el último match en el stack
            for j in range(len(stack) - 1, -1, -1):
                if stack[j] == name:
                    del stack[j]
                    break
    return stack


def fix_file(path: Path, apply: bool) -> int:
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    fixes = 0
    last_source_comment = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        # Capturar comentario source: # "..."
        m_src = re.match(r'^\s*#\s*(.*)$', line)
        if m_src and m_src.group(1).startswith('"'):
            last_source_comment = m_src.group(1)
            continue

        # Línea de target: empieza con comilla o "name "
        m_tgt = re.match(r'^(\s*)((?:\w+\s+)?)(")(.*)(")(\s*)$', line)
        if not m_tgt:
            continue

        indent, prefix, q1, body, q2, suffix = m_tgt.groups()
        unclosed = find_unclosed(body)
        if not unclosed:
            continue

        # Solo arreglar si el source tenía la tag cerrada
        src_closed = True
        if last_source_comment:
            src_unclosed = find_unclosed(last_source_comment.strip('"'))
            src_closed = not src_unclosed

        if not src_closed:
            # source también está roto, no tocar
            continue

        new_body = body
        for tag in reversed(unclosed):
            new_body += f"{{/{tag}}}"

        new_line = f"{indent}{prefix}{q1}{new_body}{q2}{suffix}"
        print(f"L{i+1}: {line.strip()}")
        print(f"   -> {new_line.strip()}")
        lines[i] = new_line
        fixes += 1

    if apply and fixes:
        bak = path.with_suffix(path.suffix + ".unclosed-bak")
        if not bak.exists():
            shutil.copy2(path, bak)
        path.write_text("\n".join(lines), encoding="utf-8")
        print(f"\n[apply] {fixes} fixes escritos en {path.name} (backup: {bak.name})")
    else:
        print(f"\n[dry] {fixes} casos detectados (use --apply)")
    return fixes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", help="archivos .rpy o directorios")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    total = 0
    for arg in args.paths:
        p = Path(arg)
        if p.is_dir():
            files = list(p.rglob("*.rpy"))
        else:
            files = [p]
        for f in files:
            print(f"\n=== {f} ===")
            total += fix_file(f, args.apply)
    print(f"\nTOTAL: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
