"""
Traduce archivos .rpy (formatos dialogo y strings) via MyMemory API.

Flujo por bloque:
  1. Tokenizar tags/variables/placeholders -> sentinelas ZT000Z
  2. Consultar MyMemory (con cache JSON para no repetir)
  3. Detokenizar
  4. Aplicar glosario (terminos con 'target' != "")
  5. Escribir en la linea destino

Uso:
  python translate.py <archivo.rpy>                # traduce in-place (con backup .bak)
  python translate.py <archivo.rpy> --dry          # imprime sin escribir
  python translate.py <archivo.rpy> --limit 50     # solo primeros 50 bloques vacios
  python translate.py <archivo.rpy> --email a@b.c  # sube cuota a ~10k palabras/dia

Cache: tools/tl/.cache/mymemory.json
"""
import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from _env import load_env  # type: ignore
load_env()
from lib_rpy import (  # type: ignore
    parse_dialogue_file, parse_strings_file,
    tokenize, detokenize, write_target_line,
)
from _env import load_env  # type: ignore
load_env()

CACHE_DIR = ROOT / ".cache"
CACHE_DIR.mkdir(exist_ok=True)
CACHE_MM = CACHE_DIR / "mymemory.json"
CACHE_DEEPL = CACHE_DIR / "deepl.json"
CACHE_GEMINI = CACHE_DIR / "gemini.json"
CACHE_OPENAI = CACHE_DIR / "openai.json"
OPENAI_USAGE_FILE = CACHE_DIR / "openai_usage.json"
GLOSSARY_FILE = ROOT / "tl-es-glossary.json"

MM_API = "https://api.mymemory.translated.net/get"
DEEPL_API = "https://api-free.deepl.com/v2/translate"  # :fx keys = free tier

# Pool de keys DeepL para rotación automática en 456 (cuota agotada).
# Se inicializa desde main() leyendo DEEPL_API_KEY, DEEPL_API_KEY_2..N del env.
DEEPL_KEY_POOL: list = []           # lista ordenada de keys
DEEPL_EXHAUSTED: set = set()        # keys que devolvieron 456
_DEEPL_ACTIVE_IDX = 0

def deepl_active_key() -> str:
    """Devuelve la key activa (no exhausta) actual del pool."""
    global _DEEPL_ACTIVE_IDX
    while _DEEPL_ACTIVE_IDX < len(DEEPL_KEY_POOL) and DEEPL_KEY_POOL[_DEEPL_ACTIVE_IDX] in DEEPL_EXHAUSTED:
        _DEEPL_ACTIVE_IDX += 1
    if _DEEPL_ACTIVE_IDX >= len(DEEPL_KEY_POOL):
        raise RuntimeError(f"DeepL: todas las keys del pool agotadas ({len(DEEPL_EXHAUSTED)}/{len(DEEPL_KEY_POOL)} con 456)")
    return DEEPL_KEY_POOL[_DEEPL_ACTIVE_IDX]

def _deepl_next_key(current: str) -> str:
    """Marca la key actual como agotada y devuelve la siguiente activa."""
    DEEPL_EXHAUSTED.add(current)
    return deepl_active_key()
GEMINI_API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Default: gemini-2.5-flash-lite (free tier: 15 RPM, 1000 RPD, 250k TPM).
# Calidad ligeramente menor que 2.5-flash pero suficiente para VN; cuota 4x mayor.
# Para upgrade a calidad: --gemini-model gemini-2.5-flash (250 RPD, 10 RPM).
GEMINI_MODEL = "gemini-2.5-flash-lite"
GEMINI_BATCH_SIZE = 25  # strings por request en modo gemini batch
LANG_PAIR = "en|es"
RATE_LIMIT_SEC_MM = 1.1
RATE_LIMIT_SEC_DEEPL = 0.1
RATE_LIMIT_SEC_GEMINI = 4.1  # 15 RPM en gemini-2.5-flash-lite (~4s entre requests)
MAX_CONSEC_ERRORS = 3
RETRY_BACKOFF = [2, 5, 15]

# ---- OpenAI ----
OPENAI_API = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = "gpt-4.1-nano"  # default mas barato: $0.10/1M in, $0.40/1M out
OPENAI_BATCH_SIZE = 25
RATE_LIMIT_SEC_OPENAI = 0.3
OPENAI_TIMEOUT_SEC = int(os.environ.get("OPENAI_TIMEOUT_SEC", "120"))
# Pricing USD por 1M tokens (input, output). Actualizar si OpenAI cambia precios.
OPENAI_PRICING = {
    "gpt-4.1-nano":         (0.10, 0.40),
    "gpt-4.1-nano-2025-04-14": (0.10, 0.40),
    "gpt-4.1-mini":         (0.40, 1.60),
    "gpt-4.1-mini-2025-04-14": (0.40, 1.60),
    "gpt-4.1":              (2.00, 8.00),
    "gpt-4o-mini":          (0.15, 0.60),
    "gpt-4o-mini-2024-07-18": (0.15, 0.60),
    "gpt-4o":               (2.50, 10.00),
}
# Tracker global de gasto por sesion (persiste a disco entre runs)
OPENAI_BUDGET_USD = float(os.environ.get("OPENAI_BUDGET_USD", "0.50"))


class OpenAIBudgetExceeded(Exception):
    pass


def _openai_load_usage() -> dict:
    if OPENAI_USAGE_FILE.exists():
        try:
            return json.loads(OPENAI_USAGE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"total_input_tokens": 0, "total_output_tokens": 0, "total_cost_usd": 0.0, "requests": 0}


def _openai_save_usage(u: dict):
    OPENAI_USAGE_FILE.write_text(json.dumps(u, indent=2), encoding="utf-8")


def _openai_track(model: str, prompt_tokens: int, completion_tokens: int) -> tuple:
    """Registra uso, devuelve (cost_added_usd, total_cost_usd)."""
    pin, pout = OPENAI_PRICING.get(model, (1.0, 4.0))  # fallback conservador
    cost = (prompt_tokens / 1_000_000) * pin + (completion_tokens / 1_000_000) * pout
    u = _openai_load_usage()
    u["total_input_tokens"] += prompt_tokens
    u["total_output_tokens"] += completion_tokens
    u["total_cost_usd"] += cost
    u["requests"] += 1
    _openai_save_usage(u)
    return cost, u["total_cost_usd"]


