#!/usr/bin/env python3
import argparse
import csv
import json
import re
from pathlib import Path


ASCII_RE = re.compile(rb"[\x20-\x7E]{4,}")
UTF16_RE = re.compile(rb"(?:[\x20-\x7E]\x00){4,}")

NOISE_SUBSTRINGS = (
    "unity",
    "shader",
    "mono",
    "vertex",
    "texture",
    "copyright",
    "mit license",
    "permission is hereby granted",
    "namespace",
    "dll",
    "system.",
    "microsoft.",
    "debug",
    "http://",
    "https://",
    "guid",
)


def iter_target_files(data_dir: Path):
    # Unity scene files are usually named level0, level1, etc.
    for p in sorted(data_dir.glob("level*")):
        if p.is_file():
            yield p

    patterns = ("*.assets", "*.resS", "*.resource")
    for pat in patterns:
        for p in sorted(data_dir.glob(pat)):
            if p.is_file():
                yield p


def extract_ascii(data: bytes, min_len: int):
    for m in ASCII_RE.finditer(data):
        raw = m.group(0)
        if len(raw) < min_len:
            continue
        yield m.start(), raw.decode("latin1", errors="ignore"), "ascii"


def extract_utf16le(data: bytes, min_len: int):
    for m in UTF16_RE.finditer(data):
        raw = m.group(0)
        decoded = raw.decode("utf-16le", errors="ignore")
        if len(decoded) < min_len:
            continue
        yield m.start(), decoded, "utf16le"


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def looks_translatable(text: str, min_words: int):
    s = normalize(text)
    if not s:
        return False

    letters = sum(ch.isalpha() for ch in s)
    printable = sum(32 <= ord(ch) <= 126 for ch in s)
    spaces = s.count(" ")
    words = len(s.split())

    if printable < max(4, int(len(s) * 0.75)):
        return False
    if letters < max(3, int(len(s) * 0.45)):
        return False
    if spaces < 1 or words < min_words:
        return False

    low = s.lower()
    for bad in NOISE_SUBSTRINGS:
        if bad in low:
            return False

    # Keep narrative-like lines and menu-like UI strings.
    has_sentence_marks = any(ch in s for ch in ".!?:")
    has_dialogue_shape = len(s) >= 12 and words >= min_words
    return has_sentence_marks or has_dialogue_shape


def main():
    parser = argparse.ArgumentParser(
        description="Extract static strings from Unity binary assets without runtime injection."
    )
    parser.add_argument("data_dir", help="Path to <Game>_Data directory")
    parser.add_argument("--out-dir", default=None, help="Output directory (default: <data_dir>/../_tl_work)")
    parser.add_argument("--min-len", type=int, default=6, help="Minimum string length")
    parser.add_argument("--min-words", type=int, default=2, help="Minimum word count for candidate filter")
    args = parser.parse_args()

    data_dir = Path(args.data_dir).resolve()
    if not data_dir.exists():
        raise SystemExit(f"Data dir not found: {data_dir}")

    if args.out_dir:
        out_dir = Path(args.out_dir).resolve()
    else:
        out_dir = (data_dir.parent / "_tl_work").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_jsonl = out_dir / "static_strings_raw.jsonl"
    cand_jsonl = out_dir / "static_strings_candidates.jsonl"
    cand_csv = out_dir / "static_strings_candidates.csv"

    seen = set()
    total = 0
    candidates = 0
    files = list(iter_target_files(data_dir))

    with raw_jsonl.open("w", encoding="utf-8", newline="") as f_raw, \
         cand_jsonl.open("w", encoding="utf-8", newline="") as f_cand, \
         cand_csv.open("w", encoding="utf-8", newline="") as f_csv:

        writer = csv.writer(f_csv)
        writer.writerow(["source_file", "offset", "encoding", "text"])

        for fp in files:
            data = fp.read_bytes()
            iterators = (
                extract_ascii(data, args.min_len),
                extract_utf16le(data, args.min_len),
            )

            for it in iterators:
                for offset, text, enc in it:
                    text = normalize(text)
                    if not text:
                        continue

                    # Deduplicate globally by exact text to reduce volume.
                    if text in seen:
                        continue
                    seen.add(text)

                    rec = {
                        "source_file": fp.name,
                        "offset": offset,
                        "encoding": enc,
                        "text": text,
                    }
                    f_raw.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    total += 1

                    if looks_translatable(text, args.min_words):
                        f_cand.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        writer.writerow([fp.name, offset, enc, text])
                        candidates += 1

    print(f"files_scanned={len(files)}")
    print(f"raw_unique_strings={total}")
    print(f"candidate_strings={candidates}")
    print(f"raw_jsonl={raw_jsonl}")
    print(f"candidate_jsonl={cand_jsonl}")
    print(f"candidate_csv={cand_csv}")


if __name__ == "__main__":
    main()
