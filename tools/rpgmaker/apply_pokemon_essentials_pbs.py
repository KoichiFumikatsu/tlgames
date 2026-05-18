#!/usr/bin/env python3
"""Apply translated Pokemon Essentials PBS JSONL to a copied PBS tree."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def build_translation_map(records: list[dict]) -> dict[tuple[str, int, str], str]:
    translations: dict[tuple[str, int, str], str] = {}
    for record in records:
        target = str(record.get("target", "")).strip()
        if not target:
            continue
        source_file = str(record.get("source_file", ""))
        line = int(record.get("line", 0))
        field = str(record.get("field", ""))
        translations[(source_file, line, field)] = target.replace("\r\n", "\\n").replace("\n", "\\n")
    return translations


def apply_file(source_path: Path, relative: Path, out_path: Path, translations: dict[tuple[str, int, str], str]) -> int:
    changed = 0
    lines = source_path.read_text(encoding="utf-8-sig", errors="replace").splitlines(keepends=True)
    out_lines: list[str] = []
    relative_key = relative.as_posix()

    for line_number, raw_line in enumerate(lines, start=1):
        line_ending = ""
        body = raw_line
        if raw_line.endswith("\r\n"):
            body = raw_line[:-2]
            line_ending = "\r\n"
        elif raw_line.endswith("\n"):
            body = raw_line[:-1]
            line_ending = "\n"

        if "=" not in body:
            out_lines.append(raw_line)
            continue
        key, value = body.split("=", 1)
        field = key.strip()
        target = translations.get((relative_key, line_number, field))
        if target is None:
            out_lines.append(raw_line)
            continue
        prefix = body[: body.index("=") + 1]
        spacing = " " if value.startswith(" ") else ""
        out_lines.append(f"{prefix}{spacing}{target}{line_ending}")
        changed += 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(out_lines), encoding="utf-8", newline="")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply translated PBS JSONL to a new PBS folder")
    parser.add_argument("translated_jsonl", type=Path)
    parser.add_argument("--pbs-root", type=Path, required=True)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    records = load_jsonl(args.translated_jsonl)
    translations = build_translation_map(records)
    changed_total = 0
    copied_files = 0
    changed_files = 0

    pbs_root = args.pbs_root.resolve()
    out_root = args.out_root.resolve()
    for source_path in sorted(pbs_root.rglob("*.txt")):
        relative = source_path.relative_to(pbs_root)
        out_path = out_root / relative
        changed = apply_file(source_path, relative, out_path, translations)
        copied_files += 1
        changed_total += changed
        if changed:
            changed_files += 1

    report = {
        "translated_jsonl": str(args.translated_jsonl),
        "pbs_root": str(pbs_root),
        "out_root": str(out_root),
        "records": len(records),
        "translations": len(translations),
        "copied_files": copied_files,
        "changed_files": changed_files,
        "changed_lines": changed_total,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"records={len(records)}")
    print(f"translations={len(translations)}")
    print(f"copied_files={copied_files}")
    print(f"changed_files={changed_files}")
    print(f"changed_lines={changed_total}")
    print(f"out_root={out_root}")
    print(f"report={args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())