def _load(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        txt = p.read_text(encoding="utf-8")
        if not txt.strip():
            return {}
        return json.loads(txt)
    except Exception:
        # Keep pipeline running even if a cache file was left corrupted.
        return {}

def _save(p: Path, data: dict):
    # Atomic write: write to temp file in same directory then replace.
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_name, p)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.remove(tmp_name)
            except OSError:
                pass

def load_cache(provider: str) -> dict:
    if provider == "deepl":
        return _load(CACHE_DEEPL)
    if provider == "gemini":
        return _load(CACHE_GEMINI)
    if provider == "openai":
        return _load(CACHE_OPENAI)
    return _load(CACHE_MM)

def save_cache(cache: dict, provider: str):
    if provider == "deepl":
        _save(CACHE_DEEPL, cache)
    elif provider == "gemini":
        _save(CACHE_GEMINI, cache)
    elif provider == "openai":
        _save(CACHE_OPENAI, cache)
    else:
        _save(CACHE_MM, cache)

def load_glossary() -> dict:
    if not GLOSSARY_FILE.exists():
        return {}
    data = json.loads(GLOSSARY_FILE.read_text(encoding="utf-8"))
    # Construir mapa source->target filtrando vacios
    mapping = {}
    for section in ("characters", "terms"):
        for key, entry in data.get(section, {}).items():
            src = entry.get("source", key)
            tgt = entry.get("target", "")
            # Incluir tambien src==tgt: sirve para PROTEGER del MT
            # ("Linea" -> "Linea" evita que MT lo convierta en "línea").
            if tgt:
                mapping[src] = tgt
    return mapping

def protect_glossary(text: str, mapping: dict) -> tuple[str, list[str]]:
    """Reemplaza terminos del glosario por sentinelas ANTES del MT.
    Devuelve (texto_protegido, lista_targets_en_orden).
    Los sentinelas usan formato ZG000Z distinto de los de tokenize (ZT)."""
    # Ordenar por longitud descendente para que 'Precepts' matchee antes que 'Precept'
    targets: list[str] = []
    items = sorted(mapping.items(), key=lambda kv: -len(kv[0]))
    for src, tgt in items:
        pat = re.compile(rf"\b{re.escape(src)}\b")
        def repl(_m, t=tgt):
            idx = len(targets)
            targets.append(t)
            return f"ZG{idx:03d}Z"
        text = pat.sub(repl, text)
    return text, targets

def restore_glossary(text: str, targets: list[str]) -> str:
    for idx, tgt in enumerate(targets):
        pat = re.compile(rf"[Zz]\s*[Gg]\s*0*{idx}\s*[Zz]")
        text = pat.sub(lambda _m, t=tgt: t, text)
    return text

def mm_translate(text: str, cache: dict, email: str = "") -> str:
    """Traduce un string via MyMemory. Cachea por texto exacto.
    Reintenta con backoff antes de propagar la excepcion."""
    key = f"{LANG_PAIR}|{text}"
    if key in cache:
        return cache[key]
    if not text.strip():
        return text
    params = {"q": text, "langpair": LANG_PAIR}
    if email:
        params["de"] = email
    url = f"{MM_API}?{urllib.parse.urlencode(params)}"
    last_err = None
    for delay in [0] + RETRY_BACKOFF:
        if delay:
            time.sleep(delay)
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            translated = data.get("responseData", {}).get("translatedText", "")
            status = data.get("responseStatus")
            if status != 200 and status != "200":
                # 429 (rate limit/quota) propagar para abortar limpio
                if str(status).startswith("429") or "QUOTA" in str(data.get("responseDetails", "")).upper():
                    raise RuntimeError(f"MyMemory cuota/rate-limit: {data.get('responseDetails')}")
                print(f"  [warn] status={status} for: {text[:60]!r}")
            cache[key] = translated
            return translated
        except Exception as e:
            last_err = e
            continue
    raise last_err  # type: ignore[misc]


