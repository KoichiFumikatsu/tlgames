#!/usr/bin/env python3
"""Restore Hero MZ asset references and conditional choice suffixes."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


IMAGE_FIELD_FOLDERS = {
    "battleback1Name": "battlebacks1",
    "battleback2Name": "battlebacks2",
    "parallaxName": "parallaxes",
    "characterName": "characters",
    "faceName": "faces",
    "battlerName": "enemies",
    "title1Name": "titles1",
    "title2Name": "titles2",
}

AUDIO_FOLDERS = ("bgm", "bgs", "me", "se")
ASSET_EXTENSIONS = (".png", ".png_", ".rpgmvp", ".ogg", ".ogg_", ".m4a", ".m4a_", ".rpgmvo")
SOURCE_CONDITION_MARKERS = (" if(", " en(")
CURRENT_CONDITION_MARKERS = (" if(", " en(", " si(", " (if(", " (en(", " (si(")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def asset_exists(base: Path, name: str, extensions: tuple[str, ...] = ASSET_EXTENSIONS) -> bool:
    if not name:
        return True
    stem = base / name
    return any(Path(str(stem) + extension).exists() for extension in extensions)


def audio_exists(game_root: Path, name: str) -> bool:
    return any(asset_exists(game_root / "audio" / folder, name) for folder in AUDIO_FOLDERS)


def patch_conditional_choice(current: str, backup: str) -> tuple[str, bool]:
    source_indexes = [backup.find(marker) for marker in SOURCE_CONDITION_MARKERS if marker in backup]
    if not source_indexes:
        return current, False
    source_index = min(source_indexes)
    suffix = backup[source_index:]

    lowered = current.lower()
    current_indexes = [lowered.find(marker) for marker in CURRENT_CONDITION_MARKERS if marker in lowered]
    if not current_indexes:
        return current, False
    current_index = min(current_indexes)
    label = current[:current_index].strip()
    if not label:
        return current, False
    if label == "Toca":
        label = "Tocar"
    if label == "Abre":
        label = "Abrir"
    patched = f"{label}{suffix}"
    return patched, patched != current


def patch_audio_object(game_root: Path, current: dict[str, Any], backup: dict[str, Any]) -> tuple[int, dict[str, Any] | None]:
    if not {"name", "volume", "pitch", "pan"}.issubset(current) or "name" not in backup:
        return 0, None
    current_name = current.get("name")
    backup_name = backup.get("name")
    if not isinstance(current_name, str) or not isinstance(backup_name, str):
        return 0, None
    if current_name == backup_name or audio_exists(game_root, current_name) or not audio_exists(game_root, backup_name):
        return 0, None
    current["name"] = backup_name
    return 1, {"from": current_name, "to": backup_name}


def patch_asset_field(
    game_root: Path,
    current: dict[str, Any],
    backup: dict[str, Any],
    key: str,
) -> tuple[int, dict[str, Any] | None]:
    current_name = current.get(key)
    backup_name = backup.get(key)
    if not isinstance(current_name, str) or not isinstance(backup_name, str) or current_name == backup_name:
        return 0, None
    folder = IMAGE_FIELD_FOLDERS[key]
    current_base = game_root / "img" / folder
    backup_base = game_root / "img" / folder
    if asset_exists(current_base, current_name) or not asset_exists(backup_base, backup_name):
        return 0, None
    current[key] = backup_name
    return 1, {"key": key, "from": current_name, "to": backup_name}


def patch_show_picture(game_root: Path, current: dict[str, Any], backup: dict[str, Any]) -> tuple[int, dict[str, Any] | None]:
    if current.get("code") != 231 or backup.get("code") != 231:
        return 0, None
    current_params = current.get("parameters")
    backup_params = backup.get("parameters")
    if not isinstance(current_params, list) or not isinstance(backup_params, list):
        return 0, None
    if len(current_params) < 2 or len(backup_params) < 2:
        return 0, None
    current_name = current_params[1]
    backup_name = backup_params[1]
    if not isinstance(current_name, str) or not isinstance(backup_name, str) or current_name == backup_name:
        return 0, None
    pictures_root = game_root / "img" / "pictures"
    if asset_exists(pictures_root, current_name) or not asset_exists(pictures_root, backup_name):
        return 0, None
    current_params[1] = backup_name
    return 1, {"from": current_name, "to": backup_name}


def patch_value(game_root: Path, current: Any, backup: Any, path: str, changes: list[dict[str, Any]]) -> int:
    total = 0
    if isinstance(current, str) and isinstance(backup, str):
        patched, did_patch = patch_conditional_choice(current, backup)
        if did_patch:
            changes.append({"kind": "conditional_choice", "path": path, "from": current, "to": patched})
            return 1
        return 0

    if isinstance(current, list) and isinstance(backup, list):
        for index, (current_item, backup_item) in enumerate(zip(current, backup)):
            if isinstance(current_item, str) and isinstance(backup_item, str):
                patched, did_patch = patch_conditional_choice(current_item, backup_item)
                if did_patch:
                    current[index] = patched
                    changes.append(
                        {
                            "kind": "conditional_choice",
                            "path": f"{path}[{index}]",
                            "from": current_item,
                            "to": patched,
                        }
                    )
                    total += 1
            else:
                total += patch_value(game_root, current_item, backup_item, f"{path}[{index}]", changes)
        return total

    if isinstance(current, dict) and isinstance(backup, dict):
        audio_changes, audio_detail = patch_audio_object(game_root, current, backup)
        if audio_detail:
            changes.append({"kind": "audio", "path": path, **audio_detail})
        total += audio_changes

        picture_changes, picture_detail = patch_show_picture(game_root, current, backup)
        if picture_detail:
            changes.append({"kind": "picture", "path": path, **picture_detail})
        total += picture_changes

        for key in IMAGE_FIELD_FOLDERS:
            asset_changes, asset_detail = patch_asset_field(game_root, current, backup, key)
            if asset_detail:
                changes.append({"kind": "image", "path": path, **asset_detail})
            total += asset_changes

        for key, current_item in list(current.items()):
            if key in backup:
                total += patch_value(game_root, current_item, backup[key], f"{path}.{key}", changes)
        return total

    return 0


def patch_corpus(game_root: Path) -> tuple[bool, int]:
    corpus_path = game_root / "_tl_work" / "hero_mz_corpus.translated.jsonl"
    if not corpus_path.exists():
        return False, 0

    changed = 0
    output_lines: list[str] = []
    for line in corpus_path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            output_lines.append(line)
            continue
        record = json.loads(line)
        source = record.get("source")
        target = record.get("target")
        if isinstance(source, str) and isinstance(target, str):
            patched, did_patch = patch_conditional_choice(target, source)
            if did_patch:
                record["target"] = patched
                changed += 1
        output_lines.append(json.dumps(record, ensure_ascii=False))

    if changed:
        corpus_path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
    return changed > 0, changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch Hero MZ asset refs and conditional choices")
    parser.add_argument("game_root", type=Path)
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    changed_files: list[dict[str, Any]] = []
    for current_path in sorted((args.game_root / "data").glob("*.json")):
        backup_path = args.backup_root / "data" / current_path.name
        if not backup_path.exists():
            continue
        current_data = load_json(current_path)
        backup_data = load_json(backup_path)
        changes: list[dict[str, Any]] = []
        total = patch_value(args.game_root, current_data, backup_data, current_path.name, changes)
        if total:
            changed_files.append({"file": current_path.name, "changes": total, "details": changes})
            if not args.dry_run:
                current_path.write_text(
                    json.dumps(current_data, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8",
                )

    corpus_changed = False
    corpus_changes = 0
    if not args.dry_run:
        corpus_changed, corpus_changes = patch_corpus(args.game_root)

    report = {
        "game_root": str(args.game_root),
        "backup_root": str(args.backup_root),
        "dry_run": args.dry_run,
        "changed_files": changed_files,
        "total_files": len(changed_files),
        "total_changes": sum(item["changes"] for item in changed_files),
        "corpus_changed": corpus_changed,
        "corpus_changes": corpus_changes,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"changed_files={report['total_files']}")
    print(f"total_changes={report['total_changes']}")
    print(f"corpus_changes={corpus_changes}")
    print(f"report={args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())