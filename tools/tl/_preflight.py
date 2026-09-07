"""Preflight para decidir provider antes de empezar a traducir.

Lo invoca la stage 'analyze' del pipeline_server una vez se conoce el conteo de chars.
"""
from __future__ import annotations
import _deepl
import _settings


def decide_provider(chars: int, settings: dict | None = None,
                    deepl_quota: dict | None = None) -> tuple[str, str]:
    """Returns (provider, reason). provider in {'deepl', 'openai'}.

    Logica:
      1. Si settings.default_provider != "auto" -> retornar ese provider forzado.
      2. Si DeepL exhausted_today (cache state) -> openai.
      3. Si check_quota_pool con sumas reales -> chars <= available -> deepl.
      4. Si la consulta a /v2/usage fallo (source != 'api') -> deepl con razon
         'preflight_failed_fallback_reactive' (comportamiento previo: el server
         hara fallback a OpenAI si DeepL responde 456).
      5. Else (chars > available) -> openai.
    """
    settings = settings or _settings.get_all()
    forced = (settings.get("default_provider") or "auto").lower()
    if forced not in ("auto", ""):
        if forced in ("deepl", "openai"):
            return forced, "forced_by_setting"

    if _deepl.is_exhausted_today():
        return "openai", "deepl_exhausted_today"

    quota = deepl_quota or _deepl.check_quota_pool()
    if quota.get("source") != "api":
        return "deepl", "preflight_failed_fallback_reactive"

    available = int(quota.get("available", 0))
    if chars <= available:
        return "deepl", f"chars_fit_quota:{chars}/{available}"
    return "openai", f"chars_exceed_quota:{chars}>{available}"


if __name__ == "__main__":
    import json, sys
    chars = int(sys.argv[1]) if len(sys.argv) > 1 else 100_000
    p, r = decide_provider(chars)
    print(json.dumps({"chars": chars, "provider": p, "reason": r}, indent=2))
