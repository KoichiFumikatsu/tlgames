from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from rubymarshal.reader import load
from rubymarshal.writer import write


def load_translations(path: Path) -> dict[str, str]:
    translations: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            source = str(record.get("source", ""))
            target = str(record.get("target", ""))
            if source and target and source != target:
                translations[source] = target
    return translations


def replace_bytes(value: bytes, translations: dict[str, str], stats: dict[str, int]) -> bytes:
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError:
        return value
    target = translations.get(text)
    if not target:
        return value
    stats["replacements"] += 1
    return target.encode("utf-8")


def walk_replace(value: Any, translations: dict[str, str], stats: dict[str, int]) -> Any:
    if isinstance(value, bytes):
        return replace_bytes(value, translations, stats)
    if isinstance(value, list):
        for index, item in enumerate(value):
            value[index] = walk_replace(item, translations, stats)
        return value
    if isinstance(value, dict):
        for key, item in list(value.items()):
            value[key] = walk_replace(item, translations, stats)
        return value
    attributes = getattr(value, "attributes", None)
    if isinstance(attributes, dict):
        for key, item in list(attributes.items()):
            attributes[key] = walk_replace(item, translations, stats)
    return value


def process_file(path: Path, translations: dict[str, str], backup_root: Path | None, dry_run: bool) -> dict[str, Any]:
    with path.open("rb") as handle:
        data = load(handle)
    stats = {"replacements": 0}
    walk_replace(data, translations, stats)
    if stats["replacements"] and not dry_run:
        if backup_root is not None:
            backup_root.mkdir(parents=True, exist_ok=True)
            backup_path = backup_root / path.name
            if not backup_path.exists():
                shutil.copy2(path, backup_path)
        with path.open("wb") as handle:
            write(handle, data)
    return {"file": str(path), "replacements": stats["replacements"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply exact translated text replacements to RPG Maker Ruby Marshal data files.")
    parser.add_argument("translations", type=Path)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--backup-root", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    translations = load_translations(args.translations)
    results = [process_file(path, translations, args.backup_root, args.dry_run) for path in args.files]
    total_replacements = sum(result["replacements"] for result in results)
    report = {
        "translations": len(translations),
        "files": len(results),
        "total_replacements": total_replacements,
        "dry_run": args.dry_run,
        "results": results,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"translations={len(translations)}")
    print(f"files={len(results)}")
    print(f"total_replacements={total_replacements}")
    print(f"report={args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())