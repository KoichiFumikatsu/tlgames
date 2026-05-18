#!/usr/bin/env python3
"""Extract Pokemon Essentials MessageTypes .dat files to JSONL."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from rubymarshal.reader import load


def ruby_text(value: object) -> str | None:
    text = getattr(value, "text", None)
    return text if isinstance(text, str) else None


def iter_message_pairs(obj: object):
    if not isinstance(obj, list):
        return
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
                yield group_index, hash_index, source, target


def extract(input_dat: Path, out_jsonl: Path, report_path: Path) -> int:
    with input_dat.open("rb") as handle:
        obj = load(handle)

    records = []
    for index, (group_index, hash_index, source, target) in enumerate(iter_message_pairs(obj)):
        records.append(
            {
                "engine": "rpgmaker_xp_pokemon_essentials",
                "format": "message_types_dat",
                "bundle": input_dat.name,
                "id": f"{input_dat.name}:{group_index}:{hash_index}:{index}",
                "source_file": input_dat.name,
                "group_index": group_index,
                "hash_index": hash_index,
                "source": source,
                "target": "" if source == target else target,
                "current_target": target,
            }
        )

    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with out_jsonl.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    by_hash = Counter((record["group_index"], record["hash_index"]) for record in records)
    report = {
        "input": str(input_dat),
        "records": len(records),
        "pending": sum(1 for record in records if not record["target"]),
        "already_translated": sum(1 for record in records if record["target"]),
        "by_hash": {f"{key[0]}:{key[1]}": value for key, value in by_hash.most_common()},
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"input={input_dat}")
    print(f"records={report['records']}")
    print(f"pending={report['pending']}")
    print(f"already_translated={report['already_translated']}")
    print(f"out={out_jsonl}")
    print(f"report={report_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract Pokemon Essentials message .dat strings")
    parser.add_argument("input_dat", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    return extract(args.input_dat, args.out, args.report)


if __name__ == "__main__":
    raise SystemExit(main())