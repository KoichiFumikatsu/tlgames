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


if os.environ.get("UNITY_OPENAI_FAST_FAIL", "").strip() in {"1", "true", "TRUE", "yes", "YES"}:
    # Unity static runs can stall on repeated network retries; allow a fast-fail mode.
    tl_translate.RETRY_BACKOFF = []


UNITY_SYSTEM_PROMPT = (
    "Eres un traductor profesional EN->ES para novelas visuales hechas en Unity/Naninovel.\n"
    "Vas a recibir un JSON array de strings en ingles.\n"
    "REGLAS ESTRICTAS:\n"
    "1. Devuelve SOLO un JSON array de strings, del mismo largo y en el mismo orden.\n"
    "2. Cada string de salida debe ser unicamente la traduccion del string correspondiente.\n"
    "3. Conserva EXACTAMENTE los placeholders del tipo ZT000Z, ZT001Z, ZG000Z.\n"
    "4. Conserva tags, variables y placeholders protegidos; no los traduzcas ni los reordenes.\n"
    "5. Conserva los \\n literales, comillas escapadas y espacios significativos.\n"
    "6. NUNCA unas ni dividas elementos: N inputs => exactamente N outputs.\n"
    "7. Registro: espanol neutro, natural y conversacional. Usa 'tu' salvo contexto formal claro.\n"
    "8. Si un string viene vacio o es solo placeholders/simbolos, devuelvelo tal cual.\n"
)


TOKEN_PATTERNS = [
    (re.compile(r"<[^<>]+>"), "TMP"),
    (re.compile(r"\{[^{}]+\}"), "BRACE"),
    (re.compile(r"\[[^\[\]]+\]"), "VAR"),
    (re.compile(r"\|[A-Za-z0-9_]+\|"), "PLACE"),
    (re.compile(r"\\n"), "NL"),
    (re.compile(r"\\\""), "QUOTE"),
    (re.compile(r"%\([a-zA-Z_][a-zA-Z0-9_]*\)[sdif]"), "PCTNAMED"),
    (re.compile(r"%[0-9.]*[sdif]"), "PCT"),
]


def tokenize(text: str) -> tuple[str, list[tuple[str, str]]]:
    mapping: list[tuple[str, str]] = []

    def repl(match: re.Match, kind: str) -> str:
        index = len(mapping)
        mapping.append((kind, match.group(0)))
        return f"ZT{index:03d}Z"

    out = text
    for pattern, kind in TOKEN_PATTERNS:
        out = pattern.sub(lambda match, token_kind=kind: repl(match, token_kind), out)
    return out, mapping


def detokenize(text: str, mapping: list[tuple[str, str]]) -> str:
    for index, (_kind, original) in enumerate(mapping):
        pattern = re.compile(rf"[Zz]\s*[Tt]\s*0*{index}\s*[Zz]")
        text = pattern.sub(lambda _match, replacement=original: replacement, text)
    return text


def load_jsonl(path: Path) -> list[dict]:
    records = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
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


def translate_batch(srcs: list[str], cache: dict, api_key: str, model: str) -> list[str]:
    tokenized = []
    mappings = []
    for source in srcs:
        prepared, mapping = tokenize(source)
        tokenized.append(prepared)
        mappings.append(mapping)

    translated_tokenized = tl_translate.openai_translate_batch(tokenized, cache, api_key, model)
    results = []
    for source, translated, mapping in zip(srcs, translated_tokenized, mappings):
        if translated is None:
            translated = source
        results.append(detokenize(str(translated), mapping))
    return results


def translate_with_split(srcs: list[str], cache: dict, api_key: str, model: str) -> list[str]:
    try:
        return translate_batch(srcs, cache, api_key, model)
    except tl_translate.BatchSizeMismatch:
        if len(srcs) == 1:
            raise
        midpoint = max(1, len(srcs) // 2)
        return (
            translate_with_split(srcs[:midpoint], cache, api_key, model)
            + translate_with_split(srcs[midpoint:], cache, api_key, model)
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Translate Naninovel JSONL corpus with OpenAI.")
    parser.add_argument("input_jsonl")
    parser.add_argument("--out", default="")
    parser.add_argument("--model", default=tl_translate.OPENAI_MODEL)
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--budget", type=float, default=float(os.environ.get("OPENAI_BUDGET_USD", "0.50")))
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
        if (record.get("source") or "").strip() and not (record.get("target") or "").strip()
    ]
    if args.limit:
        pending_indexes = pending_indexes[:args.limit]

    tl_translate.GEMINI_BATCH_SYSTEM_PROMPT = UNITY_SYSTEM_PROMPT
    tl_translate.OPENAI_BUDGET_USD = float(args.budget)
    cache = tl_translate.load_cache("openai")

    print(f"input={input_path}")
    print(f"output={output_path}")
    print(f"records={len(records)} merged_existing={merged} pending_this_run={len(pending_indexes)}")
    print(f"model={args.model} batch={args.batch_size} budget=${tl_translate.OPENAI_BUDGET_USD:.2f}")

    done = 0
    failed = 0
    try:
        for start in range(0, len(pending_indexes), args.batch_size):
            batch_indexes = pending_indexes[start:start + args.batch_size]
            sources = [records[index]["source"] for index in batch_indexes]
            try:
                translations = translate_with_split(sources, cache, api_key, args.model)
            except tl_translate.OpenAIBudgetExceeded:
                raise
            except Exception as exc:
                failed += len(batch_indexes)
                print(
                    f"[WARN] batch_failed start={start} size={len(batch_indexes)} err={type(exc).__name__}: {exc}",
                    flush=True,
                )
                # Guardar avance parcial y continuar con el siguiente batch.
                if (done + failed) % max(1, args.batch_size * args.flush_every) == 0:
                    write_jsonl(output_path, records)
                    tl_translate.save_cache(cache, "openai")
                time.sleep(tl_translate.RATE_LIMIT_SEC_OPENAI)
                continue

            for record_index, translated in zip(batch_indexes, translations):
                records[record_index]["target"] = translated.replace("\r\n", "\\n").replace("\n", "\\n")
            done += len(batch_indexes)
            tl_translate.save_cache(cache, "openai")
            if done % (args.batch_size * args.flush_every) == 0:
                write_jsonl(output_path, records)
                print(f"progress={done}/{len(pending_indexes)} failed={failed}", flush=True)
            time.sleep(tl_translate.RATE_LIMIT_SEC_OPENAI)
    except tl_translate.OpenAIBudgetExceeded as exc:
        write_jsonl(output_path, records)
        tl_translate.save_cache(cache, "openai")
        print(f"[BUDGET] {exc}", flush=True)
        return 3
    except KeyboardInterrupt:
        write_jsonl(output_path, records)
        tl_translate.save_cache(cache, "openai")
        print("interrumpido: progreso guardado", flush=True)
        return 130

    write_jsonl(output_path, records)
    tl_translate.save_cache(cache, "openai")
    translated_total = sum(1 for record in records if (record.get("target") or "").strip())
    print(f"done_this_run={done}")
    print(f"failed_this_run={failed}")
    print(f"translated_total={translated_total}/{len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())