def deepl_translate(text: str, cache: dict, api_key: str) -> str:
    """DeepL backend (free tier, key acaba en :fx).
    Cache por texto. Reintenta con backoff. En 456 (cuota) rota a la siguiente key
    del pool si hay disponibles, sino aborta."""
    if not text.strip():
        return text
    key = f"deepl|{text}"
    if key in cache:
        return cache[key]
    payload = urllib.parse.urlencode({
        "text": text,
        "source_lang": "EN",
        "target_lang": "ES",
        "preserve_formatting": "1",
    }).encode("utf-8")
    current_key = deepl_active_key() if DEEPL_KEY_POOL else api_key
    last_err = None
    for delay in [0] + RETRY_BACKOFF:
        if delay:
            time.sleep(delay)
        req = urllib.request.Request(
            DEEPL_API,
            data=payload,
            headers={
                "Authorization": f"DeepL-Auth-Key {current_key}",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "tl-fts/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            translated = data["translations"][0]["text"]
            cache[key] = translated
            return translated
        except urllib.error.HTTPError as e:
            if e.code == 403:
                raise RuntimeError(f"DeepL HTTP 403: {e.read().decode(errors='ignore')[:200]}")
            if e.code == 456:
                # Cuota agotada: rotar a la siguiente key del pool si hay
                body = e.read().decode(errors='ignore')[:200]
                try:
                    new_key = _deepl_next_key(current_key)
                    masked_old = current_key[:8] + "..."
                    masked_new = new_key[:8] + "..."
                    print(f"\n  [DeepL 456] key {masked_old} agotada, rotando a {masked_new}", flush=True)
                    current_key = new_key
                    continue
                except RuntimeError as rerr:
                    raise RuntimeError(f"DeepL HTTP 456 (todas las keys agotadas): {body} | {rerr}")
            last_err = e
            continue
        except Exception as e:
            last_err = e
            continue
    raise last_err  # type: ignore[misc]


GEMINI_SYSTEM_PROMPT = (
    "Eres un traductor profesional EN→ES para novelas visuales adultas (Ren'Py).\n"
    "REGLAS ESTRICTAS:\n"
    "1. Devuelve SOLO la traducción al español, sin explicaciones, sin comillas extra, sin prefijos.\n"
    "2. Conserva EXACTAMENTE los placeholders del tipo ZT000Z, ZT001Z, ZG000Z (no los traduzcas, no los modifiques).\n"
    "3. Conserva las etiquetas Ren'Py: {i}...{/i}, {b}...{/b}, {color=...}, {size=...}, {/color}, {/size}, {nw}, {p}, {w}, {fast}.\n"
    "4. Conserva los \\n y los espacios literales.\n"
    "5. Conserva las comillas escapadas \\\" tal cual.\n"
    "6. Registro: español neutro, tono natural y conversacional. Usa 'tú' (no 'vos'/'usted' a menos que el contexto lo pida).\n"
    "7. Contenido adulto/explícito: tradúcelo fielmente sin censurar ni suavizar.\n"
    "8. Si recibes un texto vacío o solo placeholders, devuélvelo tal cual.\n"
)

GEMINI_BATCH_SYSTEM_PROMPT = (
    "Eres un traductor profesional EN→ES para novelas visuales adultas (Ren'Py).\n"
    "Vas a recibir un JSON array de strings en inglés.\n"
    "REGLAS ESTRICTAS:\n"
    "1. Devuelve SOLO un JSON array de strings, del mismo largo y en el mismo orden.\n"
    "2. Cada string de salida debe ser únicamente la traducción del string correspondiente.\n"
    "3. Conserva EXACTAMENTE los placeholders del tipo ZT000Z, ZT001Z, ZG000Z (no los traduzcas, no los modifiques, no los reordenes).\n"
    "4. Conserva las etiquetas Ren'Py: {i}...{/i}, {b}...{/b}, {color=...}, {size=...}, {/color}, {/size}, {nw}, {p}, {w}, {fast}.\n"
    "5. Conserva los \\n y los espacios literales.\n"
    "6. Conserva las comillas escapadas \\\" tal cual.\n"
    "7. NUNCA unas ni dividas elementos: N inputs => exactamente N outputs en el mismo orden.\n"
    "8. Registro: español neutro, tono natural y conversacional. Usa 'tú' (no 'vos'/'usted' salvo que el contexto lo pida).\n"
    "9. Contenido adulto/explícito: tradúcelo fielmente sin censurar ni suavizar.\n"
    "10. Si un string viene vacío o es solo placeholders/símbolos, devuélvelo tal cual.\n"
)

class GeminiBlocked(Exception):
    """Gemini se negó a traducir (PROHIBITED_CONTENT, SAFETY, RECITATION).
    No es error transitorio: intentar fallback a otro provider."""
    pass


def gemini_translate(text: str, cache: dict, api_key: str, model: str = GEMINI_MODEL) -> str:
    """Gemini backend (free tier).
    Cache por texto. Reintenta con backoff. Aborta en 401/403 (auth)."""
    if not text.strip():
        return text
    key = f"gemini|{model}|{text}"
    if key in cache:
        return cache[key]
    body = {
        "system_instruction": {"parts": [{"text": GEMINI_SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": text}]}],
        "generationConfig": {
            "temperature": 0.2,
            "topP": 0.95,
            "maxOutputTokens": 2048,
            "responseMimeType": "text/plain",
        },
        "safetySettings": [
            {"category": c, "threshold": "BLOCK_NONE"}
            for c in (
                "HARM_CATEGORY_HARASSMENT",
                "HARM_CATEGORY_HATE_SPEECH",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "HARM_CATEGORY_DANGEROUS_CONTENT",
                "HARM_CATEGORY_CIVIC_INTEGRITY",
            )
        ],
    }
    url = GEMINI_API.format(model=model) + f"?key={urllib.parse.quote(api_key)}"
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "tl-fts/1.0"},
    )
    last_err = None
    for delay in [0] + RETRY_BACKOFF:
        if delay:
            time.sleep(delay)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            cands = data.get("candidates") or []
            if not cands:
                pf = data.get("promptFeedback", {})
                reason = pf.get("blockReason", "")
                if reason in ("PROHIBITED_CONTENT", "SAFETY", "RECITATION", "BLOCKLIST"):
                    raise GeminiBlocked(f"prompt blocked: {reason}")
                raise RuntimeError(f"Gemini sin candidatos: {pf}")
            finish = cands[0].get("finishReason", "")
            parts = cands[0].get("content", {}).get("parts") or []
            translated = "".join(p.get("text", "") for p in parts).strip()
            if not translated and finish in ("SAFETY", "PROHIBITED_CONTENT", "RECITATION", "BLOCKLIST"):
                raise GeminiBlocked(f"response blocked: {finish}")
            # Quitar comillas externas si el modelo las añadió pese al prompt
            if len(translated) >= 2 and translated[0] == translated[-1] and translated[0] in ('"', "'"):
                translated = translated[1:-1]
            cache[key] = translated
            return translated
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise RuntimeError(f"Gemini HTTP {e.code}: {e.read().decode(errors='ignore')[:300]}")
            last_err = e
            continue
        except GeminiBlocked:
            raise  # no reintentar, propagar para fallback
        except Exception as e:
            last_err = e
            continue
    raise last_err  # type: ignore[misc]


class BatchSizeMismatch(Exception):
    """El batch devolvió una cantidad distinta de items que la enviada."""
    pass


def openai_translate_batch(tokenized_list: list, cache: dict, api_key: str,
                           model: str = OPENAI_MODEL) -> list:
    """Traduce un lote vía OpenAI Chat Completions con response_format json_schema.

    - Items vacíos o cacheados no consumen tokens.
    - Aborta el run si el gasto acumulado supera OPENAI_BUDGET_USD.
    - Si la respuesta no tiene N items, lanza BatchSizeMismatch.
    """
    out: list = [None] * len(tokenized_list)  # type: ignore[list-item]
    todo_idx: list = []
    todo_texts: list = []
    for i, t in enumerate(tokenized_list):
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
        return out

    # Pre-flight: si ya pasamos el budget, abortar antes de gastar
    usage = _openai_load_usage()
    if usage["total_cost_usd"] >= OPENAI_BUDGET_USD:
        raise OpenAIBudgetExceeded(
            f"Presupuesto OpenAI ${OPENAI_BUDGET_USD:.4f} alcanzado. "
            f"Gasto actual: ${usage['total_cost_usd']:.4f}. "
            f"Sube OPENAI_BUDGET_USD en .env para continuar."
        )

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": GEMINI_BATCH_SYSTEM_PROMPT},
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
                    "properties": {
                        "items": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["items"],
                    "additionalProperties": False,
                },
            },
        },
    }
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        OPENAI_API,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "tl-fts/1.0",
        },
    )
    last_err = None
    for delay in [0] + RETRY_BACKOFF:
        if delay:
            time.sleep(delay)
        try:
            with urllib.request.urlopen(req, timeout=OPENAI_TIMEOUT_SEC) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            usage_obj = data.get("usage") or {}
            pt = int(usage_obj.get("prompt_tokens", 0))
            ct = int(usage_obj.get("completion_tokens", 0))
            cost_added, cost_total = _openai_track(model, pt, ct)
            content = data["choices"][0]["message"].get("content", "")
            try:
                parsed_obj = json.loads(content)
                parsed = parsed_obj.get("items", [])
            except json.JSONDecodeError as je:
                raise BatchSizeMismatch(f"respuesta no es JSON: {je}; raw[:200]={content[:200]!r}")
            if not isinstance(parsed, list):
                raise BatchSizeMismatch(f"items no es lista: type={type(parsed).__name__}")
            if len(parsed) != len(todo_texts):
                raise BatchSizeMismatch(f"esperaba {len(todo_texts)} items, recibí {len(parsed)}")
            for j, idx in enumerate(todo_idx):
                tr = parsed[j] if isinstance(parsed[j], str) else str(parsed[j])
                if len(tr) >= 2 and tr[0] == tr[-1] and tr[0] in ('"', "'"):
                    tr = tr[1:-1]
                out[idx] = tr
                cache[f"openai|{model}|{todo_texts[j]}"] = tr
            # Log gasto en cada batch para visibilidad
            print(f"  [openai] +${cost_added:.5f} (in={pt} out={ct}) | total=${cost_total:.4f} / ${OPENAI_BUDGET_USD:.2f}", flush=True)
            if cost_total >= OPENAI_BUDGET_USD:
                raise OpenAIBudgetExceeded(
                    f"Presupuesto ${OPENAI_BUDGET_USD:.4f} superado tras este batch (gasto=${cost_total:.4f}). Abortando."
                )
            return out
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise RuntimeError(f"OpenAI HTTP {e.code}: {e.read().decode(errors='ignore')[:300]}")
            if e.code == 429:
                body_err = e.read().decode(errors='ignore')[:300]
                # Rate limit (no quota): backoff corto y reintentar
                print(f"\n  [openai 429] {body_err[:120]}; retry in {delay or 2}s", flush=True)
                last_err = e
                continue
            last_err = e
            continue
        except BatchSizeMismatch:
            raise
        except OpenAIBudgetExceeded:
            raise
        except Exception as e:
            last_err = e
            continue
    raise last_err  # type: ignore[misc]


