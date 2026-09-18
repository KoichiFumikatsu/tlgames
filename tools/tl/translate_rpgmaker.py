#!/usr/bin/env python3
"""
Traducción autónoma RPG Maker MV/MZ — DeepL → OpenAI fallback.
Modifica los JSON en el directorio data/ del juego.

Uso:
  python translate_rpgmaker.py <ruta_juego> [--lang Spanish] [--provider deepl|openai]
  python translate_rpgmaker.py <ruta_juego> --dry
"""
import argparse
import datetime
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).parent))
from _env import load_env
load_env(ROOT)

# Reutilizar helpers de translate_unity_json (DeepL pool, OpenAI batch, ntfy, cache)
from translate_unity_json import (
    deepl_translate, deepl_check_usage, DeepLQuotaExhausted,
    openai_translate_batch, OpenAIBudgetExceeded,
    ntfy_send, _DEEPL_POOL, _stats, _load_openai_usage,
    needs_translation, OPENAI_MODEL, OPENAI_BATCH_SIZE,
)
import translate_unity_json as _tuj

NTFY_DEFAULT_TOPIC = ""

# ── Estado persistente de cuota DeepL ─────────────────────────────────────────

_DEEPL_STATE_FILE = ROOT / "tools" / "tl" / ".cache" / "deepl_quota_state.json"


def _deepl_exhausted_today() -> bool:
    """True si DeepL ya fue marcado como agotado en la fecha de hoy."""
    try:
        state = json.loads(_DEEPL_STATE_FILE.read_text(encoding="utf-8"))
        return state.get("exhausted_date") == datetime.date.today().isoformat()
    except Exception:
        return False


def _mark_deepl_exhausted():
    _DEEPL_STATE_FILE.parent.mkdir(exist_ok=True)
    _DEEPL_STATE_FILE.write_text(
        json.dumps({"exhausted_date": datetime.date.today().isoformat()}, ensure_ascii=False),
        encoding="utf-8"
    )

# Códigos RPG Maker MV/MZ con texto traducible
MSG_CODES = {401, 405}   # líneas de diálogo / texto desplazable
CHOICE_CODE = 102         # opciones de elección

# Campos de texto en archivos de base de datos (Actors, Items, Skills…)
DB_FIELDS = ["name", "description", "profile", "nickname",
             "message1", "message2", "message3", "message4"]


# ── Extracción ────────────────────────────────────────────────────────────────

def _is_english(text: str) -> bool:
    """True si el texto tiene suficiente contenido en inglés para traducir."""
    if not text or not text.strip():
        return False
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    ascii_letters = [c for c in letters if ord(c) < 128]
    # Si menos del 40% de letras son ASCII, es probablemente japonés/chino
    return len(ascii_letters) / len(letters) >= 0.6


def _iter_event_list(lst: list):
    """Itera sobre una lista de comandos de evento y yield (idx_cmd, idx_param, text)."""
    for ci, cmd in enumerate(lst or []):
        if not isinstance(cmd, dict):
            continue
        code = cmd.get("code")
        params = cmd.get("parameters") or []
        if code in MSG_CODES and params:
            txt = params[0]
            if isinstance(txt, str) and txt.strip() and _is_english(txt):
                yield ci, 0, txt
        elif code == CHOICE_CODE and params and isinstance(params[0], list):
            for pi, choice in enumerate(params[0]):
                if isinstance(choice, str) and choice.strip() and _is_english(choice):
                    yield ci, ("choices", pi), choice


