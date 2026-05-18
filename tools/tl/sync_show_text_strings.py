#!/usr/bin/env python3
"""Sync missing `show text` strings from source .rpy files into tl/<lang> files.

This solves a Ren'Py gap where some inline show-text literals are not present in
translation files. For each missing string, this script appends an entry in the
`translate <lang> strings:` block as:

    # game/path/file.rpy:123
    old "..."
    new ""

Usage:
    python tools/tl/sync_show_text_strings.py "proyects Game TL/Maeves Academy Witcher/game" --lang spanish
    python tools/tl/sync_show_text_strings.py ".../game" --lang spanish --fill-with-source
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

SHOW_TEXT_RE = re.compile(r'show\s+text\s+"((?:[^"\\]|\\.)*)"')
OLD_LINE_RE = re.compile(r'^\s*old\s+"((?:[^"\\]|\\.)*)"\s*$')
STRINGS_BLOCK_RE_TEMPLATE = r'(?ms)^translate\s+{lang}\s+strings:\s*\n'


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sync missing show-text strings into tl files")
    p.add_argument("game_root", help="Path to game root (contains .rpy and tl/)")
    p.add_argument("--lang", default="spanish", help="Ren'Py tl language folder (default: spanish)")
    p.add_argument(
        "--fill-with-source",
        action="store_true",
        help="Set new text equal to old text instead of empty string",
    )
    p.add_argument("--dry-run", action="store_true", help="Report only; do not write files")
    return p.parse_args()


def unescape_rpy_string(s: str) -> str:
    # Strings already come from source with escapes preserved; keep as-is.
    return s


def escape_rpy_string(s: str) -> str:
    # Escape backslashes first, then quotes.
    return s.replace("\\", "\\\\").replace('"', '\\"')


def collect_show_text_strings(game_root: Path) -> Dict[str, List[Tuple[int, str]]]:
    out: Dict[str, List[Tuple[int, str]]] = {}
    for src in sorted(game_root.rglob("*.rpy")):
        rel = src.relative_to(game_root).as_posix()
        if rel.startswith("tl/"):
            continue

        text = src.read_text(encoding="utf-8", errors="ignore")
        items: List[Tuple[int, str]] = []
        seen: Set[str] = set()
        for m in SHOW_TEXT_RE.finditer(text):
            line_no = text.count("\n", 0, m.start()) + 1
            raw = unescape_rpy_string(m.group(1))
            # Deduplicate per source file by exact old string.
            if raw in seen:
                continue
            seen.add(raw)
            items.append((line_no, raw))

        if items:
            out[rel] = items
    return out


def extract_existing_old_strings(tl_text: str) -> Set[str]:
    existing: Set[str] = set()
    for line in tl_text.splitlines():
        m = OLD_LINE_RE.match(line)
        if m:
            existing.add(m.group(1))
    return existing


def append_entries(
    tl_path: Path,
    source_rel: str,
    entries: List[Tuple[int, str]],
    lang: str,
    fill_with_source: bool,
    dry_run: bool,
) -> int:
    if tl_path.exists():
        tl_text = tl_path.read_text(encoding="utf-8", errors="ignore")
    else:
        tl_text = ""

    existing_old = extract_existing_old_strings(tl_text)
    missing = [(ln, s) for (ln, s) in entries if s not in existing_old]
    if not missing:
        return 0

    strings_block_re = re.compile(STRINGS_BLOCK_RE_TEMPLATE.format(lang=re.escape(lang)))
    has_strings_block = bool(strings_block_re.search(tl_text))

    lines_to_add: List[str] = []
    if has_strings_block:
        lines_to_add.append("")
    else:
        if tl_text and not tl_text.endswith("\n"):
            tl_text += "\n"
        lines_to_add.extend(["", f"translate {lang} strings:", ""])

    for line_no, old in missing:
        escaped_old = escape_rpy_string(old)
        new_value = escaped_old if fill_with_source else ""
        lines_to_add.extend(
            [
                f"    # game/{source_rel}:{line_no}",
                f"    old \"{escaped_old}\"",
                f"    new \"{new_value}\"",
                "",
            ]
        )

    if dry_run:
        return len(missing)

    tl_path.parent.mkdir(parents=True, exist_ok=True)
    with tl_path.open("a", encoding="utf-8", newline="\n") as f:
        # If file is empty and we created a new strings block, avoid leading blank lines.
        block = "\n".join(lines_to_add)
        if not tl_text:
            block = block.lstrip("\n")
        f.write(block)

    return len(missing)


def main() -> int:
    args = parse_args()
    game_root = Path(args.game_root)
    tl_root = game_root / "tl" / args.lang

    if not game_root.exists():
        raise SystemExit(f"game_root not found: {game_root}")

    show_text_map = collect_show_text_strings(game_root)

    touched_files = 0
    inserted_total = 0
    for source_rel, entries in show_text_map.items():
        tl_path = tl_root / source_rel
        inserted = append_entries(
            tl_path=tl_path,
            source_rel=source_rel,
            entries=entries,
            lang=args.lang,
            fill_with_source=args.fill_with_source,
            dry_run=args.dry_run,
        )
        if inserted:
            touched_files += 1
            inserted_total += inserted
            print(f"{source_rel}: +{inserted}")

    print("---")
    print(f"source files with show text: {len(show_text_map)}")
    print(f"tl files touched: {touched_files}")
    print(f"entries inserted: {inserted_total}")
    print(f"mode: {'dry-run' if args.dry_run else 'write'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