def translate_batch_openai(srcs: list, cache: dict, glossary: dict, api_key: str,
                            model: str) -> list:
    """Pipeline batch para provider=openai (mismo patrón que Gemini)."""
    if not srcs:
        return []
    metas = []
    prepared = []
    for src in srcs:
        if not src.strip():
            prepared.append(src)
            metas.append(([], {}))
            continue
        glossed, g_targets = protect_glossary(src, glossary)
        tokenized, t_mapping = tokenize(glossed)
        prepared.append(tokenized)
        metas.append((g_targets, t_mapping))
    translated_tokenized = openai_translate_batch(prepared, cache, api_key, model)
    results = []
    for i, src in enumerate(srcs):
        g_targets, t_mapping = metas[i]
        tr_tok = translated_tokenized[i]
        if tr_tok is None:
            tr_tok = src
        detok = detokenize(tr_tok, t_mapping)
        out_text = restore_glossary(detok, g_targets)
        results.append(out_text)
    return results


def gemini_translate_batch(tokenized_list: list, cache: dict, api_key: str, model: str = GEMINI_MODEL) -> list:
    """Traduce un lote de strings ya tokenizados en una sola request.

    - Usa responseSchema=ARRAY of STRING para forzar JSON array bien formado.
    - Items vacíos o ya cacheados se resuelven sin gastar request.
    - Si la respuesta no tiene N items, lanza BatchSizeMismatch (caller debe fallback).
    - Si Gemini bloquea, lanza GeminiBlocked.
    """
    out: list = [None] * len(tokenized_list)  # type: ignore[list-item]
    todo_idx: list = []
    todo_texts: list = []
    for i, t in enumerate(tokenized_list):
        if not t.strip():
            out[i] = t
            continue
        k = f"gemini|{model}|{t}"
        if k in cache:
            out[i] = cache[k]
        else:
            todo_idx.append(i)
            todo_texts.append(t)
    if not todo_texts:
        return out

    user_payload = json.dumps(todo_texts, ensure_ascii=False)
    body = {
        "system_instruction": {"parts": [{"text": GEMINI_BATCH_SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_payload}]}],
        "generationConfig": {
            "temperature": 0.2,
            "topP": 0.95,
            "maxOutputTokens": 8192,
            "responseMimeType": "application/json",
            "responseSchema": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
        "safetySettings": [
            {"category": c, "threshold": "BLOCK_NONE"}
            for c in (
                "HARM_CATEGORY_HARASSMENT",
                "HARM_CATEGORY_HATE_SPEECH",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "HARM_CATEGORY_DANGEROUS_CONTENT",
                "HARM_CATEGORY_CIVIC_INTEGRITY",
            )
        ],
    }
    url = GEMINI_API.format(model=model) + f"?key={urllib.parse.quote(api_key)}"
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "tl-fts/1.0"},
    )
    last_err = None
    for delay in [0] + RETRY_BACKOFF:
        if delay:
            time.sleep(delay)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            cands = data.get("candidates") or []
            if not cands:
                pf = data.get("promptFeedback", {})
                reason = pf.get("blockReason", "")
                if reason in ("PROHIBITED_CONTENT", "SAFETY", "RECITATION", "BLOCKLIST"):
                    raise GeminiBlocked(f"batch prompt blocked: {reason}")
                raise RuntimeError(f"Gemini batch sin candidatos: {pf}")
            finish = cands[0].get("finishReason", "")
            parts = cands[0].get("content", {}).get("parts") or []
            raw = "".join(p.get("text", "") for p in parts).strip()
            if not raw and finish in ("SAFETY", "PROHIBITED_CONTENT", "RECITATION", "BLOCKLIST"):
                raise GeminiBlocked(f"batch response blocked: {finish}")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as je:
                raise BatchSizeMismatch(f"respuesta no es JSON válido: {je}; raw[:200]={raw[:200]!r}")
            if not isinstance(parsed, list):
                raise BatchSizeMismatch(f"respuesta no es lista: type={type(parsed).__name__}")
            if len(parsed) != len(todo_texts):
                raise BatchSizeMismatch(f"esperaba {len(todo_texts)} items, recibí {len(parsed)}")
            for j, idx in enumerate(todo_idx):
                tr = parsed[j] if isinstance(parsed[j], str) else str(parsed[j])
                # Quitar comillas externas si el modelo las añadió
                if len(tr) >= 2 and tr[0] == tr[-1] and tr[0] in ('"', "'"):
                    tr = tr[1:-1]
                out[idx] = tr
                cache[f"gemini|{model}|{todo_texts[j]}"] = tr
            return out
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise RuntimeError(f"Gemini HTTP {e.code}: {e.read().decode(errors='ignore')[:300]}")
            if e.code == 429:
                # Cuota por minuto agotada: esperar reset (~65s) antes de reintentar
                print(f"\n  [429] cuota agotada, esperando 65s para reset...", flush=True)
                time.sleep(65)
                last_err = e
                continue
            last_err = e
            continue
        except (GeminiBlocked, BatchSizeMismatch):
            raise  # propagar para fallback per-item
        except Exception as e:
            last_err = e
            continue
    raise last_err  # type: ignore[misc]


