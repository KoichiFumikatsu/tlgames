"""
Vacia los `target` de bloques de traduccion donde `target == source`
(auto-fill por defecto de `renpy.exe . translate <lang>`), dejando intactas
las traducciones humanas (target != source).

Despues de esto, `translate.py` los detecta como pendientes y los traduce
con MT, sin tocar el trabajo humano previo.

Uso:
  python tools\tl\clear_mirror_targets.py "<juego>\game\tl\spanish\script.rpy"
  python tools\tl\clear_mirror_targets.py --all "<juego>\game\tl\spanish"
  python tools\tl\clear_mirror_targets.py --dry "<juego>\game\tl\spanish\script.rpy"

Idempotente. Backup .bak la primera vez por archivo.
"""
from __future__ import annotations
import argparse, sys, shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib_rpy import parse_dialogue_file, parse_strings_file, write_target_line


def process(path: Path, dry: bool) -> tuple[int, int]:
    """Devuelve (total_blocks, cleared)."""
    text = path.read_text(encoding="utf-8")

    # parse ambos formatos; lib_rpy detecta solo
    dialogues = parse_dialogue_file(str(path))
    strings = parse_strings_file(str(path))

    lines = text.splitlines(keepends=True)
    cleared = 0
    total = 0

    for b in dialogues:
        total += 1
        if b.current_target == b.source and b.source.strip():
            lines[b.line_target] = write_target_line(lines[b.line_target], "")
            cleared += 1

    for b in strings:
        total += 1
        # StringBlock usa line_new
        line_no = getattr(b, "line_new", None) or getattr(b, "line_target", None)
        if line_no is None:
            continue
        if b.current_target == b.source and b.source.strip():
            lines[line_no] = write_target_line(lines[line_no], "")
            cleared += 1

    if cleared and not dry:
        bak = path.with_suffix(path.suffix + ".mirror-bak")
        if not bak.exists():
            shutil.copy2(path, bak)
        path.write_text("".join(lines), encoding="utf-8")

    return total, cleared


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="archivo .rpy o carpeta (con --all)")
    ap.add_argument("--all", action="store_true", help="procesar todos los .rpy de la carpeta")
    ap.add_argument("--dry", action="store_true", help="no escribir, solo reportar")
    args = ap.parse_args()

    p = Path(args.path)
    files: list[Path]
    if args.all:
        if not p.is_dir():
            print(f"ERROR: {p} no es carpeta", file=sys.stderr); sys.exit(2)
        files = sorted(p.rglob("*.rpy"))
    else:
        if not p.is_file():
            print(f"ERROR: {p} no es archivo", file=sys.stderr); sys.exit(2)
        files = [p]

    grand_total = grand_cleared = 0
    for f in files:
        total, cleared = process(f, args.dry)
        grand_total += total
        grand_cleared += cleared
        flag = "DRY" if args.dry else "OK"
        print(f"  [{flag}] {f.name:40s} total={total:5d} cleared={cleared:5d}")

    print(f"\nTOTAL: {grand_total} bloques | {grand_cleared} targets vaciados (mirror=source)")


if __name__ == "__main__":
    main()
