#!/usr/bin/env python3
"""Apply translated Hero RPG Maker MZ corpus back into data/*.json and plugins.js."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any


MAP_FILE_RE = re.compile(r"Map\d+\.json")
PLUGINS_RE = re.compile(r"var\s+\$plugins\s*=\s*(\[.*\])\s*;", re.S)
VISIBLE_RE = re.compile(r"[A-Za-z\u3040-\u30ff\u3400-\u9fff]")

DATABASE_FIELDS = {
    "Actors.json": ["name", "nickname", "profile"],
    "Classes.json": ["name"],
    "Skills.json": ["name", "description", "message1", "message2"],
    "Items.json": ["name", "description"],
    "Weapons.json": ["name", "description"],
    "Armors.json": ["name", "description"],
    "Enemies.json": ["name"],
    "States.json": ["name", "message1", "message2", "message3", "message4"],
}
SYSTEM_LISTS = ["armorTypes", "elements", "equipTypes", "skillTypes", "weaponTypes"]
SYSTEM_TERM_LISTS = ["basic", "commands", "params"]
PLUGIN_TECH_PATH_RE = re.compile(
    r"(file|filename|font|class|switch|variable|id|x$|y$|width|height|color|"
    r"volume|pitch|pan|duration|speed|scale|offset|position|icon|image|se|bgm|bgs|me)",
    re.I,
)

TECH_LITERAL_STRINGS = {
    "true",
    "false",
    "null",
    "undefined",
    "nan",
    "inf",
    "number",
    "string",
    "boolean",
    "object",
    "array",
    "def",
    "default",
    "none",
    "auto",
    "left",
    "right",
    "center",
    "top",
    "bottom",
    "under",
    "sprite",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def dump_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def load_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_translation_map(path: Path) -> dict[str, str]:
    translations: dict[str, str] = {}
    for record in load_jsonl(path):
        source = str(record.get("source", ""))
        target = str(record.get("target", "")).strip()
        if source and target:
            translations[source] = target.replace("\r\n", "\\n").replace("\n", "\\n")
    return translations


def looks_translatable(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if len(text) <= 1:
        return False
    if text.lower() in TECH_LITERAL_STRINGS:
        return False
    if not VISIBLE_RE.search(text):
        return False
    if "/" in text or "\\" in text:
        return False
    if re.search(r"\.(png|jpg|jpeg|webp|ogg|m4a|ttf|otf|woff|js|json)$", text, re.I):
        return False
    if re.fullmatch(r"[-_=*#<>/\[\]().,;:!?\s]+", text):
        return False
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*", text):
        return len(text) <= 14 or " " in text
    return True


def translate_value(value: Any, translations: dict[str, str]) -> tuple[Any, bool]:
    if isinstance(value, str) and looks_translatable(value):
        target = translations.get(value)
        if target is not None and target != value:
            return target, True
    return value, False


def apply_event_commands(commands: Any, translations: dict[str, str]) -> int:
    if not isinstance(commands, list):
        return 0
    changed = 0
    for command in commands:
        if not isinstance(command, dict):
            continue
        code = command.get("code")
        params = command.get("parameters") or []
        if code in (401, 405) and params:
            params[0], did_change = translate_value(params[0], translations)
            changed += int(did_change)
        elif code == 102 and params and isinstance(params[0], list):
            for index, choice in enumerate(params[0]):
                params[0][index], did_change = translate_value(choice, translations)
                changed += int(did_change)
        elif code in (101, 105) and len(params) > 4:
            params[4], did_change = translate_value(params[4], translations)
            changed += int(did_change)
        elif code == 357 and len(params) >= 4 and isinstance(params[3], dict):
            for key, value in list(params[3].items()):
                params[3][key], did_change = translate_value(value, translations)
                changed += int(did_change)
    return changed


def apply_data_file(path: Path, translations: dict[str, str]) -> int:
    data = load_json(path)
    changed = 0
    if MAP_FILE_RE.fullmatch(path.name):
        for event in data.get("events") or []:
            if not event:
                continue
            for page in event.get("pages") or []:
                changed += apply_event_commands(page.get("list"), translations)
    elif path.name == "CommonEvents.json":
        for event in data:
            if not event:
                continue
            if "name" in event:
                event["name"], did_change = translate_value(event.get("name", ""), translations)
                changed += int(did_change)
            changed += apply_event_commands(event.get("list"), translations)
    elif path.name == "Troops.json":
        for troop in data:
            if not troop:
                continue
            troop["name"], did_change = translate_value(troop.get("name", ""), translations)
            changed += int(did_change)
            for page in troop.get("pages") or []:
                changed += apply_event_commands(page.get("list"), translations)
    elif path.name in DATABASE_FIELDS:
        for entry in data:
            if not entry:
                continue
            for field in DATABASE_FIELDS[path.name]:
                if field in entry:
                    entry[field], did_change = translate_value(entry.get(field, ""), translations)
                    changed += int(did_change)
    elif path.name == "System.json":
        for field in ["gameTitle", "currencyUnit"]:
            if field in data:
                data[field], did_change = translate_value(data.get(field, ""), translations)
                changed += int(did_change)
        for list_field in SYSTEM_LISTS:
            for index, value in enumerate(data.get(list_field) or []):
                data[list_field][index], did_change = translate_value(value, translations)
                changed += int(did_change)
        terms = data.get("terms") or {}
        for list_field in SYSTEM_TERM_LISTS:
            for index, value in enumerate(terms.get(list_field) or []):
                terms[list_field][index], did_change = translate_value(value, translations)
                changed += int(did_change)
        for key, value in list((terms.get("messages") or {}).items()):
            terms["messages"][key], did_change = translate_value(value, translations)
            changed += int(did_change)
    if changed:
        dump_json(path, data)
    return changed


def decode_jsonish(value: str) -> Any | None:
    text = value.strip()
    if not text or text[0] not in '[{"':
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def transform_plugin_value(value: Any, path: str, translations: dict[str, str], depth: int = 0) -> tuple[Any, int]:
    if depth > 8:
        return value, 0
    if isinstance(value, dict):
        changed = 0
        for key, child in list(value.items()):
            value[key], child_changed = transform_plugin_value(child, f"{path}.{key}", translations, depth + 1)
            changed += child_changed
        return value, changed
    if isinstance(value, list):
        changed = 0
        for index, child in enumerate(value):
            value[index], child_changed = transform_plugin_value(child, f"{path}[{index}]", translations, depth + 1)
            changed += child_changed
        return value, changed
    if isinstance(value, str):
        decoded = decode_jsonish(value)
        if decoded is not None:
            decoded, changed = transform_plugin_value(decoded, path + "<json>", translations, depth + 1)
            if changed:
                return json.dumps(decoded, ensure_ascii=False, separators=(",", ":")), changed
            return value, 0
        if not PLUGIN_TECH_PATH_RE.search(path):
            translated, did_change = translate_value(value, translations)
            return translated, int(did_change)
    return value, 0


def apply_plugins(root: Path, translations: dict[str, str]) -> int:
    path = root / "js" / "plugins.js"
    if not path.exists():
        return 0
    text = path.read_text(encoding="utf-8-sig")
    match = PLUGINS_RE.search(text)
    if not match:
        raise RuntimeError(f"Could not parse plugins array in {path}")
    plugins = json.loads(match.group(1))
    changed = 0
    for plugin in plugins:
        if not plugin or not plugin.get("status"):
            continue
        params, child_changed = transform_plugin_value(plugin.get("parameters", {}), f"{plugin.get('name', '?')}:parameters", translations)
        plugin["parameters"] = params
        changed += child_changed
    if changed:
        lines = ["// Generated by RPG Maker.", "// Do not edit this file directly.", "var $plugins =", "["]
        for index, plugin in enumerate(plugins):
            suffix = "," if index < len(plugins) - 1 else ""
            lines.append(json.dumps(plugin, ensure_ascii=False, separators=(",", ":")) + suffix)
        lines.append("];" )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def make_local_backup(root: Path, backup_root: Path) -> int:
    copied = 0
    if backup_root.exists():
        return copied
    for path in sorted((root / "data").glob("*.json")):
        relative = path.relative_to(root)
        dest = backup_root / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        copied += 1
    plugins = root / "js" / "plugins.js"
    if plugins.exists():
        dest = backup_root / plugins.relative_to(root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(plugins, dest)
        copied += 1
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply translated Hero MZ corpus to game JSON files")
    parser.add_argument("translated_jsonl", type=Path)
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = args.game_root.resolve()
    translations = load_translation_map(args.translated_jsonl)
    backup_copied = 0
    changed_files = 0
    changed_values = 0

    if not args.dry_run:
        backup_copied = make_local_backup(root, args.backup_root.resolve())

    for path in sorted((root / "data").glob("*.json")):
        if not (MAP_FILE_RE.fullmatch(path.name) or path.name in {"CommonEvents.json", "Troops.json", "System.json", *DATABASE_FIELDS.keys()}):
            continue
        if args.dry_run:
            temp_data = json.loads(path.read_text(encoding="utf-8-sig"))
            original_write = globals()["dump_json"]
            try:
                globals()["dump_json"] = lambda _path, _value: None
                changed = apply_data_file(path, translations)
            finally:
                globals()["dump_json"] = original_write
            if changed:
                path.write_text(json.dumps(temp_data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                raise RuntimeError("dry-run protection failed")
        else:
            changed = apply_data_file(path, translations)
        if changed:
            changed_files += 1
            changed_values += changed

    if args.dry_run:
        plugin_changed = 0
    else:
        plugin_changed = apply_plugins(root, translations)
    if plugin_changed:
        changed_files += 1
        changed_values += plugin_changed

    report = {
        "translated_jsonl": str(args.translated_jsonl),
        "game_root": str(root),
        "translations": len(translations),
        "backup_root": str(args.backup_root),
        "backup_copied": backup_copied,
        "changed_files": changed_files,
        "changed_values": changed_values,
        "dry_run": args.dry_run,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"translations={len(translations)}")
    print(f"backup_copied={backup_copied}")
    print(f"changed_files={changed_files}")
    print(f"changed_values={changed_values}")
    print(f"report={args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())