#!/usr/bin/env python3
"""
Linter para juegos RPG Maker MV/MZ ya traducidos.

Compara <data>/<archivo>.json (target) contra <data>/<archivo>.json.bak (source)
recorriendo las mismas rutas que translate_rpgmaker.extract_strings().

Checks:
  [CTRL]      control codes RPG Maker perdidos o alterados
              (\\C[n], \\I[n], \\N[n], \\V[n], \\P[n], \\G, \\.\\!\\>\\<\\^\\{\\}, %1..%9)
  [EMPTY]     target vacio cuando source no vacio (y no es codigo puro)
  [UNCHANGED] target == source y source tiene letras ASCII (>= 3) -> probable olvido
  [EN_RESID]  target conserva palabras EN comunes (heuristico, marcador suave)
  [OVERFLOW]  source < 30 chars y len(target)/len(source) > 1.4
              (probable desborde en labels, choices, botones)
  [EXPAND]    cualquier string con ratio > 1.6 (warn general)

Uso:
  python lint_rpgmaker.py <ruta_juego>
  python lint_rpgmaker.py <ruta_juego> --json
  python lint_rpgmaker.py <ruta_juego> --max-show 20
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from translate_rpgmaker import extract_strings, _get_nested  # type: ignore

CTRL_RE = re.compile(r"\\[CINVPG]\[\d+\]|\\[.!><^{}]|%[1-9]")
# Palabras EN sin equivalente ortografico en ES (no "no", "yes", "do" → ambiguos)
EN_RESID_WORDS = {
    "the", "and", "your", "with", "this", "that", "have",
    "from", "what", "they", "will", "would", "could", "should",
    "attack", "defend", "magic", "items", "equip",
}
SHORT_LEN = 30
SHORT_RATIO = 1.4
LONG_RATIO = 1.6
# Heuristica nombre propio: 1-3 palabras capitalizadas (sin chars especiales)
PROPER_NAME_RE = re.compile(r"^(?:[A-Z][a-z']*\d*\s*){1,3}$")
# Speaker label MV/MZ: nombre entre brackets, p.ej. "[Ruby]" o "[Geerutaro]"
SPEAKER_LABEL_RE = re.compile(r"^\s*\[[A-Za-z][A-Za-z0-9_\s]*\]\s*$")


def _data_dir(game_path: Path) -> Path:
    for cand in (game_path / "www" / "data", game_path / "data"):
        if cand.is_dir():
            return cand
    raise FileNotFoundError(f"data/ no encontrado en {game_path}")


def _load_pair(fpath: Path):
    """Devuelve (source_data, target_data) o (None, None) si falta .bak."""
    bak = fpath.with_suffix(".json.bak")
    if not bak.exists():
        return None, None
    try:
        src = json.loads(bak.read_text(encoding="utf-8-sig"))
        tgt = json.loads(fpath.read_text(encoding="utf-8-sig"))
        return src, tgt
    except Exception:
        return None, None


def _multiset(items):
    m = {}
    for it in items:
        m[it] = m.get(it, 0) + 1
    return m


def _diff(a, b):
    missing, extra = [], []
    for k, n in a.items():
        d = n - b.get(k, 0)
        if d > 0:
            missing.extend([k] * d)
    for k, n in b.items():
        d = n - a.get(k, 0)
        if d > 0:
            extra.extend([k] * d)
    return missing, extra


def _looks_english_residual(target: str) -> bool:
    """Heuristico: target tiene 2+ palabras EN frecuentes (no ES)."""
    tokens = re.findall(r"[A-Za-z']+", target.lower())
    if len(tokens) < 3:
        return False
    en_hits = sum(1 for t in tokens if t in EN_RESID_WORDS)
    return en_hits >= 2


def check_pair(source: str, target: str):
    issues = []
    if not isinstance(source, str) or not isinstance(target, str):
        return issues
    if not source.strip():
        return issues
    if not target.strip():
        issues.append(("EMPTY", "target vacio"))
        return issues

    # Control codes RPG Maker
    s_ctrl = _multiset(CTRL_RE.findall(source))
    t_ctrl = _multiset(CTRL_RE.findall(target))
    missing, extra = _diff(s_ctrl, t_ctrl)
    if missing:
        issues.append(("CTRL", f"faltan: {missing}"))
    if extra:
        issues.append(("CTRL", f"sobran: {extra}"))

    # Unchanged (solo si source tiene letras ASCII y NO parece nombre propio / speaker)
    if re.search(r"[A-Za-z]{3,}", source) and source == target:
        s_stripped = source.strip()
        if not PROPER_NAME_RE.match(s_stripped) and not SPEAKER_LABEL_RE.match(s_stripped):
            issues.append(("UNCHANGED", "target identico al source"))
        return issues  # no seguir con overflow/ctrl si son iguales

    # Residual EN
    if _looks_english_residual(target):
        issues.append(("EN_RESID", f"target parece EN: {target[:60]!r}"))

    # Overflow / expand
    s_len, t_len = len(source), len(target)
    if s_len > 0:
        ratio = t_len / s_len
        if s_len < SHORT_LEN and ratio > SHORT_RATIO:
            issues.append(("OVERFLOW", f"short {s_len}->{t_len} (x{ratio:.2f})"))
        elif ratio > LONG_RATIO:
            issues.append(("EXPAND", f"{s_len}->{t_len} (x{ratio:.2f})"))

    return issues


def lint_game(game_path: Path):
    data_dir = _data_dir(game_path)
    entries_by_file = extract_strings(data_dir)

    results = []
    counts = {}
    total_strings = 0
    files_checked = 0
    files_no_bak = []

    for fname, entries in entries_by_file.items():
        fpath = data_dir / fname
        src_data, tgt_data = _load_pair(fpath)
        if src_data is None:
            files_no_bak.append(fname)
            continue
        files_checked += 1
        for ent in entries:
            path = ent["path"]
            target_text = ent["text"]  # extract_strings devuelve la version actual (target)
            try:
                source_text = _get_nested(src_data, path)
            except Exception:
                continue
            if not isinstance(source_text, str):
                continue
            total_strings += 1
            for code, detail in check_pair(source_text, target_text):
                counts[code] = counts.get(code, 0) + 1
                results.append({
                    "file": fname,
                    "path": path,
                    "code": code,
                    "detail": detail,
                    "source": source_text,
                    "target": target_text,
                })

    return {
        "summary": counts,
        "files_checked": files_checked,
        "files_no_bak": files_no_bak,
        "strings_compared": total_strings,
        "issues": results,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("game_path", help="Ruta al juego RPG Maker traducido")
    ap.add_argument("--json", action="store_true", help="Salida JSON (para pipeline)")
    ap.add_argument("--max-show", type=int, default=10, help="Max ejemplos por codigo (humano)")
    args = ap.parse_args()

    report = lint_game(Path(args.game_path))

    if args.json:
        print(json.dumps({
            "summary": report["summary"],
            "files_checked": report["files_checked"],
            "files_no_bak": report["files_no_bak"],
            "strings_compared": report["strings_compared"],
            "issues_total": len(report["issues"]),
        }, ensure_ascii=False, indent=2))
        return 0 if not report["summary"] else 1

    summary = report["summary"]
    if not summary:
        print(f"OK: sin issues  |  archivos={report['files_checked']}  strings={report['strings_compared']}")
        if report["files_no_bak"]:
            print(f"  Sin .bak (no comparados): {len(report['files_no_bak'])}")
        return 0

    by_code = {}
    for r in report["issues"]:
        by_code.setdefault(r["code"], []).append(r)

    for code in sorted(by_code):
        rows = by_code[code]
        print(f"\n=== [{code}] {len(rows)} ===")
        for r in rows[:args.max_show]:
            print(f"  {r['file']}  {r['detail']}")
            print(f"    SRC: {r['source'][:80]!r}")
            print(f"    TGT: {r['target'][:80]!r}")
        if len(rows) > args.max_show:
            print(f"  ... +{len(rows) - args.max_show} mas")

    print(f"\nResumen: {summary}")
    print(f"Archivos chequeados: {report['files_checked']}  |  strings: {report['strings_compared']}")
    if report["files_no_bak"]:
        print(f"Sin .bak: {len(report['files_no_bak'])} -> {report['files_no_bak'][:5]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
