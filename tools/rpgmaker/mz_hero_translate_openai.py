#!/usr/bin/env python3
"""Translate the deduplicated Hero RPG Maker MZ JSONL corpus with OpenAI."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path


TL_ROOT = Path(__file__).resolve().parents[1] / "tl"
sys.path.insert(0, str(TL_ROOT))

import translate as tl_translate  # type: ignore
from _env import load_env  # type: ignore


load_env()


SYSTEM_PROMPT = (
    "Eres un traductor profesional para un RPG Maker MZ de fantasia. "
    "Traduce cada string del ingles, japones o mezcla al espanol neutro natural. "
    "Usa tuteo cuando el tono sea casual. Mantén nombres propios y terminos tecnicos "
    "si parecen ids o nombres internos. Prioriza frases compactas para ventanas pequenas. "
    "REGLAS ESTRICTAS: devuelve solo un JSON object con propiedad items, array de strings "
    "del mismo largo y orden; conserva exactamente placeholders ZT000Z, ZT001Z, etc.; "
    "conserva codigos RPG Maker, variables, %1, %2, saltos \\n literales y formato; "
    "no unas ni dividas elementos; no agregues explicaciones."
)


TOKEN_PATTERNS = [
    re.compile(r"\\[A-Za-z]+\[[^\]]+\]"),
    re.compile(r"\\[A-Za-z]+"),
    re.compile(r"\\[{}$\\.!><|^]"),
    re.compile(r"#\{[^{}]+\}"),
    re.compile(r"%\([a-zA-Z_][a-zA-Z0-9_]*\)[sdif]"),
    re.compile(r"%[0-9.]*[sdif]"),
    re.compile(r"%\d+"),
    re.compile(r"\{[0-9A-Za-z_]+\}"),
    re.compile(r"\[[A-Z0-9_]+\]"),
    re.compile(r"\r?\n"),
]


def load_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def tokenize(text: str) -> tuple[str, list[str]]:
    mapping: list[str] = []

    def repl(match: re.Match) -> str:
        index = len(mapping)
        mapping.append(match.group(0))
        return f"ZT{index:03d}Z"

    output = text
    for pattern in TOKEN_PATTERNS:
        output = pattern.sub(repl, output)
    return output, mapping


def detokenize(text: str, mapping: list[str]) -> str:
    for index, original in enumerate(mapping):
        text = re.sub(rf"[Zz]\s*[Tt]\s*0*{index}\s*[Zz]", lambda _match, value=original: value, text)
    return text


def merge_existing_targets(records: list[dict], output_path: Path) -> int:
    if not output_path.exists():
        return 0
    existing = load_jsonl(output_path)
    targets = {
        str(record.get("id", "")): str(record.get("target", ""))
        for record in existing
        if str(record.get("target", "")).strip()
    }
    merged = 0
    for record in records:
        target = targets.get(str(record.get("id", "")))
        if target and not str(record.get("target", "")).strip():
            record["target"] = target
            merged += 1
    return merged


def translate_batch(sources: list[str], cache: dict, api_key: str, model: str) -> list[str]:
    prepared: list[str] = []
    mappings: list[list[str]] = []
    for source in sources:
        tokenized, mapping = tokenize(source)
        prepared.append(tokenized)
        mappings.append(mapping)
    translated = tl_translate.openai_translate_batch(prepared, cache, api_key, model)
    output: list[str] = []
    for source, target, mapping in zip(sources, translated, mappings):
        if target is None:
            target = source
        output.append(detokenize(str(target), mapping))
    return output


def translate_with_split(sources: list[str], cache: dict, api_key: str, model: str) -> list[str]:
    try:
        return translate_batch(sources, cache, api_key, model)
    except tl_translate.OpenAIBudgetExceeded:
        raise
    except Exception as exc:
        if len(sources) == 1:
            raise
        midpoint = max(1, len(sources) // 2)
        print(
            f"[split] size={len(sources)} err={type(exc).__name__}: {exc}; retrying {midpoint}+{len(sources) - midpoint}",
            flush=True,
        )
        return translate_with_split(sources[:midpoint], cache, api_key, model) + translate_with_split(sources[midpoint:], cache, api_key, model)


def main() -> int:
    parser = argparse.ArgumentParser(description="Translate Hero MZ JSONL corpus with OpenAI")
    parser.add_argument("input_jsonl", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--model", default=tl_translate.OPENAI_MODEL)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--budget", type=float, default=float(os.environ.get("OPENAI_BUDGET_USD", "1.50")))
    parser.add_argument("--flush-every", type=int, default=5)
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("OPENAI_API_KEY no esta configurada en .env o entorno", file=sys.stderr)
        return 2

    output_path = args.out or args.input_jsonl.with_suffix(".translated.jsonl")
    records = load_jsonl(args.input_jsonl)
    merged = merge_existing_targets(records, output_path)
    pending_indexes = [
        index for index, record in enumerate(records)
        if str(record.get("source", "")).strip() and not str(record.get("target", "")).strip()
    ]
    if args.limit:
        pending_indexes = pending_indexes[: args.limit]

    tl_translate.GEMINI_BATCH_SYSTEM_PROMPT = SYSTEM_PROMPT
    tl_translate.OPENAI_BUDGET_USD = float(args.budget)
    cache = tl_translate.load_cache("openai_mz_hero")

    print(f"input={args.input_jsonl}")
    print(f"output={output_path}")
    print(f"records={len(records)} merged_existing={merged} pending_this_run={len(pending_indexes)}")
    print(f"model={args.model} batch={args.batch_size} budget=${tl_translate.OPENAI_BUDGET_USD:.2f}")

    done = 0
    failed = 0
    try:
        for start in range(0, len(pending_indexes), args.batch_size):
            batch_indexes = pending_indexes[start : start + args.batch_size]
            sources = [records[index]["source"] for index in batch_indexes]
            try:
                translations = translate_with_split(sources, cache, api_key, args.model)
            except tl_translate.OpenAIBudgetExceeded:
                raise
            except Exception as exc:
                failed += len(batch_indexes)
                print(f"[WARN] batch_failed start={start} size={len(batch_indexes)} err={type(exc).__name__}: {exc}", flush=True)
                write_jsonl(output_path, records)
                tl_translate.save_cache(cache, "openai_mz_hero")
                time.sleep(tl_translate.RATE_LIMIT_SEC_OPENAI)
                continue

            for record_index, translated in zip(batch_indexes, translations):
                records[record_index]["target"] = translated.replace("\r\n", "\n")
            done += len(batch_indexes)
            tl_translate.save_cache(cache, "openai_mz_hero")
            if done % max(1, args.batch_size * args.flush_every) == 0:
                write_jsonl(output_path, records)
                print(f"progress={done}/{len(pending_indexes)} failed={failed}", flush=True)
            time.sleep(tl_translate.RATE_LIMIT_SEC_OPENAI)
    except tl_translate.OpenAIBudgetExceeded as exc:
        write_jsonl(output_path, records)
        tl_translate.save_cache(cache, "openai_mz_hero")
        print(f"[BUDGET] {exc}", flush=True)
        return 3
    except KeyboardInterrupt:
        write_jsonl(output_path, records)
        tl_translate.save_cache(cache, "openai_mz_hero")
        print("interrumpido: progreso guardado", flush=True)
        return 130

    write_jsonl(output_path, records)
    tl_translate.save_cache(cache, "openai_mz_hero")
    translated_total = sum(1 for record in records if str(record.get("target", "")).strip())
    print(f"done_this_run={done}")
    print(f"failed_this_run={failed}")
    print(f"translated_total={translated_total}/{len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())