def extract_strings(data_dir: Path) -> dict:
    """
    Devuelve dict: {filename: [{"path": [...], "text": str}, ...]}
    path es la ruta de acceso dentro del JSON para reescribir.
    """
    result = {}
    for fpath in sorted(data_dir.glob("*.json")):
        fname = fpath.name
        try:
            raw = fpath.read_text(encoding="utf-8-sig")
            data = json.loads(raw)
        except Exception:
            continue

        entries = []

        if isinstance(data, list):
            for item_idx, item in enumerate(data):
                if not item or not isinstance(item, dict):
                    continue
                # Archivos de base de datos: campos de texto
                for field in DB_FIELDS:
                    val = item.get(field)
                    if isinstance(val, str) and val.strip() and _is_english(val):
                        entries.append({"path": [item_idx, field], "text": val})
                # Eventos (CommonEvents.json): list directo
                for ci, pi, txt in _iter_event_list(item.get("list")):
                    if isinstance(pi, tuple):
                        entries.append({"path": [item_idx, "list", ci, "parameters", 0, pi[1]], "text": txt})
                    else:
                        entries.append({"path": [item_idx, "list", ci, "parameters", pi], "text": txt})
                # Páginas de evento (poco común en CommonEvents)
                for page_idx, page in enumerate(item.get("pages") or []):
                    for ci, pi, txt in _iter_event_list(page.get("list")):
                        if isinstance(pi, tuple):
                            entries.append({"path": [item_idx, "pages", page_idx, "list", ci, "parameters", 0, pi[1]], "text": txt})
                        else:
                            entries.append({"path": [item_idx, "pages", page_idx, "list", ci, "parameters", pi], "text": txt})

        elif isinstance(data, dict):
            # Map*.json: events[].pages[].list[]
            for ev_idx, ev in enumerate(data.get("events") or []):
                if not ev or not isinstance(ev, dict):
                    continue
                for page_idx, page in enumerate(ev.get("pages") or []):
                    for ci, pi, txt in _iter_event_list(page.get("list")):
                        if isinstance(pi, tuple):
                            entries.append({"path": ["events", ev_idx, "pages", page_idx, "list", ci, "parameters", 0, pi[1]], "text": txt})
                        else:
                            entries.append({"path": ["events", ev_idx, "pages", page_idx, "list", ci, "parameters", pi], "text": txt})
            # System.json: gameTitle y terms
            if "gameTitle" in data:
                t = data["gameTitle"]
                if isinstance(t, str) and t.strip():
                    entries.append({"path": ["gameTitle"], "text": t})
            terms = data.get("terms")
            if isinstance(terms, dict):
                for grupo in ("basic", "commands", "params"):
                    for i, t in enumerate(terms.get(grupo) or []):
                        if isinstance(t, str) and t.strip() and _is_english(t):
                            entries.append({"path": ["terms", grupo, i], "text": t})
                for k, t in (terms.get("messages") or {}).items():
                    if isinstance(t, str) and t.strip() and _is_english(t):
                        entries.append({"path": ["terms", "messages", k], "text": t})

        if entries:
            result[fname] = entries

    return result


def _get_nested(obj, path: list):
    for key in path:
        if isinstance(obj, list):
            obj = obj[key]
        else:
            obj = obj[key]
    return obj


def _set_nested(obj, path: list, value):
    for key in path[:-1]:
        if isinstance(obj, list):
            obj = obj[key]
        else:
            obj = obj[key]
    last = path[-1]
    if isinstance(obj, list):
        obj[last] = value
    else:
        obj[last] = value


# ── Cache ─────────────────────────────────────────────────────────────────────

def _cache_path(game_path: Path) -> Path:
    cache_dir = ROOT / "tools" / "tl" / ".cache"
    cache_dir.mkdir(exist_ok=True)
    safe = game_path.name.replace(" ", "_")[:60]
    return cache_dir / f"rpgmaker_{safe}.json"


def _load_cache(game_path: Path) -> dict:
    p = _cache_path(game_path)
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            # Normalizar claves: openai|model|texto → texto
            normalized: dict = {}
            for k, v in raw.items():
                if k.startswith("openai|"):
                    parts = k.split("|", 2)
                    if len(parts) == 3:
                        normalized[parts[2]] = v
                        continue
                normalized[k] = v
            return normalized
        except Exception:
            pass
    return {}


