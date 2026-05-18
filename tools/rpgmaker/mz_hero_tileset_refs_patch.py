#!/usr/bin/env python3
"""Restore Hero MZ tileset asset references from the original backup."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def tileset_exists(game_root: Path, tileset_name: str) -> bool:
    if not tileset_name:
        return True
    stem = game_root / "img" / "tilesets" / tileset_name
    return (
        stem.with_suffix(".png").exists()
        or Path(str(stem) + ".png_").exists()
        or stem.with_suffix(".rpgmvp").exists()
    )


def audit_missing(game_root: Path, tilesets: list[Any]) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for tileset in tilesets:
        if not isinstance(tileset, dict):
            continue
        for asset_name in tileset.get("tilesetNames", []):
            if asset_name and not tileset_exists(game_root, asset_name):
                missing.append(
                    {
                        "id": tileset.get("id"),
                        "name": tileset.get("name", ""),
                        "asset": asset_name,
                    }
                )
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch Hero MZ tileset asset references")
    parser.add_argument("game_root", type=Path)
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    current_path = args.game_root / "data" / "Tilesets.json"
    backup_path = args.backup_root / "data" / "Tilesets.json"
    current_tilesets = load_json(current_path)
    backup_tilesets = load_json(backup_path)

    backup_by_id = {
        item.get("id"): item
        for item in backup_tilesets
        if isinstance(item, dict) and "id" in item
    }

    before_missing = audit_missing(args.game_root, current_tilesets)
    changes: list[dict[str, Any]] = []

    for tileset in current_tilesets:
        if not isinstance(tileset, dict):
            continue
        backup_tileset = backup_by_id.get(tileset.get("id"))
        if not isinstance(backup_tileset, dict):
            continue
        current_names = tileset.get("tilesetNames")
        backup_names = backup_tileset.get("tilesetNames")
        if current_names != backup_names:
            changes.append(
                {
                    "id": tileset.get("id"),
                    "name": tileset.get("name", ""),
                    "from": current_names,
                    "to": backup_names,
                }
            )
            tileset["tilesetNames"] = backup_names

    after_missing = audit_missing(args.game_root, current_tilesets)
    before_missing_set = {(item["id"], item["asset"]) for item in before_missing}
    after_missing_set = {(item["id"], item["asset"]) for item in after_missing}

    if changes and not args.dry_run:
        current_path.write_text(
            json.dumps(current_tilesets, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

    report = {
        "game_root": str(args.game_root),
        "backup_root": str(args.backup_root),
        "dry_run": args.dry_run,
        "changed_tilesets": changes,
        "total_changed_tilesets": len(changes),
        "missing_before": before_missing,
        "missing_after": after_missing,
        "total_missing_before": len(before_missing),
        "total_missing_after": len(after_missing),
        "fixed_missing_refs": len(before_missing_set - after_missing_set),
        "new_missing_refs": len(after_missing_set - before_missing_set),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"changed_tilesets={report['total_changed_tilesets']}")
    print(f"missing_before={report['total_missing_before']}")
    print(f"missing_after={report['total_missing_after']}")
    print(f"fixed_missing_refs={report['fixed_missing_refs']}")
    print(f"new_missing_refs={report['new_missing_refs']}")
    print(f"report={args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())