from __future__ import annotations

import argparse
import ast
from pathlib import Path


def parse_old_value(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("old "):
        return None
    raw = stripped[4:].strip()
    if not (raw.startswith('"') and raw.endswith('"')):
        return None
    try:
        value = ast.literal_eval(raw)
    except Exception:
        return None
    return value if isinstance(value, str) else None


def block_start(lines: list[str], old_index: int) -> int:
    comment_index = old_index - 1
    if comment_index >= 0 and lines[comment_index].strip().startswith("# game/"):
        return comment_index
    return old_index


def block_end(lines: list[str], old_index: int) -> int:
    new_index = old_index + 1
    if new_index < len(lines) and lines[new_index].strip().startswith("new "):
        return new_index + 1
    return old_index + 1


def collect_duplicates(root: Path) -> tuple[dict[str, tuple[Path, int]], dict[Path, list[tuple[int, int, str]]]]:
    seen: dict[str, tuple[Path, int]] = {}
    removals: dict[Path, list[tuple[int, int, str]]] = {}

    for path in sorted(root.rglob("*.rpy")):
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines(keepends=True)
        for index, line in enumerate(lines):
            value = parse_old_value(line)
            if value is None:
                continue
            if value in seen:
                start = block_start(lines, index)
                end = block_end(lines, index)
                removals.setdefault(path, []).append((start, end, value))
            else:
                seen[value] = (path, index + 1)

    return seen, removals


def apply_removals(removals: dict[Path, list[tuple[int, int, str]]], dry: bool) -> int:
    removed = 0
    for path, spans in sorted(removals.items()):
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines(keepends=True)
        for start, end, value in sorted(spans, reverse=True):
            removed += 1
            rel = path.as_posix()
            print(f"remove {rel}:{start + 1}-{end} | {value[:90]!r}")
            if not dry:
                del lines[start:end]
        if not dry:
            path.write_text("".join(lines), encoding="utf-8")
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove duplicate Ren'Py string translation blocks by exact old value.")
    parser.add_argument("root", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    _, removals = collect_duplicates(args.root)
    count = sum(len(spans) for spans in removals.values())
    print(f"duplicate_blocks={count}")
    removed = apply_removals(removals, dry=not args.apply)
    if not args.apply:
        print("dry_run=1")
    else:
        print(f"removed={removed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())