def translate_batch_gemini(srcs: list, gem_cache: dict, glossary: dict, api_key: str,
                           model: str, fallback_deepl_key: str, email: str) -> list:
    """Pipeline batch para provider=gemini.

    Aplica glossary+tokenize por item, manda el batch tokenizado a Gemini,
    luego detokeniza+restaura glossary por item. Si el batch falla con
    BatchSizeMismatch/GeminiBlocked/JSON error, hace fallback per-item al
    flujo single (que a su vez tiene fallback a DeepL/MyMemory).
    """
    if not srcs:
        return []
    metas = []
    prepared = []
    for src in srcs:
        if not src.strip():
            prepared.append(src)
            metas.append(([], {}))
            continue
        glossed, g_targets = protect_glossary(src, glossary)
        tokenized, t_mapping = tokenize(glossed)
        prepared.append(tokenized)
        metas.append((g_targets, t_mapping))
    try:
        translated_tokenized = gemini_translate_batch(prepared, gem_cache, api_key, model)
    except (BatchSizeMismatch, GeminiBlocked, RuntimeError) as e:
        print(f"\n  [batch->single] {type(e).__name__}: {str(e)[:120]}")
        translated_tokenized = []
        for i, src in enumerate(srcs):
            if not src.strip():
                translated_tokenized.append(src)
                continue
            try:
                t = gemini_translate(prepared[i], gem_cache, api_key, model)
            except GeminiBlocked:
                # fallback per item via translate_text (DeepL si hay key, sino MM)
                t_full = translate_text(src, gem_cache, glossary, "gemini", email, api_key, fallback_deepl_key)
                # translate_text ya devuelve el resultado final; saltarse el detok
                # marcamos None y rellenamos abajo.
                translated_tokenized.append(None)  # sentinel
                metas[i] = ("__DONE__", t_full)  # type: ignore[assignment]
                # rate-limit manual entre items single
                time.sleep(RATE_LIMIT_SEC_GEMINI)
                continue
            translated_tokenized.append(t)
            time.sleep(RATE_LIMIT_SEC_GEMINI)

    results = []
    for i, src in enumerate(srcs):
        meta = metas[i]
        if isinstance(meta, tuple) and meta and meta[0] == "__DONE__":
            results.append(meta[1])  # ya viene listo del fallback
            continue
        g_targets, t_mapping = meta  # type: ignore[misc]
        tr_tok = translated_tokenized[i]
        if tr_tok is None:
            tr_tok = src  # último recurso
        detok = detokenize(tr_tok, t_mapping)
        out = restore_glossary(detok, g_targets)
        out = out.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")
        results.append(out)
    return results


def translate_text(src: str, cache: dict, glossary: dict, provider: str, email: str, api_key: str, fallback_deepl_key: str = "") -> str:
    """Pipeline completo. provider in {'mymemory','deepl','gemini'}.

    Si provider=gemini y Gemini bloquea (PROHIBITED_CONTENT/SAFETY), intenta
    fallback a DeepL si hay fallback_deepl_key. Si no, fallback a MyMemory.
    """
    if not src.strip():
        return src
    glossed, g_targets = protect_glossary(src, glossary)
    tokenized, t_mapping = tokenize(glossed)
    if provider == "deepl":
        mt_out = deepl_translate(tokenized, cache, api_key=api_key)
    elif provider == "gemini":
        try:
            mt_out = gemini_translate(tokenized, cache, api_key=api_key)
        except GeminiBlocked as e:
            print(f"\n  [fallback] Gemini bloqueó {src[:40]!r} ({e}); usando {'deepl' if fallback_deepl_key else 'mymemory'}")
            if fallback_deepl_key:
                deepl_cache = _load(CACHE_DEEPL)
                mt_out = deepl_translate(tokenized, deepl_cache, api_key=fallback_deepl_key)
                _save(CACHE_DEEPL, deepl_cache)
            else:
                mm_cache = _load(CACHE_MM)
                mt_out = mm_translate(tokenized, mm_cache, email=email)
                _save(CACHE_MM, mm_cache)
            # Cachear el resultado en gemini.json para no reintentar
            cache[f"gemini|{GEMINI_MODEL}|{tokenized}"] = mt_out
    else:
        mt_out = mm_translate(tokenized, cache, email=email)
    detok = detokenize(mt_out, t_mapping)
    out = restore_glossary(detok, g_targets)
    out = out.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")
    return out

