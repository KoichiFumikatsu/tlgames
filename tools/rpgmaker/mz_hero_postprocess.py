#!/usr/bin/env python3
"""Postprocess Hero MZ translated JSONL before lint/apply."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


SENTINEL_RE = re.compile(r"\bZT\d{3}Z\b", re.IGNORECASE)


def load_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Postprocess Hero translated MZ JSONL")
    parser.add_argument("jsonl", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    records = load_jsonl(args.jsonl)
    counts: Counter[str] = Counter()
    examples: list[dict] = []

    for record in records:
        source = str(record.get("source", ""))
        target = str(record.get("target", ""))
        original_target = target

        if "\n" in source and "\\n" in target:
            target = target.replace("\\n", "\n")
            counts["restored_newlines"] += 1

        if SENTINEL_RE.search(target):
            target = source
            counts["sentinel_reverted_to_source"] += 1

        if target != original_target:
            record["target"] = target
            if len(examples) < 25:
                examples.append(
                    {
                        "id": record.get("id"),
                        "source": source,
                        "before": original_target,
                        "after": target,
                    }
                )

    report = {
        "input": str(args.jsonl),
        "dry_run": args.dry_run,
        "records": len(records),
        "counts": dict(counts),
        "examples": examples,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.dry_run:
        write_jsonl(args.jsonl, records)

    print(f"records={len(records)}")
    for key, value in counts.most_common():
        print(f"{key}={value}")
    print(f"report={args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())