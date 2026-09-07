"""Empaquetador ZIP autonomo para juegos traducidos.

CLI: python3 _package.py <ruta_juego> <ruta_zip_destino> [--max-gb 5] [--compress-below-mb 500]

Stdout emite lineas parseables por pipeline_server:
  [PROGRESS] file=X done=N total=M pct=P
  [WARN] package_skipped_too_large size_gb=X
  [STAGE] package END size_mb=X path=...
"""
from __future__ import annotations
import argparse
import os
import sys
import time
import zipfile
from pathlib import Path


def _du_bytes(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def _gather_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for base, _, names in os.walk(root):
        for n in names:
            out.append(Path(base) / n)
    return out


def package(game_path: Path, zip_path: Path, max_gb: float = 5.0,
            compress_below_mb: int = 500) -> int:
    """Returns exit code: 0=ok, 2=skipped_too_large, 1=error."""
    if not game_path.exists() or not game_path.is_dir():
        print(f"[ERROR] game_path no existe o no es directorio: {game_path}", flush=True)
        return 1

    size = _du_bytes(game_path)
    size_gb = size / (1024 ** 3)
    size_mb = size / (1024 ** 2)
    print(f"[STAGE] package START size_mb={size_mb:.1f} max_gb={max_gb}", flush=True)

    if size_gb > max_gb:
        print(f"[WARN] package_skipped_too_large size_gb={size_gb:.2f} max_gb={max_gb}", flush=True)
        print("[STAGE] package END status=skipped reason=too_large", flush=True)
        return 2

    files = _gather_files(game_path)
    total = len(files)
    if total == 0:
        print("[WARN] sin archivos para empaquetar", flush=True)
        return 1

    # ZIP_STORED si juego > umbral (binarios ya comprimidos, DEFLATE solo quema CPU)
    use_stored = size_mb >= compress_below_mb
    mode = zipfile.ZIP_STORED if use_stored else zipfile.ZIP_DEFLATED
    mode_label = "STORED" if use_stored else "DEFLATED"
    print(f"[STAGE] package mode={mode_label} files={total}", flush=True)

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()

    done = 0
    last_pct = -1
    started = time.time()
    try:
        with zipfile.ZipFile(zip_path, "w", compression=mode, allowZip64=True) as zf:
            for f in files:
                try:
                    arcname = f.relative_to(game_path)
                except ValueError:
                    arcname = f.name
                try:
                    zf.write(f, arcname)
                except Exception as e:
                    print(f"[WARN] skip {f.name}: {e}", flush=True)
                done += 1
                pct = int((done / total) * 100)
                if pct != last_pct and pct % 5 == 0:
                    print(f"[PROGRESS] file={f.name} done={done} total={total} pct={pct}", flush=True)
                    last_pct = pct
    except Exception as e:
        print(f"[ERROR] zip fallo: {e}", flush=True)
        return 1

    elapsed = time.time() - started
    zip_mb = zip_path.stat().st_size / (1024 ** 2)
    print(f"[STAGE] package END status=done size_mb={zip_mb:.1f} elapsed_s={elapsed:.1f} path={zip_path}",
          flush=True)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("game_path")
    ap.add_argument("zip_path")
    ap.add_argument("--max-gb", type=float, default=5.0)
    ap.add_argument("--compress-below-mb", type=int, default=500)
    args = ap.parse_args()
    rc = package(Path(args.game_path), Path(args.zip_path),
                 max_gb=args.max_gb, compress_below_mb=args.compress_below_mb)
    sys.exit(rc)


if __name__ == "__main__":
    main()