def process_dialogue(path: Path, limit: int, dry: bool, provider: str, email: str, api_key: str, fallback_deepl_key: str = "", batch_size: int = GEMINI_BATCH_SIZE, gemini_model: str = GEMINI_MODEL, openai_model: str = OPENAI_MODEL):
    blocks = parse_dialogue_file(str(path))
    pending = [b for b in blocks if not b.current_target.strip()]
    print(f"bloques totales: {len(blocks)} | vacios: {len(pending)}")
    if limit:
        pending = pending[:limit]
        print(f"limitando a {len(pending)}")

    cache = load_cache(provider)
    glossary = load_glossary()
    print(f"provider: {provider} | glosario: {len(glossary)} entradas" + (f" | model: {gemini_model} | batch: {batch_size}" if provider == "gemini" else "") + (f" | model: {openai_model} | batch: {batch_size} | budget=${OPENAI_BUDGET_USD:.2f}" if provider == "openai" else ""))
    rate = {"deepl": RATE_LIMIT_SEC_DEEPL, "gemini": RATE_LIMIT_SEC_GEMINI, "openai": RATE_LIMIT_SEC_OPENAI}.get(provider, RATE_LIMIT_SEC_MM)

    if not dry:
        bak = path.with_suffix(path.suffix + ".bak")
        if not bak.exists():
            shutil.copy2(path, bak)
            print(f"backup: {bak}")

    with path.open(encoding="utf-8") as fh:
        lines = fh.readlines()

    done = 0
    consec_err = 0

    if provider == "openai":
        last_req = 0.0
        for start in range(0, len(pending), batch_size):
            chunk = pending[start:start + batch_size]
            elapsed = time.time() - last_req
            if elapsed < rate:
                time.sleep(rate - elapsed)
            try:
                results = translate_batch_openai(
                    [b.source for b in chunk], cache, glossary, api_key, openai_model,
                )
                consec_err = 0
            except OpenAIBudgetExceeded as e:
                print(f"\n  [BUDGET] {e}")
                save_cache(cache, provider)
                if not dry:
                    path.write_text("".join(lines), encoding="utf-8")
                return
            except Exception as e:
                consec_err += 1
                print(f"\n  [ERR batch {consec_err}/{MAX_CONSEC_ERRORS}] @{start}: {e}")
                last_req = time.time()
                if consec_err >= MAX_CONSEC_ERRORS:
                    print("  [ABORT] demasiados fallos consecutivos. Guardando y saliendo.")
                    save_cache(cache, provider)
                    if not dry:
                        path.write_text("".join(lines), encoding="utf-8")
                    return
                time.sleep(15)
                continue
            last_req = time.time()
            for b, tr in zip(chunk, results):
                lines[b.line_target] = write_target_line(lines[b.line_target], tr)
                done += 1
            save_cache(cache, provider)
            if not dry:
                path.write_text("".join(lines), encoding="utf-8")
            sample = chunk[0].source[:40]
            sample_tr = results[0][:40] if results else ""
            msg = f"  [{done}/{len(pending)}] batch+{len(chunk)} {sample!r} -> {sample_tr!r}"
            print(msg.ljust(140)[:140], flush=True)
        print()
        save_cache(cache, provider)
        if not dry:
            path.write_text("".join(lines), encoding="utf-8")
        u = _openai_load_usage()
        print(f"terminado: {done} traducidos | gasto sesion total: ${u['total_cost_usd']:.4f} ({u['requests']} reqs, in={u['total_input_tokens']} out={u['total_output_tokens']})")
        return

    if provider == "gemini":
        # Modo batch: agrupar pendientes en chunks de batch_size
        last_req = 0.0
        for start in range(0, len(pending), batch_size):
            chunk = pending[start:start + batch_size]
            elapsed = time.time() - last_req
            if elapsed < rate:
                time.sleep(rate - elapsed)
            try:
                results = translate_batch_gemini(
                    [b.source for b in chunk], cache, glossary,
                    api_key, gemini_model, fallback_deepl_key, email,
                )
                consec_err = 0
            except Exception as e:
                consec_err += 1
                print(f"\n  [ERR batch {consec_err}/{MAX_CONSEC_ERRORS}] @{start}: {e}")
                last_req = time.time()
                if consec_err >= MAX_CONSEC_ERRORS:
                    print("  [ABORT] demasiados fallos consecutivos. Guardando y saliendo.")
                    save_cache(cache, provider)
                    if not dry:
                        path.write_text("".join(lines), encoding="utf-8")
                    return
                # Backoff defensivo: esperar 30s tras error antes de reintentar el mismo chunk
                time.sleep(30)
                continue
            last_req = time.time()
            for b, tr in zip(chunk, results):
                lines[b.line_target] = write_target_line(lines[b.line_target], tr)
                done += 1
            save_cache(cache, provider)
            if not dry:
                path.write_text("".join(lines), encoding="utf-8")
            sample = chunk[0].source[:40]
            sample_tr = results[0][:40] if results else ""
            msg = f"  [{done}/{len(pending)}] batch+{len(chunk)} {sample!r} -> {sample_tr!r}"
            print(msg.ljust(140)[:140], flush=True)
        print()
        save_cache(cache, provider)
        if not dry:
            path.write_text("".join(lines), encoding="utf-8")
        print(f"terminado: {done} traducidos")
        return

    last_req = 0.0
    for b in pending:
        elapsed = time.time() - last_req
        if elapsed < rate:
            time.sleep(rate - elapsed)
        try:
            tr = translate_text(b.source, cache, glossary, provider, email, api_key, fallback_deepl_key)
            consec_err = 0
        except Exception as e:
            consec_err += 1
            print(f"\n  [ERR {consec_err}/{MAX_CONSEC_ERRORS}] {b.label}: {e}")
            last_req = time.time()
            if consec_err >= MAX_CONSEC_ERRORS:
                print("  [ABORT] demasiados fallos consecutivos. Guardando y saliendo.")
                save_cache(cache, provider)
                if not dry:
                    path.write_text("".join(lines), encoding="utf-8")
                return
            continue
        last_req = time.time()
        lines[b.line_target] = write_target_line(lines[b.line_target], tr)
        done += 1
        save_cache(cache, provider)
        msg = f"  [{done}/{len(pending)}] {b.source[:50]!r} -> {tr[:50]!r}"
        print(msg.ljust(140)[:140], end="\r", flush=True)
        if done % 25 == 0:
            if not dry:
                path.write_text("".join(lines), encoding="utf-8")
            print()

    print()
    save_cache(cache, provider)
    if not dry:
        path.write_text("".join(lines), encoding="utf-8")
    print(f"terminado: {done} traducidos")

