"""Settings loader con cache + mtime reload.

Lee tools/pipeline_settings.json y lo mergea sobre defaults. Reload automatico
si el archivo cambia (revisado en cada get_all()).
"""
import json
import threading
from pathlib import Path

SETTINGS_FILE = Path(__file__).resolve().parent.parent / "pipeline_settings.json"

_DEFAULTS = {
    "default_lang": "Spanish",
    "default_provider": "auto",
    "output_dir": str(Path.home() / "Documents" / "games tl"),
    "renpy_sdk": "auto",
    "ntfy_topic": "",
    "openai": {"budget_usd": 1.50, "batch_size": 25, "model": "gpt-4.1-nano", "timeout_sec": 120},
    "deepl": {"free_quota_chars": 500_000},
    "ntfy": {"stage_events": True, "progress_every_pct": 10, "provider_switch": True, "errors": True},
    "package": {"enabled": True, "mode": "auto", "max_size_gb": 5, "compress_below_mb": 500},
    "qa": {"timeout_sec": 1800, "backend": "groq"},
    "diagnose": {"run_after_job": True, "timeout_sec": 60},
    "renpy": {"force_language_if_no_selector": True},
    "stage_weights": {
        "renpy":    {"analyze": 5, "setup": 10, "translate": 65, "lint_qa": 15, "package": 5},
        "unity":    {"analyze": 5, "setup": 5,  "translate": 80, "lint_qa": 0,  "package": 10},
        "rpgmaker": {"analyze": 5, "setup": 5,  "translate": 80, "lint_qa": 0,  "package": 10},
    },
    "dashboard": {"poll_interval_sec": 2},
}

_lock = threading.Lock()
_cache: dict | None = None
_mtime: float = 0.0


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def get_all() -> dict:
    """Returns merged settings. Reloads from disk if mtime changed."""
    global _cache, _mtime
    with _lock:
        try:
            mt = SETTINGS_FILE.stat().st_mtime if SETTINGS_FILE.exists() else 0.0
        except OSError:
            mt = 0.0

        if _cache is not None and mt == _mtime:
            return _cache

        loaded = {}
        if SETTINGS_FILE.exists():
            try:
                loaded = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            except Exception:
                loaded = {}
        _cache = _merge(_DEFAULTS, loaded)
        _mtime = mt
        return _cache


def get(path: str, default=None):
    """Dot-path getter: get('openai.batch_size') -> int."""
    cur = get_all()
    for k in path.split("."):
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return default
    return cur


def write(data: dict) -> dict:
    """Validates JSON-serializable and writes to disk. Returns reloaded settings."""
    json.dumps(data)  # raises if not serializable
    SETTINGS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    global _cache, _mtime
    with _lock:
        _cache = None
        _mtime = 0.0
    return get_all()


def defaults() -> dict:
    return json.loads(json.dumps(_DEFAULTS))


if __name__ == "__main__":
    print(json.dumps(get_all(), indent=2, ensure_ascii=False))
