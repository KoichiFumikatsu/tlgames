#!/usr/bin/env python3
"""
Translate pending strings from static_strings_pending.jsonl using DeepL.
Merges results back into main translated corpus.
"""
import argparse
import json
import os
import sys
from pathlib import Path

TL_ROOT = Path(__file__).resolve().parents[1] / "tl"
sys.path.insert(0, str(TL_ROOT))

import translate as tl_translate
from _env import load_env

load_env()


def load_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def translate_pending_deepl(pending_path: Path, output_path: Path, main_corpus_path: Path):
    """Translate pending records using DeepL and merge back to main corpus."""
    
    api_key = os.environ.get("DEEPL_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("DEEPL_API_KEY not set in environment")
    
    # Load pending records
    pending = list(load_jsonl(pending_path))
    print(f"pending_records={len(pending)}")
    
    if not pending:
        print("Nothing to translate")
        return 0
    
    # Extract sources
    sources = [rec["source"] for rec in pending]
    
    # Translate via DeepL (one at a time, as there's no batch function)
    print(f"Translating {len(sources)} strings via DeepL...")
    cache = tl_translate.load_cache("deepl")
    
    translations = []
    for i, src in enumerate(sources):
        try:
            tr = tl_translate.deepl_translate(src, cache, api_key)
            translations.append(tr)
            if (i + 1) % 50 == 0:
                print(f"  progress={i+1}/{len(sources)}", flush=True)
        except Exception as e:
            print(f"[WARN] Translation failed at {i}: {e}", file=sys.stderr)
            translations.append(src)  # fallback to source
    
    tl_translate.save_cache(cache, "deepl")
    
    # Update pending records with translations
    for rec, tr in zip(pending, translations):
        rec["target"] = tr.replace("\r\n", "\\n").replace("\n", "\\n") if tr else ""
    
    print(f"translated={len([r for r in pending if r.get('target', '').strip()])}")
    
    # Load main corpus and merge
    main_records = list(load_jsonl(main_corpus_path))
    
    # Build lookup of (bundle, id) -> translated result
    translated_map = {
        (rec["bundle"], rec["id"]): rec["target"]
        for rec in pending
    }
    
    # Merge back
    merged = 0
    for rec in main_records:
        key = (rec["bundle"], rec["id"])
        if key in translated_map:
            rec["target"] = translated_map[key]
            merged += 1
    
    print(f"merged={merged}")
    
    # Write merged output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for rec in main_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    
    print(f"output={output_path}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Translate pending Hypno Academy strings via DeepL"
    )
    parser.add_argument(
        "pending_jsonl",
        help="Path to pending strings (static_strings_pending.jsonl)"
    )
    parser.add_argument(
        "--main-corpus",
        required=True,
        help="Path to main translated corpus"
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Output path for merged corpus"
    )
    args = parser.parse_args()
    
    pending_path = Path(args.pending_jsonl).resolve()
    main_path = Path(args.main_corpus).resolve()
    output_path = Path(args.out).resolve()
    
    if not pending_path.exists():
        raise SystemExit(f"Pending file not found: {pending_path}")
    if not main_path.exists():
        raise SystemExit(f"Main corpus not found: {main_path}")
    
    return translate_pending_deepl(pending_path, output_path, main_path)


if __name__ == "__main__":
    sys.exit(main())