def process_strings(path: Path, limit: int, dry: bool, provider: str, email: str, api_key: str, fallback_deepl_key: str = "", batch_size: int = GEMINI_BATCH_SIZE, gemini_model: str = GEMINI_MODEL, openai_model: str = OPENAI_MODEL):
    blocks = parse_strings_file(str(path))
    pending = [b for b in blocks if not b.current_target.strip()]
    print(f"strings totales: {len(blocks)} | vacios: {len(pending)}")
    if limit:
        pending = pending[:limit]

    cache = load_cache(provider)
    glossary = load_glossary()
    print(f"provider: {provider}" + (f" | model: {openai_model} | batch: {batch_size} | budget=${OPENAI_BUDGET_USD:.2f}" if provider == "openai" else "") + (f" | model: {gemini_model} | batch: {batch_size}" if provider == "gemini" else ""))
    rate = {"deepl": RATE_LIMIT_SEC_DEEPL, "gemini": RATE_LIMIT_SEC_GEMINI, "openai": RATE_LIMIT_SEC_OPENAI}.get(provider, RATE_LIMIT_SEC_MM)

    if not dry:
        bak = path.with_suffix(path.suffix + ".bak")
        if not bak.exists():
            shutil.copy2(path, bak)
            print(f"backup: {bak}")

    with path.open(encoding="utf-8") as fh:
        lines = fh.readlines()

    done = 0
    consec_err = 0

    if provider == "openai":
        last_req = 0.0
        for start in range(0, len(pending), batch_size):
            chunk = pending[start:start + batch_size]
            elapsed = time.time() - last_req
            if elapsed < rate:
                time.sleep(rate - elapsed)
            try:
                results = translate_batch_openai(
                    [b.source for b in chunk], cache, glossary, api_key, openai_model,
                )
                consec_err = 0
            except OpenAIBudgetExceeded as e:
                print(f"\n  [BUDGET] {e}")
                save_cache(cache, provider)
                if not dry:
                    path.write_text("".join(lines), encoding="utf-8")
                return
            except Exception as e:
                consec_err += 1
                print(f"\n  [ERR batch {consec_err}/{MAX_CONSEC_ERRORS}] @{start}: {e}")
                last_req = time.time()
                if consec_err >= MAX_CONSEC_ERRORS:
                    print("  [ABORT] demasiados fallos consecutivos. Guardando y saliendo.")
                    save_cache(cache, provider)
                    if not dry:
                        path.write_text("".join(lines), encoding="utf-8")
                    return
                time.sleep(15)
                continue
            last_req = time.time()
            for b, tr in zip(chunk, results):
                lines[b.line_new] = write_target_line(lines[b.line_new], tr)
                done += 1
            save_cache(cache, provider)
            if not dry:
                path.write_text("".join(lines), encoding="utf-8")
            sample = chunk[0].source[:40]
            sample_tr = results[0][:40] if results else ""
            msg = f"  [{done}/{len(pending)}] batch+{len(chunk)} {sample!r} -> {sample_tr!r}"
            print(msg.ljust(140)[:140], flush=True)
        print()
        save_cache(cache, provider)
        if not dry:
            path.write_text("".join(lines), encoding="utf-8")
        u = _openai_load_usage()
        print(f"terminado: {done} traducidos | gasto sesion total: ${u['total_cost_usd']:.4f} ({u['requests']} reqs, in={u['total_input_tokens']} out={u['total_output_tokens']})")
        return

    if provider == "gemini":
        last_req = 0.0
        for start in range(0, len(pending), batch_size):
            chunk = pending[start:start + batch_size]
            elapsed = time.time() - last_req
            if elapsed < rate:
                time.sleep(rate - elapsed)
            try:
                results = translate_batch_gemini(
                    [b.source for b in chunk], cache, glossary,
                    api_key, gemini_model, fallback_deepl_key, email,
                )
                consec_err = 0
            except Exception as e:
                consec_err += 1
                print(f"\n  [ERR batch {consec_err}/{MAX_CONSEC_ERRORS}] @{start}: {e}")
                last_req = time.time()
                if consec_err >= MAX_CONSEC_ERRORS:
                    print("  [ABORT] demasiados fallos consecutivos. Guardando y saliendo.")
                    save_cache(cache, provider)
                    if not dry:
                        path.write_text("".join(lines), encoding="utf-8")
                    return
                # Backoff defensivo: esperar 30s tras error antes de reintentar el mismo chunk
                time.sleep(30)
                continue
            last_req = time.time()
            for b, tr in zip(chunk, results):
                lines[b.line_new] = write_target_line(lines[b.line_new], tr)
                done += 1
            save_cache(cache, provider)
            if not dry:
                path.write_text("".join(lines), encoding="utf-8")
            sample = chunk[0].source[:40]
            sample_tr = results[0][:40] if results else ""
            msg = f"  [{done}/{len(pending)}] batch+{len(chunk)} {sample!r} -> {sample_tr!r}"
            print(msg.ljust(140)[:140], flush=True)
        print()
        save_cache(cache, provider)
        if not dry:
            path.write_text("".join(lines), encoding="utf-8")
        print(f"terminado: {done} traducidos")
        return

    last_req = 0.0
    for b in pending:
        elapsed = time.time() - last_req
        if elapsed < rate:
            time.sleep(rate - elapsed)
        try:
            tr = translate_text(b.source, cache, glossary, provider, email, api_key, fallback_deepl_key)
            consec_err = 0
        except Exception as e:
            consec_err += 1
            print(f"\n  [ERR {consec_err}/{MAX_CONSEC_ERRORS}] {b.source[:40]!r}: {e}")
            last_req = time.time()
            if consec_err >= MAX_CONSEC_ERRORS:
                print("  [ABORT] demasiados fallos consecutivos. Guardando y saliendo.")
                save_cache(cache, provider)
                if not dry:
                    path.write_text("".join(lines), encoding="utf-8")
                return
            continue
        last_req = time.time()
        lines[b.line_new] = write_target_line(lines[b.line_new], tr)
        done += 1
        save_cache(cache, provider)
        msg = f"  [{done}/{len(pending)}] {b.source[:50]!r} -> {tr[:50]!r}"
        print(msg.ljust(140)[:140], end="\r", flush=True)
        if done % 25 == 0:
            if not dry:
                path.write_text("".join(lines), encoding="utf-8")
            print()

    print()
    save_cache(cache, provider)
    if not dry:
        path.write_text("".join(lines), encoding="utf-8")
    print(f"terminado: {done} traducidos")

