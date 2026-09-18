"""
Glosario automático por juego: nombres de personaje sacados de los .rpy del juego.

Cada juego tiene sus propios nombres; antes se usaba el glosario fijo de FromTheSin
para todos. Este módulo escanea `define x = Character("Nombre", ...)` (y variantes
con _("Nombre")) en los .rpy de origen (fuera de tl/) y escribe un glosario con el
mismo formato que lee translate.py: los nombres quedan con target == source, es
decir, protegidos del traductor (no se traducen ni se acentúan).

Uso: python game_glossary.py <ruta/al/juego/game> [--out archivo.json]
"""
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

# define e = Character("Eris", ...) | Character(_("Eris")) | Character('Eris') | DynamicCharacter no aplica
_CHARACTER_RE = re.compile(r"""Character\(\s*(?:_\(\s*)?["']([^"'\n]{1,40})["']""")

# Nombres genéricos que Ren'Py suele usar como rótulo y que SÍ deben traducirse
GENERICOS = {
    "???", "unknown", "narrator", "stranger", "voice", "someone", "everyone", "all", "both", "man", "woman",
    "girl", "boy", "guy", "lady", "mom", "dad", "mother", "father", "sister", "brother", "aunt", "uncle", "grandma",
    "grandpa", "teacher", "nurse", "doctor", "boss", "landlady", "landlord", "waitress", "waiter", "officer", "police",
    "guard", "clerk", "student", "you", "me", "mc", "player", "protagonist", "neighbor", "neighbour", "friend", "roommate",
    "phone", "tv", "text", "sms", "system", "announcer", "crowd", "cashier", "receptionist", "driver", "cop", "bartender",
    "customer", "stepmom", "stepdad", "stepsister", "stepbrother", "wife", "husband", "daughter", "son", "kid", "child",
}


def extraer_nombres(game_dir: Path) -> Counter:
    """Cuenta nombres de personaje definidos en los .rpy de origen (ignora tl/ y cache)."""
    nombres: Counter = Counter()
    game_dir = Path(game_dir)
    for rpy in sorted(game_dir.rglob("*.rpy")):
        partes = {p.lower() for p in rpy.relative_to(game_dir).parts[:-1]}
        if "tl" in partes or "cache" in partes:
            continue
        try:
            texto = rpy.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        for m in _CHARACTER_RE.finditer(texto):
            nombre = m.group(1).strip()
            if not nombre or "[" in nombre or "{" in nombre or "%" in nombre:
                continue   # nombres dinámicos ([mc_name]) ya los protege el tokenizador
            if nombre.lower() in GENERICOS or not re.search(r"[A-Za-z]", nombre):
                continue
            if nombre[0].islower():
                continue   # "e", "narrator" en minúscula: rótulos técnicos, no nombres
            nombres[nombre] += 1
    return nombres


def generar(game_dir: Path, out: Path) -> dict:
    """Escribe el glosario del juego y devuelve el dict escrito."""
    nombres = extraer_nombres(game_dir)
    data = {
        "_meta": {"generated_from": str(game_dir), "generated_at": datetime.now().isoformat(timespec="seconds"),
                  "auto": True, "note": "Nombres de Character(): target == source = protegido del traductor."},
        "characters": {n: {"source": n, "target": n, "count": c} for n, c in sorted(nombres.items())},
        "terms": {},
    }
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        return 2
    game_dir = Path(argv[0])
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else game_dir.parent / "tl-es-glossary.json"
    data = generar(game_dir, out)
    print(f"{len(data['characters'])} nombres → {out}")
    for n, e in data["characters"].items():
        print(f"  {n} ({e['count']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
