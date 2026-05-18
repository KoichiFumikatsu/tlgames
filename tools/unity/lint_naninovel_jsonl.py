from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


PROTECTED_PATTERNS = {
    "tmp_tag": re.compile(r"<[^<>]+>"),
    "brace": re.compile(r"\{[^{}]+\}"),
    "var": re.compile(r"\[[^\[\]]+\]"),
    "pipe": re.compile(r"\|[A-Za-z0-9_]+\|"),
    "pct_named": re.compile(r"%\([a-zA-Z_][a-zA-Z0-9_]*\)[sdif]"),
    "pct": re.compile(r"%[0-9.]*[sdif]"),
}

SENTINEL_RE = re.compile(r"\bZ[GT]\d+Z?\b", re.IGNORECASE)
ASCII_WORD_RE = re.compile(r"[A-Za-z]{3,}")


def load_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                records.append({"__line__": line_no, "__json_error__": str(exc)})
                continue
            record["__line__"] = line_no
            records.append(record)
    return records


def tokens(pattern: re.Pattern[str], text: str) -> Counter[str]:
    return Counter(pattern.findall(text or ""))


def context(record: dict) -> str:
    return f"line={record.get('__line__')} script={record.get('script_path') or record.get('script_name') or ''} id={record.get('id')}"


def lint(records: list[dict]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    for record in records:
        if record.get("__json_error__"):
            errors.append(f"{context(record)} JSON parse error: {record['__json_error__']}")
            continue

        source = str(record.get("source") or "")
        target = str(record.get("target") or "")
        where = context(record)

        if source.strip() and not target.strip():
            errors.append(f"{where} empty target | source={source!r}")

        if "\n" in target or "\r" in target:
            errors.append(f"{where} physical newline in target")

        source_newlines = source.count("\\n")
        target_newlines = target.count("\\n")
        if source_newlines != target_newlines:
            errors.append(f"{where} literal \\n count mismatch source={source_newlines} target={target_newlines}")

        sentinels = SENTINEL_RE.findall(target)
        if sentinels:
            errors.append(f"{where} unresolved sentinel(s): {', '.join(sentinels)}")

        for name, pattern in PROTECTED_PATTERNS.items():
            source_tokens = tokens(pattern, source)
            target_tokens = tokens(pattern, target)
            if source_tokens != target_tokens:
                errors.append(
                    f"{where} {name} mismatch source={dict(source_tokens)} target={dict(target_tokens)}"
                )

        if source.strip() == target.strip() and ASCII_WORD_RE.search(source) and len(source.strip()) > 6:
            warnings.append(f"{where} unchanged target | {source!r}")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint translated Naninovel JSONL before bundle reinjection.")
    parser.add_argument("jsonl", type=Path)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--max-lines", type=int, default=200)
    args = parser.parse_args()

    records = load_jsonl(args.jsonl)
    errors, warnings = lint(records)

    lines = [
        f"file={args.jsonl}",
        f"records={len(records)}",
        f"errors={len(errors)}",
        f"warnings={len(warnings)}",
    ]
    if errors:
        lines.append("\n[errors]")
        lines.extend(errors[:args.max_lines])
    if warnings:
        lines.append("\n[warnings]")
        lines.extend(warnings[:args.max_lines])

    output = "\n".join(lines) + "\n"
    print(output, end="")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output, encoding="utf-8")

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())