def _save_cache(game_path: Path, cache: dict):
    _cache_path(game_path).write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


# ── Helpers OpenAI ────────────────────────────────────────────────────────────

def _openai_chunked(texts: list, cache: dict, api_key: str, model: str, budget: float,
                    game_path: "Path | None" = None) -> list:
    """
    Llama openai_translate_batch en chunks de OPENAI_BATCH_SIZE.
    Guarda el cache tras cada chunk. Errores de red por chunk se ignoran (strings quedan None).
    Propaga OpenAIBudgetExceeded.
    """
    results: list = [None] * len(texts)
    for start in range(0, len(texts), OPENAI_BATCH_SIZE):
        chunk = texts[start:start + OPENAI_BATCH_SIZE]
        try:
            chunk_results = openai_translate_batch(chunk, cache, api_key, model, budget=budget)
            for j, r in enumerate(chunk_results):
                results[start + j] = r
        except OpenAIBudgetExceeded:
            raise
        except Exception as e:
            print(f"  [WARN OpenAI chunk {start // OPENAI_BATCH_SIZE + 1}] {e}", flush=True)
        if game_path:
            _save_cache(game_path, cache)
    return results


# ── Traducción ────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> int:
    game_path = Path(args.game_path)
    lang = args.lang
    dry = args.dry
    provider = args.provider
    ntfy_topic = args.ntfy
    budget = args.budget
    game_version = getattr(args, "game_version", "") or ""
    game_os = getattr(args, "game_os", "") or ""
    game_runtime = getattr(args, "game_runtime", "") or ""

    api_key_deepl = os.environ.get("DEEPL_API_KEY", "")
    api_key_openai = os.environ.get("OPENAI_API_KEY", "")

    # Inicializar pool DeepL (reutiliza lógica de translate_unity_json)
    pool = []
    if api_key_deepl:
        pool.append(api_key_deepl)
    for k, v in os.environ.items():
        if k.startswith("DEEPL_API_KEY") and k != "DEEPL_API_KEY" and v and v not in pool:
            pool.append(v)
    _tuj._DEEPL_POOL = pool
    deepl_available = bool(pool) and provider != "openai"
    openai_available = bool(api_key_openai)

    if deepl_available and _deepl_exhausted_today():
        deepl_available = False
        print("DeepL cuota agotada hoy - usando OpenAI directamente", flush=True)

    if not deepl_available and not openai_available:
        print("ERROR: sin DEEPL_API_KEY ni OPENAI_API_KEY", file=sys.stderr)
        return 1

    # Localizar data/
    data_dir = None
    for candidate in [
        game_path / "data",
        game_path / "www" / "data",
        game_path / "Data",
    ]:
        if candidate.is_dir() and list(candidate.glob("*.json")):
            data_dir = candidate
            break
    if not data_dir:
        print(f"ERROR: no se encontró directorio data/ en {game_path}", file=sys.stderr)
        return 1

    # Verificar cuota DeepL
    deepl_remaining = 0
    if deepl_available:
        usage = deepl_check_usage(pool[0])
        if usage:
            used = usage.get("character_count", 0)
            limit = usage.get("character_limit", 500_000)
            deepl_remaining = max(0, limit - used)
            _tuj._stats["deepl_chars_limit"] = limit
            _tuj._stats["deepl_chars_used_prev"] = used
    _tuj._stats["openai_budget"] = budget
    _tuj._stats["openai_spent"] = _tuj._load_openai_usage().get("total_cost_usd", 0.0)
    openai_remaining = max(0.0, budget - _tuj._stats["openai_spent"])

    # Extraer strings
    print(f"\n=== TL RPGMaker {game_path.name} -> {lang} ===")
    print("Extrayendo strings...", flush=True)
    all_strings = extract_strings(data_dir)
    total = sum(len(v) for v in all_strings.values())
    print(f"Archivos: {len(all_strings)}  |  Strings: {total}", flush=True)

    cache = _load_cache(game_path)
    pending_total = sum(
        1 for entries in all_strings.values()
        for e in entries
        if e["text"] not in cache
    )
    print(f"Pendientes (sin cache): {pending_total}", flush=True)
    if deepl_available:
        print(f"DeepL: {deepl_remaining:,} chars disponibles", flush=True)
    print(f"OpenAI: ${_tuj._stats['openai_spent']:.4f} gastados | presupuesto ${budget:.2f} | resta ${openai_remaining:.4f}", flush=True)

    meta_parts = []
    if game_version: meta_parts.append(f"v{game_version}")
    if game_os: meta_parts.append(game_os)
    if game_runtime: meta_parts.append(game_runtime)
    meta_line = f"[{' | '.join(meta_parts)}]\n" if meta_parts else ""

    if deepl_available and openai_available:
        provider_line = "DeepL -> OpenAI (fallback)"
    elif deepl_available:
        provider_line = "DeepL"
    elif openai_available:
        provider_line = "OpenAI" + (" (DeepL agotado hoy)" if _deepl_exhausted_today() else "")
    else:
        provider_line = "sin provider"

    ntfy_send(ntfy_topic,
              f"{meta_line}{pending_total} strings | {len(all_strings)} archivos | EN -> {lang}\nProvider: {provider_line}",
              title=f"TL {game_path.name} - Iniciando")

    translated = 0
    errors = 0
    files_done = 0
    deepl_active = deepl_available
    last_ntfy_pct = -1

    for fname, entries in all_strings.items():
        file_pending = [e for e in entries if e["text"] not in cache]
        if not file_pending:
            files_done += 1
            pct_line = f"[{files_done}/{len(all_strings)}] {fname} | {translated}/{pending_total} strings | {int(translated/max(pending_total,1)*100)}%"
            print(pct_line, flush=True)
            continue

        # Leer JSON actual
        fpath = data_dir / fname
        try:
            raw = fpath.read_text(encoding="utf-8-sig")
            data = json.loads(raw)
        except Exception as e:
            print(f"  SKIP {fname}: {e}", flush=True)
            files_done += 1
            continue

        # Hacer backup si no existe
        bak = fpath.with_suffix(".json.bak")
        if not bak.exists() and not dry:
            bak.write_bytes(fpath.read_bytes())

        # Traducir pendientes de este archivo en batch
        texts = [e["text"] for e in file_pending]
        results = []

        if deepl_active:
            batch_results = []
            for txt in texts:
                if not deepl_active:
                    # Cuota agotada durante este batch — no seguir intentando DeepL
                    batch_results.append(None)
                    continue
                if txt in cache:
                    batch_results.append(cache[txt])
                    continue
                try:
                    tr = deepl_translate(txt, cache)
                    batch_results.append(tr)
                    translated += 1
                except DeepLQuotaExhausted:
                    print(f"  DeepL cuota agotada en {fname} — cambiando a OpenAI", flush=True)
                    deepl_active = False
                    _mark_deepl_exhausted()
                    ntfy_send(ntfy_topic,
                              f"{meta_line}DeepL cuota agotada. Continuando con OpenAI.",
                              title=f"TL {game_path.name}", priority="high")
                    batch_results.append(None)
                except Exception as e:
                    print(f"  [WARN DeepL] {e}", flush=True)
                    errors += 1
                    batch_results.append(None)

            # Strings que fallaron en DeepL → OpenAI (en chunks)
            retry_idx = [i for i, r in enumerate(batch_results) if r is None]
            if retry_idx and openai_available:
                retry_texts = [texts[i] for i in retry_idx]
                try:
                    retry_results = _openai_chunked(retry_texts, cache, api_key_openai,
                                                    OPENAI_MODEL, budget, game_path)
                    for j, i in enumerate(retry_idx):
                        if retry_results[j] is not None:
                            batch_results[i] = retry_results[j]
                            translated += 1
                except OpenAIBudgetExceeded as e:
                    print(f"  [BUDGET] {e}", flush=True)
                    ntfy_send(ntfy_topic, f"Presupuesto OpenAI alcanzado. {translated}/{pending_total} strings.",
                              title=f"TL {game_path.name}", priority="high")
                    _save_cache(game_path, cache)
                    return 2
            results = batch_results
        else:
            # Solo OpenAI
            if not openai_available:
                print("ERROR: DeepL agotado y sin OpenAI key", file=sys.stderr)
                _save_cache(game_path, cache)
                return 1
            try:
                results = _openai_chunked(texts, cache, api_key_openai,
                                          OPENAI_MODEL, budget, game_path)
                translated += len([r for r in results if r])
            except OpenAIBudgetExceeded as e:
                print(f"  [BUDGET] {e}", flush=True)
                ntfy_send(ntfy_topic, f"Presupuesto OpenAI alcanzado. {translated}/{pending_total} strings.",
                          title=f"TL {game_path.name}", priority="high")
                _save_cache(game_path, cache)
                return 2

        # Escribir traducciones en el JSON
        for entry, result in zip(file_pending, results):
            if result:
                cache[entry["text"]] = result
                if not dry:
                    try:
                        _set_nested(data, entry["path"], result)
                    except Exception:
                        pass

        if not dry:
            fpath.write_text(json.dumps(data, ensure_ascii=False, indent=None, separators=(',', ':')), encoding="utf-8")
        _save_cache(game_path, cache)

        files_done += 1
        pct = int(translated / max(pending_total, 1) * 100)
        pct_line = f"[{files_done}/{len(all_strings)}] {fname} | {translated}/{pending_total} strings | {pct}%"
        print(pct_line, flush=True)

        # ntfy cada 5%
        ntfy_pct = (pct // 5) * 5
        if ntfy_pct > last_ntfy_pct and ntfy_pct > 0:
            last_ntfy_pct = ntfy_pct
            openai_spent_now = _tuj._load_openai_usage().get("total_cost_usd", 0.0)
            body = (
                f"{meta_line}"
                f"Archivos: {files_done}/{len(all_strings)}\n"
                f"Strings: {translated}/{pending_total}\n"
                f"Archivo actual: {fname}\n"
                f"OpenAI: ${openai_spent_now:.4f} gastados"
            )
            ntfy_send(ntfy_topic, body, title=f"TL {game_path.name} - {ntfy_pct}%")

    # Resumen final
    openai_final = _tuj._load_openai_usage().get("total_cost_usd", 0.0)
    summary_lines = []
    if meta_line.strip(): summary_lines.append(meta_line.strip())
    summary_lines.append(f"Strings: {translated}/{pending_total}")
    summary_lines.append(f"Archivos: {files_done}/{len(all_strings)}")
    summary_lines.append(f"Idioma: EN -> {lang}")
    summary_lines.append(f"OpenAI: ${openai_final:.4f} gastados")
    if errors: summary_lines.append(f"Errores: {errors}")
    summary = "\n".join(summary_lines)
    print(f"\n{summary}", flush=True)
    ntfy_send(ntfy_topic, summary, title=f"TL {game_path.name} - Listo", priority="high")

    return 0 if errors == 0 else 1


def main():
    ap = argparse.ArgumentParser(description="Traducción RPG Maker MV/MZ — DeepL->OpenAI")
    ap.add_argument("game_path", help="Ruta raíz del juego")
    ap.add_argument("--lang", default="Spanish")
    ap.add_argument("--provider", choices=["deepl", "openai"], default="deepl")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--ntfy", default=os.environ.get("NTFY_TOPIC", NTFY_DEFAULT_TOPIC))
    ap.add_argument("--budget", type=float, default=float(os.environ.get("OPENAI_BUDGET_USD", "1.50")))
    ap.add_argument("--game-version", default="")
    ap.add_argument("--game-os", default="")
    ap.add_argument("--game-runtime", default="")
    args = ap.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
