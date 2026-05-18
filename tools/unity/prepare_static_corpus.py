#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def load_jsonl(path: Path):
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def main():
    parser = argparse.ArgumentParser(description="Normalize static Unity string candidates to source/target corpus JSONL.")
    parser.add_argument("input_jsonl", help="Input JSONL with source_file/offset/text fields")
    parser.add_argument("--out", default="", help="Output corpus JSONL path")
    args = parser.parse_args()

    input_path = Path(args.input_jsonl).resolve()
    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")

    out_path = Path(args.out).resolve() if args.out else input_path.with_name("static_strings_corpus.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    seen = set()
    total = 0
    written = 0
    with out_path.open("w", encoding="utf-8", newline="") as out:
        for rec in load_jsonl(input_path):
            total += 1
            source_file = str(rec.get("source_file", "")).strip()
            offset = int(rec.get("offset", 0) or 0)
            source = str(rec.get("text", "")).strip()
            if not source:
                continue

            key = (source_file, offset, source)
            if key in seen:
                continue
            seen.add(key)

            row = {
                "bundle": source_file,
                "id": str(offset),
                "index": written,
                "source": source,
                "target": "",
                "encoding": rec.get("encoding", ""),
            }
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            written += 1

    print(f"input={input_path}")
    print(f"output={out_path}")
    print(f"records_in={total}")
    print(f"records_out={written}")


if __name__ == "__main__":
    main()
