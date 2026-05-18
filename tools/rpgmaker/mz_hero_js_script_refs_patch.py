from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SCRIPT_CODES = {355, 655}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def iter_commands(value: Any, path: str = ""):
    if isinstance(value, dict):
        if isinstance(value.get("list"), list):
            yield path, value["list"]
        for key, child in value.items():
            next_path = f"{path}.{key}" if path else str(key)
            yield from iter_commands(child, next_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_commands(child, f"{path}[{index}]")


def command_map(data: Any) -> dict[tuple[str, int, int], dict[str, Any]]:
    commands: dict[tuple[str, int, int], dict[str, Any]] = {}
    for event_path, event_commands in iter_commands(data):
        for index, command in enumerate(event_commands):
            if not isinstance(command, dict):
                continue
            code = command.get("code")
            parameters = command.get("parameters")
            if code in SCRIPT_CODES and parameters and isinstance(parameters[0], str):
                commands[(event_path, index, code)] = command
    return commands


def patch_file(current_path: Path, backup_path: Path) -> tuple[bool, list[dict[str, Any]]]:
    current_data = load_json(current_path)
    backup_data = load_json(backup_path)
    current_commands = command_map(current_data)
    backup_commands = command_map(backup_data)
    details: list[dict[str, Any]] = []

    for key, current_command in current_commands.items():
        backup_command = backup_commands.get(key)
        if not backup_command:
            continue
        current_value = current_command["parameters"][0]
        backup_value = backup_command["parameters"][0]
        if current_value == backup_value:
            continue
        current_command["parameters"][0] = backup_value
        event_path, command_index, code = key
        details.append(
            {
                "event_path": event_path,
                "command_index": command_index,
                "code": code,
                "before": current_value,
                "after": backup_value,
            }
        )

    return bool(details), details, current_data


def patch_corpus(corpus_path: Path, changes: list[dict[str, Any]], dry_run: bool) -> int:
    if not corpus_path.exists() or not changes:
        return 0
    text = corpus_path.read_text(encoding="utf-8")
    original = text
    for change in changes:
        text = text.replace(change["before"], change["after"])
    if text != original and not dry_run:
        corpus_path.write_text(text, encoding="utf-8")
    return sum(1 for change in changes if change["before"] in original)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restore RPG Maker MZ JavaScript event script commands from backup."
    )
    parser.add_argument("game_root", type=Path)
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    game_root = args.game_root
    backup_root = args.backup_root
    report = {
        "dry_run": args.dry_run,
        "changed_files": [],
        "total_changes": 0,
        "corpus_changes": 0,
    }
    all_changes: list[dict[str, Any]] = []

    for current_path in sorted((game_root / "data").glob("*.json")):
        backup_path = backup_root / "data" / current_path.name
        if not backup_path.exists():
            continue
        changed, details, patched_data = patch_file(current_path, backup_path)
        if not changed:
            continue
        if not args.dry_run:
            write_json(current_path, patched_data)
        report["changed_files"].append(
            {"file": str(current_path.relative_to(game_root)), "details": details}
        )
        report["total_changes"] += len(details)
        all_changes.extend(details)

    corpus_path = game_root / "_tl_work" / "hero_mz_corpus.translated.jsonl"
    report["corpus_changes"] = patch_corpus(corpus_path, all_changes, args.dry_run)

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"changed_files={len(report['changed_files'])}")
    print(f"total_changes={report['total_changes']}")
    print(f"corpus_changes={report['corpus_changes']}")
    print(f"report={args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())