#!/usr/bin/env python3
"""Export Unity JSONL translations to XUnity AutoTranslator static format."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


WORD_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ'’-]*")
VOWEL_RE = re.compile(r"[AEIOUaeiouÁÉÍÓÚÜáéíóúü]")
COMMON_ENGLISH_WORDS = {
    "a", "about", "after", "all", "am", "an", "and", "are", "as", "at", "be", "been",
    "but", "by", "can", "come", "do", "does", "for", "from", "get", "go", "got", "had",
    "has", "have", "he", "her", "here", "him", "his", "how", "i", "if", "in", "into", "is",
    "it", "its", "just", "like", "me", "my", "no", "not", "of", "on", "one", "or", "our",
    "out", "she", "so", "that", "the", "their", "them", "then", "there", "they", "this",
    "to", "up", "was", "we", "were", "what", "when", "where", "which", "who", "why", "will",
    "with", "would", "you", "your", "you're", "i'm", "don't", "can't", "won't", "it's",
}


def load_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def xunity_escape(text: str) -> str:
    return text.replace("\r\n", "\\n").replace("\n", "\\n").strip()


def reject_reason(source: str, target: str, max_len: int) -> str | None:
    source = source.strip()
    target = target.strip()
    if not source:
        return "empty_source"
    if not target:
        return "empty_target"
    if source == target:
        return "unchanged"
    if len(source) > max_len:
        return "too_long"
    if "=" in source:
        return "source_has_equals"
    if "\x00" in source or "\x00" in target:
        return "nul_byte"

    words = WORD_RE.findall(source)
    alpha_count = sum(ch.isalpha() for ch in source)
    alnum_count = sum(ch.isalnum() for ch in source)
    symbol_count = sum((not ch.isalnum()) and (not ch.isspace()) for ch in source)
    whitespace_count = sum(ch.isspace() for ch in source)
    length = max(len(source), 1)

    if len(source) > 80 and whitespace_count == 0:
        return "long_no_spaces"
    if len(source) > 20 and len(words) < 2:
        return "too_few_words"
    if len(source) > 30 and whitespace_count == 0:
        return "medium_no_spaces"
    if len(source) > 120 and symbol_count / length > 0.35:
        return "symbol_heavy"
    if len(source) > 40 and symbol_count / length > 0.30:
        return "symbol_heavy"
    if len(source) > 120 and alnum_count / length < 0.55:
        return "low_alnum"
    if len(source) > 60 and alpha_count / length < 0.35:
        return "low_alpha"

    if len(source) > 40:
        vowel_words = [word for word in words if VOWEL_RE.search(word)]
        if len(vowel_words) < 2:
            return "not_language_like"
        common_words = [word for word in words if word.lower() in COMMON_ENGLISH_WORDS]
        if not common_words:
            return "no_common_english_word"
        average_word_length = sum(len(word) for word in words) / max(len(words), 1)
        if average_word_length > 14:
            return "word_runs"
    if re.search(r"(.)\1{6,}", source):
        return "repeated_char_run"

    if len(source) > 100:
        trigrams = [source[index : index + 3] for index in range(len(source) - 2)]
        most_common = Counter(trigrams).most_common(1)
        if most_common and most_common[0][1] >= 12:
            return "repeated_binary_pattern"

    return None


def export(corpus_path: Path, out_path: Path, report_path: Path, max_len: int) -> int:
    records = load_jsonl(corpus_path)
    exported: dict[str, str] = {}
    skipped: Counter[str] = Counter()
    skipped_samples: dict[str, list[dict]] = {}
    duplicates = 0

    for record in records:
        source = str(record.get("source", ""))
        target = str(record.get("target", ""))
        reason = reject_reason(source, target, max_len=max_len)
        if reason:
            skipped[reason] += 1
            skipped_samples.setdefault(reason, [])
            if len(skipped_samples[reason]) < 10:
                skipped_samples[reason].append(
                    {
                        "source": source[:240],
                        "target": target[:240],
                        "source_length": len(source),
                    }
                )
            continue

        source_key = xunity_escape(source)
        target_value = xunity_escape(target)
        if source_key in exported and exported[source_key] != target_value:
            duplicates += 1
            continue
        exported[source_key] = target_value

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("# Generated from Hypno Academy static string corpus.\n")
        handle.write("# Format: English=Spanish\n")
        for source, target in sorted(exported.items(), key=lambda item: item[0].lower()):
            handle.write(f"{source}={target}\n")

    report = {
        "input": str(corpus_path),
        "output": str(out_path),
        "total_records": len(records),
        "exported_unique": len(exported),
        "duplicates_conflicting_skipped": duplicates,
        "skipped": dict(skipped),
        "skipped_samples": skipped_samples,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"records={len(records)}")
    print(f"exported_unique={len(exported)}")
    print(f"duplicates_conflicting_skipped={duplicates}")
    for reason, count in skipped.most_common():
        print(f"skipped_{reason}={count}")
    print(f"out={out_path}")
    print(f"report={report_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Export JSONL translations to XUnity static format")
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--max-len", type=int, default=1000)
    args = parser.parse_args()

    return export(args.corpus, args.out, args.report, args.max_len)


if __name__ == "__main__":
    raise SystemExit(main())