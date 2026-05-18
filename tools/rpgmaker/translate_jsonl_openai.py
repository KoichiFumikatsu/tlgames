#!/usr/bin/env python3
"""Translate RPG Maker/Pokemon Essentials JSONL corpora with OpenAI."""

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


RPGMAKER_SYSTEM_PROMPT = (
    "Eres un traductor profesional EN->ES para un fangame de Pokemon Essentials/RPG Maker XP.\n"
    "Vas a recibir un JSON array de strings en ingles.\n"
    "REGLAS ESTRICTAS:\n"
    "1. Devuelve SOLO un JSON object con la propiedad items, array de strings del mismo largo y orden.\n"
    "2. Traduce al espanol neutro natural, con tuteo y tono de juego Pokemon.\n"
    "3. Conserva exactamente los placeholders ZT000Z, ZT001Z, etc.\n"
    "4. Conserva codigos de RPG Maker, variables, placeholders, saltos \\n literales y formato.\n"
    "5. No traduzcas nombres internos, ids, symbols Ruby ni nombres de Pokemon si aparecen como nombres propios.\n"
    "6. Para nombres de objetos, movimientos, habilidades, tipos y stats, usa terminologia oficial de Pokemon en espanol cuando la conozcas.\n"
    "7. Para descripciones, prioriza claridad y longitud compacta para cajas pequenas.\n"
    "8. Nunca unas ni dividas elementos: N entradas => N salidas.\n"
)


TOKEN_PATTERNS = [
    re.compile(r"\\[A-Za-z]+\[[^\]]+\]"),
    re.compile(r"\\[A-Za-z]+"),
    re.compile(r"#\{[^{}]+\}"),
    re.compile(r"%\([a-zA-Z_][a-zA-Z0-9_]*\)[sdif]"),
    re.compile(r"%[0-9.]*[sdif]"),
    re.compile(r"\{[0-9A-Za-z_]+\}"),
    re.compile(r"\[[A-Z0-9_]+\]"),
    re.compile(r"\r?\n"),
]


def tokenize(text: str) -> tuple[str, list[str]]:
    mapping: list[str] = []

    def repl(match: re.Match) -> str:
        index = len(mapping)
        mapping.append(match.group(0))
        return f"ZT{index:03d}Z"

    out = text
    for pattern in TOKEN_PATTERNS:
        out = pattern.sub(repl, out)
    return out, mapping


def detokenize(text: str, mapping: list[str]) -> str:
    for index, original in enumerate(mapping):
        text = re.sub(rf"[Zz]\s*[Tt]\s*0*{index}\s*[Zz]", lambda _match, value=original: value, text)
    return text


def load_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def merge_existing_targets(records: list[dict], output_path: Path) -> int:
    if not output_path.exists():
        return 0
    existing = load_jsonl(output_path)
    targets = {
        (record.get("bundle"), record.get("id")): record.get("target", "")
        for record in existing
        if record.get("target")
    }
    merged = 0
    for record in records:
        key = (record.get("bundle"), record.get("id"))
        if not record.get("target") and targets.get(key):
            record["target"] = targets[key]
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
    out: list[str] = []
    for source, target, mapping in zip(sources, translated, mappings):
        if target is None:
            target = source
        out.append(detokenize(str(target), mapping))
    return out


def translate_with_split(sources: list[str], cache: dict, api_key: str, model: str) -> list[str]:
    try:
        return translate_batch(sources, cache, api_key, model)
    except tl_translate.BatchSizeMismatch:
        if len(sources) == 1:
            raise
        midpoint = max(1, len(sources) // 2)
        return translate_with_split(sources[:midpoint], cache, api_key, model) + translate_with_split(sources[midpoint:], cache, api_key, model)


def main() -> int:
    parser = argparse.ArgumentParser(description="Translate RPG Maker JSONL corpus with OpenAI")
    parser.add_argument("input_jsonl")
    parser.add_argument("--out", default="")
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

    input_path = Path(args.input_jsonl)
    output_path = Path(args.out) if args.out else input_path.with_suffix(".translated.jsonl")
    records = load_jsonl(input_path)
    merged = merge_existing_targets(records, output_path)
    pending_indexes = [
        index for index, record in enumerate(records)
        if str(record.get("source", "")).strip() and not str(record.get("target", "")).strip()
    ]
    if args.limit:
        pending_indexes = pending_indexes[: args.limit]

    tl_translate.GEMINI_BATCH_SYSTEM_PROMPT = RPGMAKER_SYSTEM_PROMPT
    tl_translate.OPENAI_BUDGET_USD = float(args.budget)
    cache = tl_translate.load_cache("openai_rpgmaker")

    print(f"input={input_path}")
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
                tl_translate.save_cache(cache, "openai_rpgmaker")
                time.sleep(tl_translate.RATE_LIMIT_SEC_OPENAI)
                continue

            for record_index, translated in zip(batch_indexes, translations):
                records[record_index]["target"] = translated.replace("\r\n", "\\n").replace("\n", "\\n")
            done += len(batch_indexes)
            tl_translate.save_cache(cache, "openai_rpgmaker")
            if done % max(1, args.batch_size * args.flush_every) == 0:
                write_jsonl(output_path, records)
                print(f"progress={done}/{len(pending_indexes)} failed={failed}", flush=True)
            time.sleep(tl_translate.RATE_LIMIT_SEC_OPENAI)
    except tl_translate.OpenAIBudgetExceeded as exc:
        write_jsonl(output_path, records)
        tl_translate.save_cache(cache, "openai_rpgmaker")
        print(f"[BUDGET] {exc}", flush=True)
        return 3
    except KeyboardInterrupt:
        write_jsonl(output_path, records)
        tl_translate.save_cache(cache, "openai_rpgmaker")
        print("interrumpido: progreso guardado", flush=True)
        return 130

    write_jsonl(output_path, records)
    tl_translate.save_cache(cache, "openai_rpgmaker")
    translated_total = sum(1 for record in records if str(record.get("target", "")).strip())
    print(f"done_this_run={done}")
    print(f"failed_this_run={failed}")
    print(f"translated_total={translated_total}/{len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())