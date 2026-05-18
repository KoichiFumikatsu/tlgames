#!/usr/bin/env python3
"""
Simple fallback translator for static corpus using OpenAI.
Handles timeouts gracefully by translating one batch at a time with retries.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent / "tl"
sys.path.insert(0, str(ROOT))
from _env import load_env
load_env()

import translate as tl_translate
from lib_rpy import tokenize, detokenize


def load_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def save_record(path: Path, rec: dict, mode="a"):
    with path.open(mode, encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def translate_batch_with_retries(sources: list, cache: dict, api_key: str, model: str, max_retries=3):
    """Translate batch with exponential backoff on timeout."""
    # Tokenize
    prepared = []
    metas = []
    for src in sources:
        if not src.strip():
            prepared.append(src)
            metas.append({})
            continue
        tok_str, tok_map = tokenize(src)
        prepared.append(tok_str)
        metas.append(tok_map)
    
    for attempt in range(max_retries):
        try:
            translated_tokenized = tl_translate.openai_translate_batch(prepared, cache, api_key, model)
            
            results = []
            for i, tr_tok in enumerate(translated_tokenized):
                if tr_tok is None:
                    results.append(sources[i])
                else:
                    detok = detokenize(tr_tok, metas[i])
                    results.append(detok)
            return results
        except tl_translate.BatchSizeMismatch as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"  [retry {attempt+1}] BatchSizeMismatch: {e}. Waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
            else:
                raise
        except TimeoutError as e:
            if attempt < max_retries - 1:
                wait = 5 * (2 ** attempt)
                print(f"  [retry {attempt+1}] Timeout. Waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
            else:
                raise


def main():
    parser = argparse.ArgumentParser(
        description="Simple OpenAI translator for static corpus with retry logic."
    )
    parser.add_argument("input_jsonl", help="Input corpus JSONL")
    parser.add_argument("--out", required=True, help="Output JSONL path")
    parser.add_argument("--batch-size", type=int, default=5, help="Batch size per request")
    parser.add_argument("--budget", type=float, default=2.50, help="Budget USD")
    args = parser.parse_args()

    input_path = Path(args.input_jsonl).resolve()
    output_path = Path(args.out).resolve()
    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY not set")

    # Load cache
    cache_file = Path(__file__).parent.parent / "tl" / ".cache" / "openai_usage.json"
    cache = {}
    if cache_file.exists():
        with cache_file.open("r") as f:
            cache = json.load(f)

    # Load existing translations
    existing = {}
    if output_path.exists():
        for rec in load_jsonl(output_path):
            key = (rec["bundle"], rec["id"])
            existing[key] = rec
        print(f"Loaded {len(existing)} existing translations")

    # Load input corpus
    records = list(load_jsonl(input_path))
    print(f"Total records: {len(records)}")

    # Separate into pending and existing
    pending = []
    for rec in records:
        key = (rec["bundle"], rec["id"])
        if key not in existing or not existing[key].get("target"):
            pending.append(rec)

    print(f"Pending: {len(pending)}")
    if not pending:
        print("Nothing to translate")
        return 0

    # Translate in batches
    total_cost = cache.get("total_cost", 0)
    budget = args.budget
    translated_count = 0

    for i in range(0, len(pending), args.batch_size):
        batch = pending[i : i + args.batch_size]
        sources = [rec["source"] for rec in batch]

        try:
            targets = translate_batch_with_retries(sources, cache, api_key, "gpt-4.1-nano")
            
            for rec, target in zip(batch, targets):
                rec["target"] = target
                key = (rec["bundle"], rec["id"])
                existing[key] = rec
                translated_count += 1

            # Update cost
            total_cost = cache.get("total_cost", 0)
            if total_cost > budget:
                print(f"Budget exceeded: ${total_cost:.4f} > ${budget:.2f}")
                break

            # Show progress every N batches
            if (i // args.batch_size + 1) % 10 == 0:
                print(f"progress={translated_count}/{len(pending)} cost=${total_cost:.4f} / ${budget:.2f}")

        except (TimeoutError, tl_translate.BatchSizeMismatch) as e:
            print(f"Failed on batch starting at {i}: {e}", file=sys.stderr)
            break

    # Write output
    with output_path.open("w", encoding="utf-8") as f:
        for rec in records:
            key = (rec["bundle"], rec["id"])
            if key in existing:
                f.write(json.dumps(existing[key], ensure_ascii=False) + "\n")
            else:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"output={output_path}")
    print(f"translated={translated_count} cost=${total_cost:.4f} / ${budget:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
