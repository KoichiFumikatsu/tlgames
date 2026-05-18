#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


def load_jsonl(path: Path):
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def fix_common_issues(text: str) -> str:
    """Apply common post-MT fixes for Spanish from English MT output."""
    if not text:
        return text

    # Fix: "I no X" → remove stray English "I"
    text = re.sub(r"\bI\s+no\s+", "no ", text, flags=re.IGNORECASE)

    # Fix: "creepy" left untranslated in some contexts
    text = re.sub(r"\bcreepy\b", "asqueroso/a", text, flags=re.IGNORECASE)

    # Fix: "Piggy-boy" / common misspellings
    text = re.sub(r"\bPiggy[- ]boy\b", "Cerdo-chico", text, flags=re.IGNORECASE)
    text = re.sub(r"\bBobby[- ]boy\b", "Bobby", text)

    # Fix: Double spaces
    text = re.sub(r"\s+", " ", text)

    # Fix: Broken HTML-like tags (edge case)
    text = re.sub(r"\{s\s*\}", "{s}", text)
    text = re.sub(r"\{/s\s*\}", "{/s}", text)

    return text.strip()


def main():
    parser = argparse.ArgumentParser(
        description="Clean up common post-MT issues in static extraction corpus."
    )
    parser.add_argument("input_jsonl", help="Translated JSONL corpus")
    parser.add_argument("--out", default="", help="Output JSONL path")
    args = parser.parse_args()

    input_path = Path(args.input_jsonl).resolve()
    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")

    out_path = Path(args.out).resolve() if args.out else input_path.with_name(
        input_path.stem + ".cleaned.jsonl"
    )

    total = 0
    changed = 0
    with out_path.open("w", encoding="utf-8", newline="") as out:
        for rec in load_jsonl(input_path):
            total += 1
            original = rec.get("target", "").strip()
            fixed = fix_common_issues(original)
            if fixed != original:
                changed += 1
            rec["target"] = fixed
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"input={input_path}")
    print(f"output={out_path}")
    print(f"records={total} modified={changed}")


if __name__ == "__main__":
    main()
