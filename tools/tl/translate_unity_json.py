#!/usr/bin/env python3
"""
translate_unity_json.py — Traducción autónoma de juegos Unity con sistema nativo JSON.
Flujo: DeepL → OpenAI fallback automático cuando DeepL agota cuota (456).
Sin preguntas. Sin prompts. Notificaciones ntfy.sh en tiempo real.

Uso:
  python3 translate_unity_json.py <game_path> [opciones]

Opciones:
  --lang NOMBRE    Carpeta destino en Translations/ (default: Spanish)
  --ntfy TOPIC     Topic ntfy.sh (default: koichi_agenda_2026 o NTFY_TOPIC env)
  --budget USD     Tope gasto OpenAI por sesión (default: OPENAI_BUDGET_USD o 1.50)
  --batch N        Strings por request OpenAI (default: 25)
  --dry            Solo muestra, no escribe archivos
  --quiet          Sin notificaciones ntfy (solo stdout)

Estructura esperada:
  <game_path>/
    <Data>/
      StreamingAssets/
        Translations/
          English/     ← fuente
          languages.json
          <lang>/      ← destino (creado si no existe)
"""

import argparse
import json
import os
import re
import sys
import time
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # repo root
sys.path.insert(0, str(ROOT / "tools" / "tl"))
from _env import load_env  # type: ignore
load_env()

# ── Constantes ────────────────────────────────────────────────────────────────

DEEPL_API = "https://api-free.deepl.com/v2/translate"
OPENAI_API = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = "gpt-4.1-nano"
OPENAI_PRICING = {"gpt-4.1-nano": (0.10, 0.40)}
OPENAI_BATCH_SIZE = 25
RATE_LIMIT_DEEPL = 0.12   # 500 req/s free tier limit (conservador)
RATE_LIMIT_OPENAI = 0.35
RETRY_BACKOFF = [2, 5, 15]
NTFY_DEFAULT_TOPIC = "koichi_agenda_2026"
NTFY_URL = "https://ntfy.sh"

# Pool de keys DeepL (inicializado en main)
_DEEPL_POOL: list[str] = []
_DEEPL_EXHAUSTED: set[str] = set()
_deepl_active_idx = 0

# Estadísticas de sesión (para reportes en ntfy)
_stats = {
    "deepl_chars_used": 0,
    "deepl_chars_limit": 500_000,  # free tier
    "deepl_chars_used_prev": 0,    # uso previo a esta sesión
    "openai_budget": 0.0,
    "openai_spent": 0.0,
}


