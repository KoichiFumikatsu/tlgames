#!/usr/bin/env python3
"""Extract translatable text from Hero in an All-Forgiving Fantasy World RPG.

This game is RPG Maker MZ with data/*.json at the game root and active plugin
parameters in js/plugins.js. The extractor writes two JSONL files:
- refs: every occurrence, with source file/path/category.
- corpus: deduplicated by exact source string, used for MT.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


JP_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]")
VISIBLE_RE = re.compile(r"[A-Za-z\u3040-\u30ff\u3400-\u9fff]")
MAP_FILE_RE = re.compile(r"Map\d+\.json")
PLUGINS_RE = re.compile(r"var\s+\$plugins\s*=\s*(\[.*\])\s*;", re.S)


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


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def language_of(text: str) -> str:
    has_jp = bool(JP_RE.search(text))
    has_latin = bool(LATIN_RE.search(text))
    if has_jp and has_latin:
        return "mixed"
    if has_jp:
        return "ja"
    if has_latin:
        return "latin"
    return "other"


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


def make_ref(records: list[dict[str, Any]], category: str, file_name: str, path: str, source: Any) -> None:
    if not looks_translatable(source):
        return
    source_text = str(source)
    records.append(
        {
            "engine": "rpgmaker_mz",
            "game": "hero_all_forgiving_fantasy_world_rpg",
            "id": f"r{len(records) + 1:06d}",
            "category": category,
            "source_file": file_name,
            "path": path,
            "source": source_text,
            "target": "",
            "chars": len(source_text),
            "language": language_of(source_text),
        }
    )


def extract_event_commands(records: list[dict[str, Any]], file_name: str, owner_path: str, commands: Any) -> None:
    if not isinstance(commands, list):
        return
    for index, command in enumerate(commands):
        if not isinstance(command, dict):
            continue
        code = command.get("code")
        params = command.get("parameters") or []
        base = f"{owner_path}.list[{index}].code{code}"
        if code in (401, 405) and params:
            make_ref(records, "events_text", file_name, base + ".parameters[0]", params[0])
        elif code == 102 and params and isinstance(params[0], list):
            for choice_index, choice in enumerate(params[0]):
                make_ref(records, "choices", file_name, base + f".parameters[0][{choice_index}]", choice)
        elif code in (101, 105) and len(params) > 4:
            make_ref(records, "nameboxes", file_name, base + ".parameters[4]", params[4])
        elif code == 357 and len(params) >= 4 and isinstance(params[3], dict):
            for key, value in params[3].items():
                make_ref(records, "plugin_command_args", file_name, base + f".parameters[3].{key}", value)


def extract_data_json(root: Path, records: list[dict[str, Any]]) -> None:
    data_dir = root / "data"
    for path in sorted(p for p in data_dir.glob("Map*.json") if MAP_FILE_RE.fullmatch(p.name)):
        data = load_json(path)
        for event in data.get("events") or []:
            if not event:
                continue
            for page_index, page in enumerate(event.get("pages") or []):
                extract_event_commands(records, path.name, f"events[{event.get('id')}].pages[{page_index}]", page.get("list"))

    common_path = data_dir / "CommonEvents.json"
    if common_path.exists():
        data = load_json(common_path)
        for event in data:
            if not event:
                continue
            make_ref(records, "database", common_path.name, f"commonEvents[{event.get('id')}].name", event.get("name", ""))
            extract_event_commands(records, common_path.name, f"commonEvents[{event.get('id')}]", event.get("list"))

    troops_path = data_dir / "Troops.json"
    if troops_path.exists():
        data = load_json(troops_path)
        for troop in data:
            if not troop:
                continue
            make_ref(records, "database", troops_path.name, f"troops[{troop.get('id')}].name", troop.get("name", ""))
            for page_index, page in enumerate(troop.get("pages") or []):
                extract_event_commands(records, troops_path.name, f"troops[{troop.get('id')}].pages[{page_index}]", page.get("list"))

    for file_name, fields in DATABASE_FIELDS.items():
        path = data_dir / file_name
        if not path.exists():
            continue
        data = load_json(path)
        for entry in data:
            if not entry:
                continue
            for field in fields:
                make_ref(records, "database", file_name, f"records[{entry.get('id')}].{field}", entry.get(field, ""))

    system_path = data_dir / "System.json"
    if system_path.exists():
        system = load_json(system_path)
        for field in ["gameTitle", "currencyUnit"]:
            make_ref(records, "system", system_path.name, field, system.get(field, ""))
        for list_field in SYSTEM_LISTS:
            for index, value in enumerate(system.get(list_field) or []):
                make_ref(records, "system", system_path.name, f"{list_field}[{index}]", value)
        terms = system.get("terms") or {}
        for list_field in SYSTEM_TERM_LISTS:
            for index, value in enumerate(terms.get(list_field) or []):
                make_ref(records, "system_terms", system_path.name, f"terms.{list_field}[{index}]", value)
        for key, value in (terms.get("messages") or {}).items():
            make_ref(records, "system_terms", system_path.name, f"terms.messages.{key}", value)


def decode_jsonish(value: str) -> Any | None:
    text = value.strip()
    if not text or text[0] not in '[{"':
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def walk_plugin_value(records: list[dict[str, Any]], plugin_name: str, path: str, value: Any, depth: int = 0) -> None:
    if depth > 8:
        return
    if isinstance(value, dict):
        for key, child in value.items():
            walk_plugin_value(records, plugin_name, f"{path}.{key}", child, depth + 1)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            walk_plugin_value(records, plugin_name, f"{path}[{index}]", child, depth + 1)
    elif isinstance(value, str):
        decoded = decode_jsonish(value)
        if decoded is not None:
            walk_plugin_value(records, plugin_name, path + "<json>", decoded, depth + 1)
        elif not PLUGIN_TECH_PATH_RE.search(path):
            make_ref(records, "plugin_params", "plugins.js", f"{plugin_name}:{path}", value)


def load_plugins(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8-sig")
    match = PLUGINS_RE.search(text)
    if not match:
        raise RuntimeError(f"Could not parse plugins array in {path}")
    return json.loads(match.group(1))


def extract_plugins(root: Path, records: list[dict[str, Any]]) -> None:
    plugins_path = root / "js" / "plugins.js"
    if not plugins_path.exists():
        return
    for plugin in load_plugins(plugins_path):
        if not plugin or not plugin.get("status"):
            continue
        walk_plugin_value(records, str(plugin.get("name", "?")), "parameters", plugin.get("parameters", {}))


def build_corpus(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in refs:
        grouped[record["source"]].append(record)
    corpus: list[dict[str, Any]] = []
    for index, (source, occurrences) in enumerate(sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])), start=1):
        categories = sorted({record["category"] for record in occurrences})
        files = sorted({record["source_file"] for record in occurrences})
        corpus.append(
            {
                "engine": "rpgmaker_mz",
                "game": "hero_all_forgiving_fantasy_world_rpg",
                "id": f"u{index:05d}",
                "source": source,
                "target": "",
                "occurrences": len(occurrences),
                "categories": categories,
                "files": files[:20],
                "chars": len(source),
                "language": language_of(source),
            }
        )
    return corpus


def write_report(path: Path, root: Path, refs: list[dict[str, Any]], corpus: list[dict[str, Any]]) -> None:
    by_category = Counter(record["category"] for record in refs)
    chars_by_category = Counter()
    by_language_chars = Counter()
    by_file = Counter()
    chars_by_file = Counter()
    for record in refs:
        chars_by_category[record["category"]] += len(record["source"])
        by_language_chars[record["language"]] += len(record["source"])
        by_file[record["source_file"]] += 1
        chars_by_file[record["source_file"]] += len(record["source"])
    report = {
        "root": str(root),
        "engine": "rpgmaker_mz",
        "refs": len(refs),
        "ref_chars": sum(len(record["source"]) for record in refs),
        "unique_strings": len(corpus),
        "unique_chars": sum(len(record["source"]) for record in corpus),
        "by_category": dict(by_category.most_common()),
        "chars_by_category": dict(chars_by_category.most_common()),
        "chars_by_language": dict(by_language_chars.most_common()),
        "top_files": [
            {"file": file_name, "records": by_file[file_name], "chars": chars_by_file[file_name]}
            for file_name, _count in chars_by_file.most_common(25)
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract Hero RPG Maker MZ text to JSONL")
    parser.add_argument("game_root", type=Path)
    parser.add_argument("--refs-out", type=Path, required=True)
    parser.add_argument("--corpus-out", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    root = args.game_root.resolve()
    refs: list[dict[str, Any]] = []
    extract_data_json(root, refs)
    extract_plugins(root, refs)
    corpus = build_corpus(refs)
    write_jsonl(args.refs_out, refs)
    write_jsonl(args.corpus_out, corpus)
    write_report(args.report, root, refs, corpus)

    print(f"root={root}")
    print("engine=rpgmaker_mz")
    print(f"refs={len(refs)}")
    print(f"ref_chars={sum(len(record['source']) for record in refs)}")
    print(f"unique_strings={len(corpus)}")
    print(f"unique_chars={sum(len(record['source']) for record in corpus)}")
    print(f"refs_out={args.refs_out}")
    print(f"corpus_out={args.corpus_out}")
    print(f"report={args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())