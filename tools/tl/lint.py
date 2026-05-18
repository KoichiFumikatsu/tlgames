"""
Valida un .rpy traducido comparando source vs target.

Checks:
  [TAG]      tags {..} desbalanceados o perdidos
  [VAR]      variables [var] perdidas/extras
  [PLACE]    placeholders |..| perdidos/extras
  [NL]       secuencias \\n perdidas/extras
  [EMPTY]    target vacio cuando source no lo es
  [UNCHANGED] target == source (posible olvido, solo si source tiene letras)
  [EXPAND]   target >150% del source (posible overflow)
  [TOFU]     chars no-ASCII que la fuente podria no tener (solo si --font dado)
  [SENTINEL] sentinelas ZT###Z quedaron sin resolver

Uso:
  python lint.py <archivo.rpy>
  python lint.py <archivo.rpy> --font "C:/.../VT323.ttf"
  python lint.py <archivo.rpy> --json    # salida JSON para tooling
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from lib_rpy import parse_dialogue_file, parse_strings_file  # type: ignore

TAG_RE = re.compile(r"\{[^{}]*\}")
VAR_RE = re.compile(r"\[[^\[\]]+\]")
PLACE_RE = re.compile(r"\|[A-Za-z0-9_]+\|")
SENTINEL_RE = re.compile(r"[Zz][Tt]\s*\d{1,4}\s*[Zz]")

def _multiset(items):
    m = {}
    for it in items:
        m[it] = m.get(it, 0) + 1
    return m

def _diff(a: dict, b: dict) -> tuple[list, list]:
    """Devuelve (solo_en_a, solo_en_b) como listas expandidas."""
    missing = []
    extra = []
    for k, n in a.items():
        d = n - b.get(k, 0)
        if d > 0:
            missing.extend([k] * d)
    for k, n in b.items():
        d = n - a.get(k, 0)
        if d > 0:
            extra.extend([k] * d)
    return missing, extra

def check(source: str, target: str, font_chars: set = None) -> list[tuple[str, str]]:
    """Devuelve lista de (codigo, detalle) para este par."""
    issues = []
    if not source.strip():
        return issues
    if not target.strip():
        issues.append(("EMPTY", "target vacio"))
        return issues

    # Sentinelas sin resolver
    if SENTINEL_RE.search(target):
        issues.append(("SENTINEL", "quedan marcadores ZT###Z sin resolver"))

    # Tags
    s_tags = _multiset(TAG_RE.findall(source))
    t_tags = _multiset(TAG_RE.findall(target))
    missing, extra = _diff(s_tags, t_tags)
    if missing:
        issues.append(("TAG", f"faltan: {missing}"))
    if extra:
        issues.append(("TAG", f"sobran: {extra}"))

    # Variables
    s_var = _multiset(VAR_RE.findall(source))
    t_var = _multiset(VAR_RE.findall(target))
    missing, extra = _diff(s_var, t_var)
    if missing:
        issues.append(("VAR", f"faltan: {missing}"))
    if extra:
        issues.append(("VAR", f"sobran: {extra}"))

    # Placeholders
    s_pl = _multiset(PLACE_RE.findall(source))
    t_pl = _multiset(PLACE_RE.findall(target))
    missing, extra = _diff(s_pl, t_pl)
    if missing:
        issues.append(("PLACE", f"faltan: {missing}"))
    if extra:
        issues.append(("PLACE", f"sobran: {extra}"))

    # \n count
    s_nl = source.count("\\n")
    t_nl = target.count("\\n")
    if s_nl != t_nl:
        issues.append(("NL", f"source {s_nl} vs target {t_nl}"))

    # Unchanged (solo si source tiene letras)
    if re.search(r"[A-Za-z]{3,}", source) and source == target:
        issues.append(("UNCHANGED", "target identico al source"))

    # Expansion
    if len(source) >= 20:
        ratio = len(target) / len(source)
        if ratio > 1.5:
            issues.append(("EXPAND", f"{ratio:.2f}x (source={len(source)}, target={len(target)})"))

    # Tofu check
    if font_chars is not None:
        missing_chars = {c for c in target if ord(c) > 127 and c not in font_chars}
        if missing_chars:
            issues.append(("TOFU", f"chars sin glifo: {sorted(missing_chars)}"))

    return issues

def load_font_chars(font_path: str) -> set:
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        print("fontTools no instalado; skip --font")
        return None
    f = TTFont(font_path, lazy=True)
    cmap = f.getBestCmap()
    return {chr(cp) for cp in cmap.keys()}

def detect_format(path: Path) -> str:
    with path.open(encoding="utf-8") as fh:
        head = fh.read(4096)
    return "strings" if "translate spanish strings:" in head.lower() else "dialogue"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--font", default="", help="ruta a .ttf/.otf para check TOFU")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--format", choices=["auto", "dialogue", "strings"], default="auto")
    args = ap.parse_args()

    path = Path(args.file)
    font_chars = load_font_chars(args.font) if args.font else None
    fmt = args.format if args.format != "auto" else detect_format(path)

    if fmt == "dialogue":
        blocks = parse_dialogue_file(str(path))
        items = [(b.label, b.char, b.source, b.current_target, b.line_target + 1) for b in blocks]
    else:
        blocks = parse_strings_file(str(path))
        items = [(b.source_file or "strings", "", b.source, b.current_target, b.line_new + 1) for b in blocks]

    results = []
    counts = {}
    for label, char, src, tgt, lineno in items:
        issues = check(src, tgt, font_chars)
        for code, detail in issues:
            counts[code] = counts.get(code, 0) + 1
            results.append({
                "line": lineno, "label": label, "char": char,
                "code": code, "detail": detail,
                "source": src, "target": tgt,
            })

    if args.json:
        print(json.dumps({"summary": counts, "issues": results}, ensure_ascii=False, indent=2))
        return

    if not results:
        print(f"OK: sin issues ({len(items)} bloques)")
        return

    # Agrupar por codigo
    by_code = {}
    for r in results:
        by_code.setdefault(r["code"], []).append(r)

    for code in sorted(by_code):
        rows = by_code[code]
        print(f"\n=== [{code}] {len(rows)} ===")
        for r in rows[:10]:
            print(f"  L{r['line']} {r['label']}/{r['char']}: {r['detail']}")
            print(f"    SRC: {r['source'][:80]!r}")
            print(f"    TGT: {r['target'][:80]!r}")
        if len(rows) > 10:
            print(f"  ... +{len(rows)-10} mas")

    print(f"\nResumen: {counts} | total issues: {len(results)} / bloques: {len(items)}")

if __name__ == "__main__":
    main()