def deepl_check_usage(api_key: str) -> dict:
    """Consulta /v2/usage de DeepL. Retorna {'character_count':N,'character_limit':M} o {}."""
    if not api_key:
        return {}
    try:
        req = urllib.request.Request(
            "https://api-free.deepl.com/v2/usage",
            headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return {}


# ── Helpers ntfy ──────────────────────────────────────────────────────────────

def ntfy_send(topic: str, msg: str, title: str = "TL Games", tags: str = "gear",
              priority: str = "default"):
    if not topic:
        return
    try:
        payload = msg.encode("utf-8")
        req = urllib.request.Request(
            f"{NTFY_URL}/{topic}",
            data=payload,
            headers={
                "Title": title,
                "Priority": priority,
                "Tags": tags,
                "Content-Type": "text/plain; charset=utf-8",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=8)
    except Exception:
        pass  # ntfy es best-effort; no abortar el pipeline


# ── Tokenizador de tags TMP / placeholders ────────────────────────────────────
# Protege <tag>, <tag=val>, </tag>, ::Name::, {placeholder}

_TAG_RE = re.compile(r"(<[^<>]+>|::\w[\w:]*::|{[\w_]+})")


def tokenize_tmp(text: str) -> tuple[str, list[str]]:
    """Reemplaza tags/placeholders por ZU###Z. Devuelve (tokenized, sentinel_list)."""
    tokens: list[str] = []

    def _repl(m: re.Match) -> str:
        idx = len(tokens)
        tokens.append(m.group(0))
        return f"ZU{idx:03d}Z"

    return _TAG_RE.sub(_repl, text), tokens


def detokenize_tmp(text: str, tokens: list[str]) -> str:
    for idx, orig in enumerate(tokens):
        text = re.sub(rf"[Zz]\s*[Uu]\s*0*{idx}\s*[Zz]", orig, text)
    return text


def needs_translation(text: str) -> bool:
    """Retorna False si el string no tiene texto real que traducir."""
    stripped = _TAG_RE.sub("", text).strip()
    return bool(stripped) and stripped not in ("...", "…", "-", "~", "?", "!")


# ── Cache ──────────────────────────────────────────────────────────────────────

def _load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        txt = path.read_text(encoding="utf-8")
        return json.loads(txt) if txt.strip() else {}
    except Exception:
        return {}


def _save_cache(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


# ── DeepL ──────────────────────────────────────────────────────────────────────

class DeepLQuotaExhausted(Exception):
    pass


def _deepl_active_key() -> str:
    global _deepl_active_idx
    while (_deepl_active_idx < len(_DEEPL_POOL) and
           _DEEPL_POOL[_deepl_active_idx] in _DEEPL_EXHAUSTED):
        _deepl_active_idx += 1
    if _deepl_active_idx >= len(_DEEPL_POOL):
        raise DeepLQuotaExhausted("todas las keys DeepL agotadas")
    return _DEEPL_POOL[_deepl_active_idx]


def deepl_translate(text: str, cache: dict) -> str:
    if not text.strip():
        return text
    ckey = f"deepl|{text}"
    if ckey in cache:
        return cache[ckey]
    api_key = _deepl_active_key()
    payload = urllib.parse.urlencode({
        "text": text, "source_lang": "EN", "target_lang": "ES",
        "preserve_formatting": "1",
    }).encode("utf-8")
    last_err = None
    current_key = api_key
    for delay in [0] + RETRY_BACKOFF:
        if delay:
            time.sleep(delay)
        req = urllib.request.Request(
            DEEPL_API, data=payload,
            headers={
                "Authorization": f"DeepL-Auth-Key {current_key}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            result = data["translations"][0]["text"]
            cache[ckey] = result
            _stats["deepl_chars_used"] += len(text)
            return result
        except urllib.error.HTTPError as e:
            if e.code == 456:
                _DEEPL_EXHAUSTED.add(current_key)
                try:
                    current_key = _deepl_active_key()
                    print(f"  [DeepL 456] key rotada", flush=True)
                    continue
                except DeepLQuotaExhausted:
                    raise
            if e.code == 403:
                raise RuntimeError(f"DeepL 403: {e.read().decode(errors='ignore')[:120]}")
            last_err = e
            continue
        except DeepLQuotaExhausted:
            raise
        except Exception as e:
            last_err = e
            continue
    raise last_err  # type: ignore[misc]


# ── OpenAI ─────────────────────────────────────────────────────────────────────

OPENAI_SYSTEM_PROMPT = (
    "Eres un traductor profesional EN→ES para videojuegos (visual novel).\n"
    "REGLAS:\n"
    "1. Devuelve SOLO la traducción al español, sin explicaciones ni prefijos.\n"
    "2. Conserva EXACTAMENTE los placeholders ZU###Z (no los traduzcas, no los modifiques).\n"
    "3. Conserva signos especiales, mayúsculas de énfasis, puntuación.\n"
    "4. Español neutro, tono natural y conversacional. Usa 'tú'.\n"
    "5. Contenido adulto/explícito: tradúcelo fielmente sin censurar.\n"
    "6. Si el string es solo símbolos/placeholders, devuélvelo sin cambios.\n"
)

OPENAI_BATCH_PROMPT = (
    "Eres un traductor profesional EN→ES para videojuegos (visual novel).\n"
    "Recibes un JSON array de strings en inglés.\n"
    "REGLAS:\n"
    "1. Devuelve SOLO un JSON array de strings del mismo largo y en el mismo orden.\n"
    "2. Conserva EXACTAMENTE los placeholders ZU###Z.\n"
    "3. Español neutro, conversacional. Usa 'tú'.\n"
    "4. Contenido adulto/explícito: tradúcelo fielmente.\n"
    "5. N inputs → exactamente N outputs, mismo orden.\n"
    "6. Si un string es solo símbolos/placeholders, devuélvelo tal cual.\n"
)


class OpenAIBudgetExceeded(Exception):
    pass


_openai_usage_lock = threading.Lock()
_openai_usage_file: Path = ROOT / "tools" / "tl" / ".cache" / "openai_usage.json"


def _load_openai_usage() -> dict:
    if _openai_usage_file.exists():
        try:
            return json.loads(_openai_usage_file.read_text())
        except Exception:
            pass
    return {"total_cost_usd": 0.0, "requests": 0,
            "total_input_tokens": 0, "total_output_tokens": 0}


def _save_openai_usage(u: dict):
    _openai_usage_file.parent.mkdir(parents=True, exist_ok=True)
    _openai_usage_file.write_text(json.dumps(u, indent=2), encoding="utf-8")


def _track_openai(model: str, pt: int, ct: int, budget: float) -> float:
    pin, pout = OPENAI_PRICING.get(model, (1.0, 4.0))
    cost = (pt / 1_000_000) * pin + (ct / 1_000_000) * pout
    with _openai_usage_lock:
        u = _load_openai_usage()
        u["total_cost_usd"] += cost
        u["requests"] += 1
        u["total_input_tokens"] += pt
        u["total_output_tokens"] += ct
        _save_openai_usage(u)
        total = u["total_cost_usd"]
    if total >= budget:
        raise OpenAIBudgetExceeded(
            f"Presupuesto OpenAI ${budget:.2f} superado (gastado ${total:.4f})"
        )
    return total


def openai_translate_batch(texts: list[str], cache: dict, api_key: str,
                            model: str, budget: float) -> list[str]:
    """Traduce un lote de strings (ya tokenizados). Devuelve lista del mismo largo."""
    out: list[str | None] = [None] * len(texts)
    todo_idx: list[int] = []
    todo_texts: list[str] = []

    for i, t in enumerate(texts):
        if not t.strip():
            out[i] = t
            continue
        k = f"openai|{model}|{t}"
        if k in cache:
            out[i] = cache[k]
        else:
            todo_idx.append(i)
            todo_texts.append(t)

    if not todo_texts:
        return out  # type: ignore[return-value]

    # Pre-flight budget check
    u = _load_openai_usage()
    if u["total_cost_usd"] >= budget:
        raise OpenAIBudgetExceeded(
            f"Presupuesto ${budget:.2f} ya alcanzado (gastado ${u['total_cost_usd']:.4f})"
        )

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": OPENAI_BATCH_PROMPT},
            {"role": "user", "content": json.dumps(todo_texts, ensure_ascii=False)},
        ],
        "temperature": 0.2,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "translations",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {"items": {"type": "array", "items": {"type": "string"}}},
                    "required": ["items"],
                    "additionalProperties": False,
                },
            },
        },
    }
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        OPENAI_API, data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    last_err = None
    for delay in [0] + RETRY_BACKOFF:
        if delay:
            time.sleep(delay)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
            usage = data.get("usage", {})
            total_cost = _track_openai(
                model, usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0), budget
            )
            content = data["choices"][0]["message"].get("content", "")
            parsed = json.loads(content).get("items", [])
            if len(parsed) != len(todo_texts):
                raise ValueError(f"mismatch: esperaba {len(todo_texts)}, recibí {len(parsed)}")
            for j, idx in enumerate(todo_idx):
                tr = str(parsed[j])
                if len(tr) >= 2 and tr[0] == tr[-1] and tr[0] in ('"', "'"):
                    tr = tr[1:-1]
                out[idx] = tr
                cache[f"openai|{model}|{todo_texts[j]}"] = tr
            _stats["openai_spent"] = total_cost
            remaining = max(0.0, _stats["openai_budget"] - total_cost)
            print(f"  [openai] batch {len(todo_texts)} strings | gastado ${total_cost:.4f} | resta ${remaining:.4f}", flush=True)
            return out  # type: ignore[return-value]
        except OpenAIBudgetExceeded:
            raise
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise RuntimeError(f"OpenAI HTTP {e.code}: {e.read().decode(errors='ignore')[:200]}")
            if e.code == 429:
                print(f"  [openai 429] rate limit, esperando {delay or 10}s...", flush=True)
            last_err = e
            continue
        except Exception as e:
            last_err = e
            continue
    raise last_err  # type: ignore[misc]


