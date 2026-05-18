#!/usr/bin/env python3
"""Apply translated JSONL targets to Pokemon Essentials MessageTypes .dat files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rubymarshal.reader import load
from rubymarshal.writer import write


def load_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def ruby_text(value: object) -> str | None:
    text = getattr(value, "text", None)
    return text if isinstance(text, str) else None


def build_translation_map(records: list[dict]) -> dict[tuple[int, int, str], str]:
    translations: dict[tuple[int, int, str], str] = {}
    for record in records:
        target = str(record.get("target", "")).strip()
        source = str(record.get("source", ""))
        if not source or not target:
            continue
        key = (int(record["group_index"]), int(record["hash_index"]), source)
        translations[key] = target
    return translations


def apply(input_dat: Path, translated_jsonl: Path, out_dat: Path, report_path: Path) -> int:
    records = load_jsonl(translated_jsonl)
    translations = build_translation_map(records)

    with input_dat.open("rb") as handle:
        obj = load(handle)

    changed = 0
    missing = 0
    total_pairs = 0
    if isinstance(obj, list):
        for group_index, group in enumerate(obj):
            if not isinstance(group, list):
                continue
            for hash_index, item in enumerate(group):
                if not isinstance(item, dict):
                    continue
                for source_obj, target_obj in item.items():
                    source = ruby_text(source_obj)
                    target = ruby_text(target_obj)
                    if source is None or target is None:
                        continue
                    total_pairs += 1
                    key = (group_index, hash_index, source)
                    new_target = translations.get(key)
                    if new_target is None:
                        missing += 1
                        continue
                    if new_target != target:
                        target_obj.text = new_target
                        changed += 1

    out_dat.parent.mkdir(parents=True, exist_ok=True)
    with out_dat.open("wb") as handle:
        write(handle, obj)

    report = {
        "input_dat": str(input_dat),
        "translated_jsonl": str(translated_jsonl),
        "out_dat": str(out_dat),
        "records": len(records),
        "translations": len(translations),
        "total_pairs": total_pairs,
        "changed": changed,
        "missing_pairs_without_target": missing,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"records={report['records']}")
    print(f"translations={report['translations']}")
    print(f"total_pairs={total_pairs}")
    print(f"changed={changed}")
    print(f"out={out_dat}")
    print(f"report={report_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply Pokemon Essentials message .dat translations")
    parser.add_argument("input_dat", type=Path)
    parser.add_argument("translated_jsonl", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    return apply(args.input_dat, args.translated_jsonl, args.out, args.report)


if __name__ == "__main__":
    raise SystemExit(main())