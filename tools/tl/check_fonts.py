"""
Escanea fuentes .ttf/.otf y reporta cobertura de glifos para el alfabeto
espanol completo (incluyendo tildes, dieresis, n, abre-interrogacion/exclamacion).

Uso:
  python tools\\tl\\check_fonts.py <archivo.ttf | carpeta>
  python tools\\tl\\check_fonts.py "proyects Game TL\\<juego>\\game\\fonts"

Sin dependencias externas: usa solo tabla cmap del .ttf via fontTools si
esta disponible, si no parsea cmap manualmente con `pathlib`+`struct`.
Preferimos fontTools (pip install fonttools) para fiabilidad.
"""
from __future__ import annotations
import sys, os
from pathlib import Path

# Glifos requeridos para espanol
ES_REQUIRED = list("aeiouAEIOU")  # base
ES_REQUIRED += list("aeiouAEIOU".replace("", ""))  # placeholder
ES_REQUIRED = list("áéíóúÁÉÍÓÚñÑ¿¡üÜ")
# Tambien checkear comillas tipograficas y guion largo
TYPO_REQUIRED = list("«»“”‘’—–…")


def cmap_chars(path: Path) -> set[int]:
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        print("ERROR: instala fonttools  ->  pip install fonttools", file=sys.stderr)
        sys.exit(2)
    font = TTFont(str(path), lazy=True)
    chars = set()
    for table in font["cmap"].tables:
        if table.isUnicode():
            chars.update(table.cmap.keys())
    font.close()
    return chars


def report_font(path: Path) -> dict:
    chars = cmap_chars(path)
    missing_es = [c for c in ES_REQUIRED if ord(c) not in chars]
    missing_typo = [c for c in TYPO_REQUIRED if ord(c) not in chars]
    return {
        "path": path,
        "total_glyphs": len(chars),
        "missing_es": missing_es,
        "missing_typo": missing_typo,
        "ok_es": len(missing_es) == 0,
    }


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(2)
    target = Path(sys.argv[1])
    if target.is_file():
        files = [target]
    elif target.is_dir():
        files = sorted(p for p in target.rglob("*") if p.suffix.lower() in (".ttf", ".otf"))
    else:
        print(f"ERROR: {target} no existe"); sys.exit(2)

    if not files:
        print(f"No se encontraron .ttf/.otf en {target}"); return

    print(f"{'Fuente':50s}  ES?  glifos  faltan_ES  faltan_tipo")
    print("-" * 100)
    bad = []
    for f in files:
        try:
            r = report_font(f)
        except Exception as e:
            print(f"{f.name:50s}  ERR  {e}")
            continue
        flag = "OK " if r["ok_es"] else "NO "
        es_miss = "".join(r["missing_es"]) or "-"
        typo_miss = "".join(r["missing_typo"]) or "-"
        print(f"{f.name:50s}  {flag}  {r['total_glyphs']:6d}  {es_miss:10s}  {typo_miss}")
        if not r["ok_es"]:
            bad.append(f)

    if bad:
        print(f"\n{len(bad)} fuente(s) sin cobertura ES completa:")
        for f in bad:
            print(f"  - {f}")
        print("\nSiguiente paso: identificar donde se usan (gui.rpy / script.rpy / definitions.rpy)")
        print("y reemplazarlas en game/fonts/tl/<lang>/<mismo-nombre>.ttf")


if __name__ == "__main__":
    main()
