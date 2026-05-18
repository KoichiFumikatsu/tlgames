#!/usr/bin/env python3
"""Lint translated RPG Maker JSONL corpora."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


CONTROL_RE = re.compile(r"\\[A-Za-z]+\[[^\]]+\]|\\[A-Za-z]+|#\{[^{}]+\}|%\([a-zA-Z_][a-zA-Z0-9_]*\)[sdif]|%[0-9.]*[sdif]")
SENTINEL_RE = re.compile(r"\bZ[GT]\d{3}Z\b", re.IGNORECASE)


def load_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def controls(text: str) -> list[str]:
    return CONTROL_RE.findall(text)


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint RPG Maker translated JSONL")
    parser.add_argument("jsonl", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    records = load_jsonl(args.jsonl)
    issues: list[dict] = []
    counts: Counter[str] = Counter()

    for index, record in enumerate(records):
        source = str(record.get("source", ""))
        target = str(record.get("target", ""))
        if source.strip() and not target.strip():
            counts["EMPTY"] += 1
            issues.append({"index": index, "code": "EMPTY", "id": record.get("id"), "source": source})
            continue
        if SENTINEL_RE.search(target):
            counts["SENTINEL"] += 1
            issues.append({"index": index, "code": "SENTINEL", "id": record.get("id"), "target": target})
        if controls(source) != controls(target):
            counts["CONTROL"] += 1
            issues.append({"index": index, "code": "CONTROL", "id": record.get("id"), "source": source, "target": target})
        if len(source) >= 20 and len(target) > max(80, int(len(source) * 1.8)):
            counts["EXPAND"] += 1
            issues.append({"index": index, "code": "EXPAND", "id": record.get("id"), "source": source, "target": target})

    report = {
        "input": str(args.jsonl),
        "records": len(records),
        "counts": dict(counts),
        "issues": issues[:500],
        "truncated_issues": max(0, len(issues) - 500),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"records={len(records)}")
    for code, count in counts.most_common():
        print(f"{code}={count}")
    print(f"issues={len(issues)}")
    print(f"report={args.report}")
    return 1 if counts.get("EMPTY") or counts.get("SENTINEL") or counts.get("CONTROL") else 0


if __name__ == "__main__":
    raise SystemExit(main())