# ── Traducción por item (con fallback deepl→openai por string individual) ─────

def translate_one(text: str, cache: dict, deepl_active: bool,
                  api_key_deepl: str, api_key_openai: str,
                  model: str, budget: float) -> tuple[str, bool]:
    """Traduce un string. Retorna (traducción, deepl_still_active)."""
    if not needs_translation(text):
        return text, deepl_active

    tok, tokens = tokenize_tmp(text)

    if deepl_active:
        try:
            result = deepl_translate(tok, cache)
            return detokenize_tmp(result, tokens), True
        except DeepLQuotaExhausted:
            print("\n  [DeepL] cuota agotada — cambiando a OpenAI para el resto", flush=True)
            deepl_active = False

    # OpenAI single (batch de 1)
    results = openai_translate_batch([tok], cache, api_key_openai, model, budget)
    result = results[0] if results[0] is not None else tok
    return detokenize_tmp(result, tokens), False


# ── Carga/escritura JSON ───────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    txt = path.read_text(encoding="utf-8-sig")  # maneja BOM
    return json.loads(txt)


def write_json(path: Path, data: dict, dry: bool):
    if dry:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, ensure_ascii=False, indent=2)
    path.write_text(content, encoding="utf-8")


# ── Pipeline principal ─────────────────────────────────────────────────────────

