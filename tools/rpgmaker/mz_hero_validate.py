#!/usr/bin/env python3
"""Validate Hero MZ translated data files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Hero MZ JSON files after apply")
    parser.add_argument("game_root", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    data_root = args.game_root / "data"
    errors: list[dict] = []
    checked = 0
    for path in sorted(data_root.glob("*.json")):
        checked += 1
        try:
            json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:  # noqa: BLE001
            errors.append({"file": str(path), "error": f"{type(exc).__name__}: {exc}"})

    report = {
        "game_root": str(args.game_root),
        "checked_json_files": checked,
        "errors": errors,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"checked_json_files={checked}")
    print(f"json_errors={len(errors)}")
    print(f"report={args.report}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())