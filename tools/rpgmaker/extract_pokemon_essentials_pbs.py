#!/usr/bin/env python3
"""Extract translatable Pokemon Essentials PBS fields to JSONL."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


TEXT_FIELDS = {
    "Description",
    "Pokedex",
    "BeginSpeech",
    "EndSpeechWin",
    "EndSpeechLose",
    "LoseText",
}

NAME_FIELDS_BY_FILE = {
    "abilities.txt": {"Name"},
    "items.txt": {"Name", "NamePlural", "PortionName", "PortionNamePlural"},
    "moves.txt": {"Name"},
    "trainer_types.txt": {"Name"},
    "types.txt": {"Name"},
    "pokemon_forms.txt": {"FormName"},
}

SKIP_DIR_NAMES = {
    "backup",
    "backups",
    "gen 1 backup",
    "gen 2 backup",
    "gen 3 backup",
    "gen 4 backup",
    "gen 5 backup",
    "gen 6 backup",
    "gen 7 backup",
    "gen 8 backup",
    "gen 9 backup",
    "shadow pokemon backup",
}

INLINE_COMMENT_RE = re.compile(r"\s+#.*$")


def is_backup_path(path: Path, root: Path) -> bool:
    relative_parts = [part.lower() for part in path.relative_to(root).parts[:-1]]
    return any(part in SKIP_DIR_NAMES or "backup" in part for part in relative_parts)


def is_translatable_field(file_name: str, key: str) -> bool:
    if key in TEXT_FIELDS:
        return True
    return key in NAME_FIELDS_BY_FILE.get(file_name.lower(), set())


def looks_textual(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    if len(text) <= 1:
        return False
    if re.fullmatch(r"[A-Z0-9_., -]+", text) and " " not in text:
        return False
    if not re.search(r"[A-Za-z]", text):
        return False
    return True


def parse_pbs_file(path: Path, root: Path) -> list[dict]:
    records: list[dict] = []
    current_section = ""
    relative = path.relative_to(root).as_posix()
    file_name = path.name.lower()

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig", errors="replace").splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            current_section = stripped[1:-1].strip()
            continue
        if "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        key = key.strip()
        value = INLINE_COMMENT_RE.sub("", value).strip()
        if not is_translatable_field(file_name, key):
            continue
        if not looks_textual(value):
            continue
        records.append(
            {
                "engine": "rpgmaker_xp_pokemon_essentials",
                "format": "pbs",
                "bundle": relative,
                "id": f"{relative}:{line_number}:{current_section}:{key}",
                "source_file": relative,
                "line": line_number,
                "section": current_section,
                "field": key,
                "source": value,
                "target": "",
            }
        )
    return records


def extract(root: Path, out_jsonl: Path, report_path: Path) -> int:
    root = root.resolve()
    records: list[dict] = []
    scanned_files = 0
    skipped_backup_files = 0

    for path in sorted(root.rglob("*.txt")):
        if is_backup_path(path, root):
            skipped_backup_files += 1
            continue
        scanned_files += 1
        records.extend(parse_pbs_file(path, root))

    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with out_jsonl.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    by_file = Counter(record["source_file"] for record in records)
    by_field = Counter(record["field"] for record in records)
    report = {
        "root": str(root),
        "scanned_files": scanned_files,
        "skipped_backup_files": skipped_backup_files,
        "records": len(records),
        "chars": sum(len(record["source"]) for record in records),
        "by_file": dict(by_file.most_common()),
        "by_field": dict(by_field.most_common()),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"root={root}")
    print(f"scanned_files={scanned_files}")
    print(f"skipped_backup_files={skipped_backup_files}")
    print(f"records={len(records)}")
    print(f"chars={report['chars']}")
    print(f"out={out_jsonl}")
    print(f"report={report_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract Pokemon Essentials PBS translatable fields")
    parser.add_argument("pbs_root", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    return extract(args.pbs_root, args.out, args.report)


if __name__ == "__main__":
    raise SystemExit(main())