def find_translations_dir(game_path: Path) -> Path | None:
    """Busca StreamingAssets/Translations/ dentro del directorio del juego."""
    for data_dir in game_path.glob("*_Data"):
        tl = data_dir / "StreamingAssets" / "Translations"
        if tl.is_dir():
            return tl
    # Fallback: busca directamente
    tl = game_path / "StreamingAssets" / "Translations"
    if tl.is_dir():
        return tl
    return None


def run(args: argparse.Namespace) -> int:
    game_path = Path(args.game_path)
    lang = args.lang
    ntfy_topic = args.ntfy
    dry = args.dry
    model = OPENAI_MODEL
    budget = args.budget
    batch_size = args.batch

    api_key_deepl = os.environ.get("DEEPL_API_KEY", "")
    api_key_openai = os.environ.get("OPENAI_API_KEY", "")

    # Inicializar pool DeepL
    global _DEEPL_POOL, _stats
    pool: list[str] = []
    if api_key_deepl:
        pool.append(api_key_deepl)
    for k, v in os.environ.items():
        if k.startswith("DEEPL_API_KEY") and k != "DEEPL_API_KEY" and v and v not in pool:
            pool.append(v)
    _DEEPL_POOL = pool

    deepl_available = bool(_DEEPL_POOL)
    openai_available = bool(api_key_openai)

    if not deepl_available and not openai_available:
        print("ERROR: sin DEEPL_API_KEY ni OPENAI_API_KEY en .env", file=sys.stderr)
        return 1

    # Verificar cuota DeepL al inicio
    deepl_chars_used = 0
    deepl_chars_limit = 500_000
    if deepl_available:
        usage = deepl_check_usage(_DEEPL_POOL[0])
        if usage:
            deepl_chars_used = usage.get("character_count", 0)
            deepl_chars_limit = usage.get("character_limit", 500_000)
            _stats["deepl_chars_used_prev"] = deepl_chars_used
            _stats["deepl_chars_limit"] = deepl_chars_limit
    _stats["openai_budget"] = budget
    _stats["openai_spent"] = _load_openai_usage().get("total_cost_usd", 0.0)

    # Localizar directorio de traducciones
    tl_dir = find_translations_dir(game_path)
    if not tl_dir:
        print(f"ERROR: no se encontró StreamingAssets/Translations/ en {game_path}", file=sys.stderr)
        return 1

    english_dir = tl_dir / "English"
    target_dir = tl_dir / lang
    lang_file = tl_dir / "languages.json"

    if not english_dir.is_dir():
        print(f"ERROR: no existe {english_dir}", file=sys.stderr)
        return 1

    json_files = sorted(english_dir.glob("*.json"))
    if not json_files:
        print(f"ERROR: no hay .json en {english_dir}", file=sys.stderr)
        return 1

    # Cache
    game_name = game_path.name.replace(" ", "_")
    cache_file = ROOT / "tools" / "tl" / ".cache" / f"unity_json_{game_name}.json"
    cache = _load_cache(cache_file)

    # Contar strings pendientes
    total_strings = 0
    pending_total = 0
    for jf in json_files:
        eng = load_json(jf)
        tgt = load_json(target_dir / jf.name)
        for k, v in eng.items():
            total_strings += 1
            existing = tgt.get(k, "")
            if not existing and needs_translation(v):
                pending_total += 1

    deepl_remaining = deepl_chars_limit - deepl_chars_used
    openai_spent_start = _stats["openai_spent"]
    openai_remaining = max(0.0, budget - openai_spent_start)

    print(f"\n=== TL {game_path.name} → {lang} ===")
    print(f"Archivos: {len(json_files)}  |  Strings: {total_strings}  |  Pendientes: {pending_total}")
    if deepl_available:
        print(f"DeepL: {deepl_chars_used:,}/{deepl_chars_limit:,} chars usados ({deepl_remaining:,} disponibles)")
    print(f"OpenAI: ${openai_spent_start:.4f} gastados | presupuesto ${budget:.2f} | resta ${openai_remaining:.4f}")
    print(f"Provider: {'DeepL' if deepl_available else ''}{' → ' if deepl_available and openai_available else ''}{'OpenAI (fallback)' if openai_available else ''}")
    if dry:
        print("[DRY RUN — no se escriben archivos]")
    print()

    inicio_msg = (
        f"Iniciando: {game_path.name} → {lang}\n"
        f"{pending_total} strings en {len(json_files)} archivos\n"
    )
    if deepl_available:
        inicio_msg += f"DeepL: {deepl_remaining:,} chars disponibles\n"
    inicio_msg += f"OpenAI: ${openai_remaining:.2f} presupuesto disponible"
    ntfy_send(ntfy_topic, inicio_msg, title=f"TL {game_path.name}", tags="gear,hourglass")

    deepl_active = deepl_available
    translated = 0
    files_done = 0
    last_ntfy_pct = -1
    errors = 0
    cost_total = 0.0

    for jf in json_files:
        eng_data = load_json(jf)
        tgt_data = load_json(target_dir / jf.name)

        file_changed = False

        # Recolectar pendientes de este archivo para batch OpenAI
        pending_keys: list[str] = []
        pending_texts: list[str] = []
        pending_tokens: list[list[str]] = []

        for k, v in eng_data.items():
            if not v:
                tgt_data.setdefault(k, v)
                continue
            existing = tgt_data.get(k, "")
            if existing:
                continue  # ya traducido
            if not needs_translation(v):
                tgt_data[k] = v  # copiar tal cual
                file_changed = True
                continue
            tok, tokens = tokenize_tmp(v)
            pending_keys.append(k)
            pending_texts.append(tok)
            pending_tokens.append(tokens)

        if not pending_keys:
            files_done += 1
            continue

        if dry:
            # En dry run solo simulamos el progreso sin llamar APIs
            for k in pending_keys:
                tgt_data[k] = f"[DRY] {eng_data[k][:40]}"
                translated += 1
            files_done += 1
            pct = int(files_done / len(json_files) * 100)
            print(f"[{files_done}/{len(json_files)}] {jf.name} | {translated}/{pending_total} strings | {pct}% [dry]", flush=True)
            continue

        if deepl_active:
            # DeepL: traducir string a string
            for i, (k, tok, tokens) in enumerate(zip(pending_keys, pending_texts, pending_tokens)):
                last_req = time.time()
                try:
                    result = deepl_translate(tok, cache)
                    tgt_data[k] = detokenize_tmp(result, tokens)
                    file_changed = True
                    translated += 1
                except DeepLQuotaExhausted:
                    print(f"\n  [DeepL] cuota agotada en {jf.name} — cambiando a OpenAI", flush=True)
                    deepl_active = False
                    deepl_this_session = _stats["deepl_chars_used"]
                    openai_remaining_now = max(0.0, budget - _stats["openai_spent"])
                    ntfy_send(ntfy_topic,
                              f"DeepL cuota agotada. Continuando con OpenAI.\n"
                              f"{translated}/{pending_total} strings completados\n"
                              f"DeepL usó {deepl_this_session:,} chars esta sesión\n"
                              f"OpenAI: ${_stats['openai_spent']:.4f} gastados | ${openai_remaining_now:.4f} restantes",
                              title=f"TL {game_path.name}", tags="warning", priority="high")
                    # Traducir el resto de este archivo + los siguientes con OpenAI
                    remaining_keys = pending_keys[i:]
                    remaining_texts = pending_texts[i:]
                    remaining_tokens = pending_tokens[i:]
                    for start in range(0, len(remaining_texts), batch_size):
                        chunk_keys = remaining_keys[start:start + batch_size]
                        chunk_texts = remaining_texts[start:start + batch_size]
                        chunk_tokens = remaining_tokens[start:start + batch_size]
                        elapsed = time.time() - last_req
                        if elapsed < RATE_LIMIT_OPENAI:
                            time.sleep(RATE_LIMIT_OPENAI - elapsed)
                        try:
                            results = openai_translate_batch(chunk_texts, cache, api_key_openai, model, budget)
                            for j, (ck, ctokens) in enumerate(zip(chunk_keys, chunk_tokens)):
                                r = results[j]
                                tgt_data[ck] = detokenize_tmp(r if r is not None else chunk_texts[j], ctokens)
                            file_changed = True
                            translated += len(chunk_keys)
                            last_req = time.time()
                        except OpenAIBudgetExceeded as e:
                            print(f"\n  [BUDGET] {e}", flush=True)
                            ntfy_send(ntfy_topic, f"Presupuesto OpenAI alcanzado. {translated}/{pending_total} strings traducidos.",
                                      title=f"TL {game_path.name}", tags="warning,money", priority="high")
                            if not dry and file_changed:
                                write_json(target_dir / jf.name, tgt_data, dry)
                            _save_cache(cache_file, cache)
                            return 2
                        except Exception as e:
                            print(f"\n  [ERR OpenAI] {e}", flush=True)
                            errors += 1
                    break  # salir del loop DeepL de este archivo
                else:
                    elapsed = time.time() - last_req
                    if elapsed < RATE_LIMIT_DEEPL:
                        time.sleep(RATE_LIMIT_DEEPL - elapsed)
        else:
            # OpenAI batch mode para este archivo completo
            last_req = time.time()
            for start in range(0, len(pending_texts), batch_size):
                chunk_keys = pending_keys[start:start + batch_size]
                chunk_texts = pending_texts[start:start + batch_size]
                chunk_tokens = pending_tokens[start:start + batch_size]
                elapsed = time.time() - last_req
                if elapsed < RATE_LIMIT_OPENAI:
                    time.sleep(RATE_LIMIT_OPENAI - elapsed)
                try:
                    results = openai_translate_batch(chunk_texts, cache, api_key_openai, model, budget)
                    for j, (ck, ctokens) in enumerate(zip(chunk_keys, chunk_tokens)):
                        r = results[j]
                        tgt_data[ck] = detokenize_tmp(r if r is not None else chunk_texts[j], ctokens)
                    file_changed = True
                    translated += len(chunk_keys)
                    last_req = time.time()
                except OpenAIBudgetExceeded as e:
                    print(f"\n  [BUDGET] {e}", flush=True)
                    ntfy_send(ntfy_topic, f"Presupuesto OpenAI alcanzado. {translated}/{pending_total} strings traducidos.",
                              title=f"TL {game_path.name}", tags="warning,money", priority="high")
                    if not dry and file_changed:
                        write_json(target_dir / jf.name, tgt_data, dry)
                    _save_cache(cache_file, cache)
                    return 2
                except Exception as e:
                    print(f"\n  [ERR OpenAI] {e}", flush=True)
                    errors += 1

        # Copiar strings no traducibles (vacíos, solo símbolos)
        for k, v in eng_data.items():
            tgt_data.setdefault(k, v)

        if file_changed:
            write_json(target_dir / jf.name, tgt_data, dry)
            _save_cache(cache_file, cache)

        files_done += 1

        # Mostrar progreso en stdout
        pct = int(files_done / len(json_files) * 100)
        msg = f"[{files_done}/{len(json_files)}] {jf.name} | {translated}/{pending_total} strings | {pct}%"
        print(msg, flush=True)

        # ntfy cada 25%
        ntfy_pct = (pct // 25) * 25
        if ntfy_pct > last_ntfy_pct and ntfy_pct > 0:
            last_ntfy_pct = ntfy_pct
            provider_now = "DeepL" if deepl_active else "OpenAI"
            deepl_info = ""
            if deepl_available:
                chars_total_used = _stats["deepl_chars_used_prev"] + _stats["deepl_chars_used"]
                deepl_remaining_now = max(0, _stats["deepl_chars_limit"] - chars_total_used)
                deepl_info = f"DeepL: {deepl_remaining_now:,} chars restantes\n"
            openai_remaining_now = max(0.0, budget - _stats["openai_spent"])
            openai_info = f"OpenAI: ${_stats['openai_spent']:.4f} gastados | ${openai_remaining_now:.4f} restantes"
            ntfy_send(ntfy_topic,
                      f"{ntfy_pct}% — {files_done}/{len(json_files)} archivos | {translated}/{pending_total} strings\n"
                      f"Provider activo: {provider_now}\n{deepl_info}{openai_info}",
                      title=f"TL {game_path.name}", tags="white_check_mark")

    # Actualizar languages.json
    if not dry and lang_file.exists():
        try:
            lang_data = json.loads(lang_file.read_text(encoding="utf-8-sig"))
            langs = lang_data.get("languages", [])
            if lang not in langs:
                langs.append(lang)
                lang_data["languages"] = langs
                lang_file.write_text(json.dumps(lang_data, ensure_ascii=False, indent=4), encoding="utf-8")
                print(f"\nlanguages.json actualizado → {langs}")
        except Exception as e:
            print(f"\n[WARN] No se pudo actualizar languages.json: {e}", flush=True)

    u = _load_openai_usage()
    cost_total = u["total_cost_usd"]
    deepl_session_chars = _stats["deepl_chars_used"]
    chars_total_used = _stats["deepl_chars_used_prev"] + deepl_session_chars
    deepl_remaining_final = max(0, _stats["deepl_chars_limit"] - chars_total_used)

    summary_lines = [
        f"Completado: {translated}/{pending_total} strings en {files_done}/{len(json_files)} archivos",
    ]
    if deepl_available:
        summary_lines.append(f"DeepL: {deepl_session_chars:,} chars usados esta sesión | {deepl_remaining_final:,} restantes de cuota")
    summary_lines.append(f"OpenAI: ${cost_total:.4f} gastados en sesión | ${max(0.0, budget - cost_total):.4f} restantes del presupuesto")
    if errors:
        summary_lines.append(f"Errores: {errors}")

    summary = "\n".join(summary_lines)
    print(f"\n{summary}")
    ntfy_send(ntfy_topic, summary,
              title=f"TL {game_path.name} — Listo",
              tags="white_check_mark,tada", priority="high")

    return 0 if errors == 0 else 1


def main():
    global OPENAI_MODEL
    ap = argparse.ArgumentParser(description="Traducción autónoma Unity JSON — DeepL→OpenAI")
    ap.add_argument("game_path", help="Ruta raíz del juego")
    ap.add_argument("--lang", default="Spanish", help="Carpeta destino (default: Spanish)")
    ap.add_argument("--ntfy", default=os.environ.get("NTFY_TOPIC", NTFY_DEFAULT_TOPIC),
                    help="Topic ntfy.sh (default: koichi_agenda_2026)")
    ap.add_argument("--budget", type=float,
                    default=float(os.environ.get("OPENAI_BUDGET_USD", "1.50")),
                    help="Tope gasto OpenAI USD (default: 1.50)")
    ap.add_argument("--batch", type=int, default=OPENAI_BATCH_SIZE,
                    help=f"Strings por request OpenAI (default: {OPENAI_BATCH_SIZE})")
    ap.add_argument("--model", default=OPENAI_MODEL,
                    help=f"Modelo OpenAI (default: {OPENAI_MODEL})")
    ap.add_argument("--dry", action="store_true", help="No escribir archivos")
    ap.add_argument("--quiet", action="store_true", help="Sin notificaciones ntfy")
    args = ap.parse_args()

    if args.quiet:
        args.ntfy = ""
    OPENAI_MODEL = args.model

    sys.exit(run(args))


if __name__ == "__main__":
    main()
