"""DeepL utilities centralizadas: pool de keys, check_usage, estado persistente."""
import json
import os
import urllib.request
from datetime import date
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent / ".cache"
QUOTA_STATE_FILE = CACHE_DIR / "deepl_quota_state.json"

# DeepL API Free oficial: 500,000 chars/mes. Anteriormente este codigo asumia
# que la API tenia un "bug" reportando la mitad y sobreescribia a 1M — incorrecto.
# Verificado 2026-05-24: /v2/usage devuelve character_limit=500000 con cuenta nueva.
DEEPL_FREE_QUOTA_REAL = 500_000
DEEPL_USAGE_ENDPOINT = "https://api-free.deepl.com/v2/usage"


def get_keys() -> list[str]:
    """Returns all DeepL keys from env (DEEPL_API_KEY, DEEPL_API_KEY_2, etc)."""
    out: list[str] = []
    primary = os.environ.get("DEEPL_API_KEY", "").strip()
    if primary:
        out.append(primary)
    for k, v in os.environ.items():
        if k.startswith("DEEPL_API_KEY") and k != "DEEPL_API_KEY":
            v = (v or "").strip()
            if v and v not in out:
                out.append(v)
    return out


def check_usage(api_key: str, timeout: int = 8) -> dict:
    """GET /v2/usage. Returns {character_count, character_limit} or {} on failure.
    Devuelve el valor tal cual lo reporta DeepL — la API es la verdad operativa."""
    if not api_key:
        return {}
    try:
        req = urllib.request.Request(
            DEEPL_USAGE_ENDPOINT,
            headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        return data
    except Exception:
        return {}


def check_quota_pool(keys: list[str] | None = None) -> dict:
    """Itera pool, suma chars disponibles. Returns dict con total_used/total_limit/available/per_key/source."""
    if keys is None:
        keys = get_keys()

    per_key = []
    total_used = 0
    total_limit = 0
    api_ok = False

    for k in keys:
        usage = check_usage(k)
        if usage:
            api_ok = True
            used = usage.get("character_count", 0)
            limit = usage.get("character_limit", DEEPL_FREE_QUOTA_REAL)
            per_key.append({
                "key_suffix": k[-6:],
                "used": used,
                "limit": limit,
                "available": max(0, limit - used),
            })
            total_used += used
            total_limit += limit
        else:
            per_key.append({
                "key_suffix": k[-6:] if k else "",
                "used": None,
                "limit": None,
                "available": None,
            })

    available = max(0, total_limit - total_used) if total_limit > 0 else 0
    return {
        "total_used": total_used,
        "total_limit": total_limit,
        "available": available,
        "per_key": per_key,
        "source": "api" if api_ok else "unknown",
        "key_count": len(keys),
    }


def is_exhausted_today() -> bool:
    """Lee .cache/deepl_quota_state.json. True si exhausted_date == today."""
    state = get_state()
    return state.get("exhausted_date") == date.today().isoformat()


def mark_exhausted_today():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    QUOTA_STATE_FILE.write_text(
        json.dumps({"exhausted_date": date.today().isoformat()}),
        encoding="utf-8",
    )


def get_state() -> dict:
    if not QUOTA_STATE_FILE.exists():
        return {}
    try:
        return json.loads(QUOTA_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


if __name__ == "__main__":
    print(json.dumps(check_quota_pool(), indent=2))
    print(f"exhausted_today: {is_exhausted_today()}")
