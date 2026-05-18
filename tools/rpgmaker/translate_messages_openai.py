#!/usr/bin/env python3
"""Translate Pokemon Essentials MessageTypes JSONL with OpenAI."""

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
    "Eres un traductor profesional EN->ES para un fangame de Pokemon Essentials/RPG Maker XP.\n"
    "Vas a recibir un JSON array de strings de mensajes runtime.\n"
    "REGLAS ESTRICTAS:\n"
    "1. Devuelve SOLO un JSON object con la propiedad items, array de strings del mismo largo y orden.\n"
    "2. Traduce al espanol neutro natural, con tuteo y tono de juego Pokemon.\n"
    "3. Conserva exactamente todos los placeholders ZT000Z, ZT001Z, etc.; son obligatorios y deben aparecer una vez, en el mismo orden.\n"
    "4. Los placeholders pueden representar codigos como nombres, variables, ventanas, colores o formato; no los traduzcas, no los borres y no los sustituyas.\n"
    "5. Traduce todo el lenguaje natural alrededor de los placeholders. No dejes palabras inglesas como Hello, You, So, Show, Do si no son nombres propios.\n"
    "6. Conserva nombres propios, nombres de Pokemon, variables y formato.\n"
    "7. Mantén frases compactas para cajas de texto pequenas.\n"
    "8. Nunca unas ni dividas elementos: N entradas => N salidas.\n"
    "Ejemplos: 'ZT000Z ZT001Z Your party is full!' => 'ZT000Z ZT001Z ¡Tu equipo está lleno!'; "
    "'ZT000Z received a Pokédex!' => 'ZT000Z recibió una Pokédex!'.\n"
)

CACHE_NAME = "openai_rpgmaker_messages_v4"
CACHE_PATH = tl_translate.CACHE_DIR / f"{CACHE_NAME}.json"


def load_message_cache() -> dict:
    return tl_translate._load(CACHE_PATH)


def save_message_cache(cache: dict) -> None:
    tl_translate._save(CACHE_PATH, cache)


LEADING_BOX_CONTROL_RE = re.compile(r"^(?:\\[br])+")


TOKEN_PATTERNS = [
    re.compile(r"\\[A-Za-z]+\[[^\]]+\]"),
    re.compile(r"\\(?:PN|CN|wu|wm|wd|op|cl|G|[br])"),
    re.compile(r"#\{[^{}]+\}"),
    re.compile(r"%\([a-zA-Z_][a-zA-Z0-9_]*\)[sdif]"),
    re.compile(r"%[0-9.]*[sdif]"),
    re.compile(r"\{[0-9A-Za-z_:]+\}"),
    re.compile(r"<[^>]+>"),
]


def tokenize(text: str) -> tuple[str, list[str]]:
    mapping: list[str] = []

    def repl(match: re.Match) -> str:
        index = len(mapping)
        mapping.append(match.group(0))
        return f" ZT{index:03d}Z "

    out = text
    for pattern in TOKEN_PATTERNS:
        out = pattern.sub(repl, out)
    return re.sub(r" {2,}", " ", out).strip(), mapping


def detokenize(text: str, mapping: list[str]) -> str:
    for index, original in enumerate(mapping):
        text = re.sub(rf"[Zz]\s*[Tt]\s*0*{index}\s*[Zz]", lambda _match, value=original: value, text)
    text = re.sub(r"(\\[brn])\s+", r"\1", text)
    text = re.sub(r"(<[^>]+>)\s+(?=[\\{<])", r"\1", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    return text.strip()


def prepare_source(source: str) -> tuple[str, str, list[str]]:
    prefix_match = LEADING_BOX_CONTROL_RE.match(source)
    prefix = prefix_match.group(0) if prefix_match else ""
    body = source[len(prefix) :].replace("\\n", "\n")
    tokenized, mapping = tokenize(body)
    return prefix, tokenized, mapping


def restore_target(prefix: str, target: str, mapping: list[str]) -> str:
    restored = detokenize(target, mapping)
    restored = restored.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")
    return prefix + restored


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
        record.get("id"): record.get("target", "")
        for record in existing
        if record.get("id") and str(record.get("target", "")).strip()
    }
    merged = 0
    for record in records:
        target = targets.get(record.get("id"))
        if not str(record.get("target", "")).strip() and target:
            record["target"] = target
            merged += 1
    return merged


def translate_batch(sources: list[str], cache: dict, api_key: str, model: str) -> list[str]:
    prepared: list[str] = []
    mappings: list[list[str]] = []
    prefixes: list[str] = []
    for source in sources:
        prefix, tokenized, mapping = prepare_source(source)
        prefixes.append(prefix)
        prepared.append(tokenized)
        mappings.append(mapping)
    translated = tl_translate.openai_translate_batch(prepared, cache, api_key, model)
    out: list[str] = []
    for source, target, prefix, mapping in zip(sources, translated, prefixes, mappings):
        if target is None:
            target = source
        out.append(restore_target(prefix, str(target), mapping))
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
    parser = argparse.ArgumentParser(description="Translate Pokemon Essentials messages JSONL with OpenAI")
    parser.add_argument("input_jsonl")
    parser.add_argument("--out", default="")
    parser.add_argument("--model", default=tl_translate.OPENAI_MODEL)
    parser.add_argument("--batch-size", type=int, default=15)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--budget", type=float, default=float(os.environ.get("OPENAI_BUDGET_USD", "2.50")))
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

    tl_translate.GEMINI_BATCH_SYSTEM_PROMPT = SYSTEM_PROMPT
    tl_translate.OPENAI_BUDGET_USD = float(args.budget)
    cache = load_message_cache()

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
                save_message_cache(cache)
                time.sleep(tl_translate.RATE_LIMIT_SEC_OPENAI)
                continue
            for record_index, translated in zip(batch_indexes, translations):
                records[record_index]["target"] = translated
            done += len(batch_indexes)
            save_message_cache(cache)
            if done % max(1, args.batch_size * args.flush_every) == 0:
                write_jsonl(output_path, records)
                print(f"progress={done}/{len(pending_indexes)} failed={failed}", flush=True)
            time.sleep(tl_translate.RATE_LIMIT_SEC_OPENAI)
    except tl_translate.OpenAIBudgetExceeded as exc:
        write_jsonl(output_path, records)
        save_message_cache(cache)
        print(f"[BUDGET] {exc}", flush=True)
        return 3
    except KeyboardInterrupt:
        write_jsonl(output_path, records)
        save_message_cache(cache)
        print("interrumpido: progreso guardado", flush=True)
        return 130

    write_jsonl(output_path, records)
    save_message_cache(cache)
    translated_total = sum(1 for record in records if str(record.get("target", "")).strip())
    print(f"done_this_run={done}")
    print(f"failed_this_run={failed}")
    print(f"translated_total={translated_total}/{len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())