def detect_format(path: Path) -> str:
    with path.open(encoding="utf-8") as fh:
        head = fh.read(4096)
    if "translate spanish strings:" in head.lower():
        return "strings"
    return "dialogue"

def main():
    import os
    global OPENAI_BUDGET_USD, DEEPL_KEY_POOL
    ap = argparse.ArgumentParser()
    ap.add_argument("file", help="archivo .rpy a traducir")
    ap.add_argument("--dry", action="store_true", help="no escribir archivo")
    ap.add_argument("--limit", type=int, default=0, help="max bloques vacios a traducir")
    ap.add_argument("--provider", choices=["deepl", "mymemory", "gemini", "openai"], default="deepl")
    ap.add_argument("--email", default="", help="email para subir cuota MyMemory")
    ap.add_argument("--deepl-key", default=os.environ.get("DEEPL_API_KEY", ""),
                    help="API key de DeepL (o env DEEPL_API_KEY)")
    ap.add_argument("--gemini-key", default=os.environ.get("GEMINI_API_KEY", ""),
                    help="API key de Gemini (o env GEMINI_API_KEY)")
    ap.add_argument("--gemini-model", default=GEMINI_MODEL,
                    help=f"modelo Gemini (default {GEMINI_MODEL}; otras: gemini-2.5-flash, gemini-flash-latest)")
    ap.add_argument("--openai-key", default=os.environ.get("OPENAI_API_KEY", ""),
                    help="API key de OpenAI (o env OPENAI_API_KEY)")
    ap.add_argument("--openai-model", default=OPENAI_MODEL,
                    help=f"modelo OpenAI (default {OPENAI_MODEL}; otras: gpt-4o-mini, gpt-4.1-mini, gpt-4.1)")
    ap.add_argument("--openai-budget", type=float, default=OPENAI_BUDGET_USD,
                    help=f"tope de gasto USD por sesion OpenAI (default ${OPENAI_BUDGET_USD:.2f}, env OPENAI_BUDGET_USD)")
    ap.add_argument("--batch-size", type=int, default=GEMINI_BATCH_SIZE,
                    help=f"strings por request en provider=gemini/openai (default {GEMINI_BATCH_SIZE})")
    ap.add_argument("--format", choices=["auto", "dialogue", "strings"], default="auto")
    args = ap.parse_args()

    if args.provider == "deepl" and not args.deepl_key:
        sys.exit("--provider deepl requiere --deepl-key o variable DEEPL_API_KEY")
    if args.provider == "gemini" and not args.gemini_key:
        sys.exit("--provider gemini requiere --gemini-key o variable GEMINI_API_KEY")
    if args.provider == "openai" and not args.openai_key:
        sys.exit("--provider openai requiere --openai-key o variable OPENAI_API_KEY")

    # Override budget si se especifico via CLI o env
    OPENAI_BUDGET_USD = float(args.openai_budget)

    # Inicializar pool de keys DeepL (DEEPL_API_KEY + DEEPL_API_KEY_2..N + DEEPL_API_KEY_BACKUP*)
    # para rotación automática cuando alguna devuelve 456.
    pool = []
    if args.deepl_key:
        pool.append(args.deepl_key)
    for env_name, env_val in os.environ.items():
        if env_name.startswith("DEEPL_API_KEY") and env_name != "DEEPL_API_KEY" and env_val:
            if env_val not in pool:
                pool.append(env_val)
    DEEPL_KEY_POOL = pool
    if len(DEEPL_KEY_POOL) > 1:
        masked = [k[:8] + "..." for k in DEEPL_KEY_POOL]
        print(f"DeepL pool: {len(DEEPL_KEY_POOL)} keys: {masked}")

    api_key = args.deepl_key if args.provider == "deepl" else (args.gemini_key if args.provider == "gemini" else (args.openai_key if args.provider == "openai" else ""))

    path = Path(args.file)
    if not path.exists():
        sys.exit(f"no existe: {path}")

    fmt = args.format if args.format != "auto" else detect_format(path)
    text = path.read_text(encoding="utf-8")
    # has_dialogue: encabezados translate spanish <label>: que NO sean strings:
    has_dialogue = re.search(r"^translate\s+spanish\s+(?!strings:)\S+:", text, re.MULTILINE | re.IGNORECASE) is not None
    has_strings = re.search(r"^translate\s+spanish\s+strings:", text, re.MULTILINE | re.IGNORECASE) is not None
    print(f"formato: {fmt} | dialogue_blocks={has_dialogue} | strings_block={has_strings}")

    # Forzar formato manual aun manda; auto/mixto procesa ambos cuando aplique
    do_dialogue = (fmt == "dialogue") or (args.format == "auto" and has_dialogue)
    do_strings = (fmt == "strings") or (args.format == "auto" and has_strings)

    if do_dialogue and do_strings:
        print("[mixto] archivo contiene dialogue y strings; procesando ambos")
    fallback_key = args.deepl_key if args.provider == "gemini" else ""
    if do_dialogue:
        process_dialogue(path, args.limit, args.dry, args.provider, args.email, api_key, fallback_key,
                         batch_size=args.batch_size, gemini_model=args.gemini_model, openai_model=args.openai_model)
    if do_strings:
        process_strings(path, args.limit, args.dry, args.provider, args.email, api_key, fallback_key,
                        batch_size=args.batch_size, gemini_model=args.gemini_model, openai_model=args.openai_model)

if __name__ == "__main__":
    main()
