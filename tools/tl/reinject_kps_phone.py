#!/usr/bin/env python3
# Reinyecta traducciones del corpus KPS phone in-place en archivos .rpy.
# Lee corpus_translated.jsonl (campos: file, line, col_start, col_end, source, target, kind).
# Aplica reemplazos por archivo en ORDEN DESCENDENTE de (line, col_start) para no descuadrar offsets.
# Hace backup .bak antes de tocar cada archivo (a menos que --no-backup).
#
# Uso: python3 reinject_kps_phone.py corpus_translated.jsonl [--no-backup] [--dry-run]

import argparse
import json
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

ASSET_EXT_RE = re.compile(r"\.(png|jpg|jpeg|svg|gif|webp|mp4|webm|wav|ogg|mp3)$", re.I)


def _escape_for_quote(target: str, quote: str) -> str:
    """Escapa target para insertar dentro de strings con la comilla dada."""
    out = target.replace("\\", "\\\\")
    out = out.replace(quote, "\\" + quote)
    out = out.replace("\n", "\\n").replace("\r", "")
    return out


def apply_file(file_path: Path, entries: list, do_backup: bool, dry_run: bool) -> dict:
    text = file_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    # Agrupar por linea
    by_line = defaultdict(list)
    for e in entries:
        by_line[e["line"]].append(e)

    stats = {"applied": 0, "skipped_empty": 0, "skipped_mismatch": 0, "skipped_asset": 0}

    for line_no in sorted(by_line.keys()):
        if line_no - 1 >= len(lines):
            continue
        original_line = lines[line_no - 1]
        # Strip newline para trabajar
        nl = ""
        if original_line.endswith("\r\n"):
            nl = "\r\n"; body = original_line[:-2]
        elif original_line.endswith("\n"):
            nl = "\n"; body = original_line[:-1]
        else:
            body = original_line

        # Ordenar entries por col_start DESCENDENTE
        ents = sorted(by_line[line_no], key=lambda x: x["col_start"], reverse=True)
        new_body = body
        for e in ents:
            target = e.get("target", "").strip()
            if not target:
                stats["skipped_empty"] += 1
                continue
            src = e["source"]
            cs, ce = e["col_start"], e["col_end"]
            extracted = new_body[cs:ce] if cs <= len(new_body) and ce <= len(new_body) else ""

            if e["kind"] in ("delete",) and ASSET_EXT_RE.search(target):
                stats["skipped_asset"] += 1
                continue

            if extracted == src:
                # Speaker: msg (sin comillas). Reemplazo directo.
                new_body = new_body[:cs] + target + new_body[ce:]
                stats["applied"] += 1
            elif extracted.startswith('"') and extracted.endswith('"'):
                inner_src = extracted[1:-1]
                if inner_src == src or _unescape(inner_src) == src:
                    new_body = new_body[:cs] + '"' + _escape_for_quote(target, '"') + '"' + new_body[ce:]
                    stats["applied"] += 1
                else:
                    stats["skipped_mismatch"] += 1
            elif extracted.startswith("'") and extracted.endswith("'"):
                inner_src = extracted[1:-1]
                if inner_src == src or _unescape(inner_src) == src:
                    new_body = new_body[:cs] + "'" + _escape_for_quote(target, "'") + "'" + new_body[ce:]
                    stats["applied"] += 1
                else:
                    stats["skipped_mismatch"] += 1
            else:
                stats["skipped_mismatch"] += 1

        lines[line_no - 1] = new_body + nl

    if not dry_run:
        if do_backup:
            bak = file_path.with_suffix(file_path.suffix + ".kps_bak")
            if not bak.exists():
                shutil.copy2(file_path, bak)
        file_path.write_text("".join(lines), encoding="utf-8")

    return stats


def _unescape(s: str) -> str:
    return s.replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl")
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    by_file = defaultdict(list)
    with open(args.jsonl, encoding="utf-8") as fh:
        for line in fh:
            e = json.loads(line)
            by_file[e["file"]].append(e)

    total = {"applied": 0, "skipped_empty": 0, "skipped_mismatch": 0, "skipped_asset": 0}
    for fp, ents in by_file.items():
        path = Path(fp)
        st = apply_file(path, ents, do_backup=not args.no_backup, dry_run=args.dry_run)
        print(f"[reinject] {path.name}: {st}", file=sys.stderr)
        for k in total:
            total[k] += st[k]
    print(f"[reinject] TOTAL: {total}", file=sys.stderr)


if __name__ == "__main__":
    main()
