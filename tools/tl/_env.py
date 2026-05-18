"""Mini-loader de .env. Sin dependencias externas.

Busca el .env subiendo desde el cwd y desde la ubicación del script.
Solo carga claves que NO estén ya en os.environ (las env vars existentes ganan).
"""
import os
from pathlib import Path

def load_env(start: Path | None = None) -> dict[str, str]:
    """Carga el primer .env encontrado subiendo desde `start` (o cwd).
    Devuelve dict de pares cargados (los que no estaban ya en environ)."""
    if start is None:
        start = Path.cwd()
    candidates: list[Path] = []
    p = start.resolve()
    for parent in [p] + list(p.parents):
        candidates.append(parent / ".env")
    # Tambien probar relativo al archivo que invoca
    here = Path(__file__).resolve().parent
    for parent in [here] + list(here.parents):
        candidates.append(parent / ".env")

    seen: set[Path] = set()
    loaded: dict[str, str] = {}
    for c in candidates:
        if c in seen or not c.exists():
            seen.add(c)
            continue
        seen.add(c)
        for line in c.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
                loaded[k] = v
        break  # solo el primer .env hallado
    return loaded

if __name__ == "__main__":
    keys = load_env()
    print(f"loaded {len(keys)} keys: {list(keys)}")
