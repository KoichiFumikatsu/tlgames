"""Fix unrpyc artifact: 'show X at Y:' or 'scene X at Y:' with NO indented block.
Removes trailing ':' when next non-empty line is at same or lesser indent.

Usage:
  python fix_empty_blocks.py <root_dir> [--dry]
"""
import sys, re, io, os
from pathlib import Path

# Statements que toleran tener `:` (o no) y donde la decompilación de unrpyc
# a veces deja el `:` espurio.
TRIGGER = re.compile(r'^(\s+)(show|scene|hide)\s+.+:\s*$')

def fix_file(path: Path, dry: bool) -> int:
    text = path.read_text(encoding='utf-8')
    lines = text.split('\n')
    fixed = 0
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = TRIGGER.match(line)
        if m:
            indent = m.group(1)
            # mirar siguiente linea no vacia
            j = i + 1
            while j < len(lines) and lines[j].strip() == '':
                j += 1
            next_line = lines[j] if j < len(lines) else ''
            # contar indent de la siguiente
            next_indent = re.match(r'^(\s*)', next_line).group(1) if next_line else ''
            if len(next_indent) <= len(indent):
                # bloque vacio -> quitar ':'
                out.append(line[:-1].rstrip() + ('' if line.endswith(':') else ''))
                # Aseguramos remover solo el ':' final preservando trailing whitespace minimal
                # rebuild correcto:
                out[-1] = re.sub(r':\s*$', '', line)
                fixed += 1
                i += 1
                continue
        out.append(line)
        i += 1
    if fixed and not dry:
        path.write_text('\n'.join(out), encoding='utf-8')
    return fixed

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    root = Path(sys.argv[1])
    dry = '--dry' in sys.argv
    total = 0
    files_changed = 0
    for rpy in root.rglob('*.rpy'):
        n = fix_file(rpy, dry)
        if n:
            total += n
            files_changed += 1
            print(f'  {rpy.relative_to(root)}: {n}')
    print(f'\n{"DRY-RUN " if dry else ""}fixed {total} lines en {files_changed} archivos')

if __name__ == '__main__':
    main()
