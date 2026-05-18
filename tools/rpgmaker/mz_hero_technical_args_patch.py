#!/usr/bin/env python3
"""Restore Hero MZ plugin command arguments that must remain in English."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


TECHNICAL_REPLACEMENTS = {
    '["ordenarMisión","ordenMisión","reporteMisión"]': '["orderingQuest","questOrder","questReport"]',
    '["ordenarMision","ordenMision","reporteMision"]': '["orderingQuest","questOrder","questReport"]',
    '{"NombreArchivo1":"","NombreArchivo2":"","XDespl":"240","YDespl":"300"}': '{"FileName1":"","FileName2":"","XOfs":"240","YOfs":"300"}',
}


def patch_value(value: Any) -> tuple[Any, int]:
    if isinstance(value, str):
        output = value
        changes = 0
        for source, target in TECHNICAL_REPLACEMENTS.items():
            if source in output:
                output = output.replace(source, target)
                changes += 1
        return output, changes
    if isinstance(value, list):
        total = 0
        output = []
        for item in value:
            patched, changes = patch_value(item)
            output.append(patched)
            total += changes
        return output, total
    if isinstance(value, dict):
        total = 0
        output = {}
        for key, item in value.items():
            patched_key, key_changes = patch_value(key)
            patched_item, item_changes = patch_value(item)
            output[patched_key] = patched_item
            total += key_changes + item_changes
        return output, total
    return value, 0


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
        if record.get("source") == '["orderingQuest","questOrder","questReport"]':
            if record.get("target") != record.get("source"):
                record["target"] = record["source"]
                changed += 1
        output_lines.append(json.dumps(record, ensure_ascii=False))

    if changed:
        corpus_path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
    return changed > 0, changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch Hero MZ technical plugin command arguments")
    parser.add_argument("game_root", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    changed_files: list[dict[str, Any]] = []
    for path in sorted((args.game_root / "data").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        patched, changes = patch_value(data)
        if changes:
            changed_files.append({"file": path.name, "replacements": changes})
            if not args.dry_run:
                path.write_text(json.dumps(patched, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    corpus_changed = False
    corpus_changes = 0
    if not args.dry_run:
        corpus_changed, corpus_changes = patch_corpus(args.game_root)

    report = {
        "game_root": str(args.game_root),
        "dry_run": args.dry_run,
        "changed_files": changed_files,
        "total_files": len(changed_files),
        "total_replacements": sum(item["replacements"] for item in changed_files),
        "corpus_changed": corpus_changed,
        "corpus_changes": corpus_changes,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"changed_files={report['total_files']}")
    print(f"total_replacements={report['total_replacements']}")
    print(f"corpus_changes={corpus_changes}")
    print(f"report={args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())