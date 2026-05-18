import argparse
import csv
import json
from pathlib import Path

import UnityPy


def iter_bundles(root: Path, pattern: str):
    if root.is_file():
        yield root
        return
    yield from sorted(root.rglob(pattern))


def get_map_items(tree):
    text_map = tree.get("textMap")
    if not isinstance(text_map, dict):
        return []
    id_to_text = text_map.get("idToText")
    if not isinstance(id_to_text, dict):
        return []
    keys = id_to_text.get("keys") or []
    values = id_to_text.get("values") or []
    if len(keys) != len(values):
        return []
    return list(zip(keys, values))


def extract_records(root: Path, pattern: str):
    for bundle in iter_bundles(root, pattern):
        try:
            env = UnityPy.load(str(bundle))
        except Exception as exc:
            yield {"kind": "error", "bundle": str(bundle), "error": str(exc)}
            continue

        for obj in env.objects:
            if str(obj.type.name) != "MonoBehaviour":
                continue
            try:
                tree = obj.read_typetree()
            except Exception as exc:
                yield {"kind": "error", "bundle": str(bundle), "error": str(exc)}
                continue

            items = get_map_items(tree)
            if not items:
                continue

            script_path = tree.get("path") or tree.get("m_Name") or ""
            script_name = tree.get("m_Name") or ""
            for index, (text_id, source) in enumerate(items):
                yield {
                    "kind": "text",
                    "bundle": str(bundle),
                    "script_path": script_path,
                    "script_name": script_name,
                    "index": index,
                    "id": text_id,
                    "source": source,
                    "target": "",
                }


def main():
    parser = argparse.ArgumentParser(description="Extract Naninovel textMap strings from Unity bundles.")
    parser.add_argument("root", help="Bundle file or directory containing Naninovel bundles.")
    parser.add_argument("--pattern", default="naninovel_assets_naninovel_scripts_*.bundle")
    parser.add_argument("--out-jsonl", required=True)
    parser.add_argument("--out-csv")
    args = parser.parse_args()

    root = Path(args.root)
    out_jsonl = Path(args.out_jsonl)
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    out_csv = Path(args.out_csv) if args.out_csv else None
    if out_csv:
        out_csv.parent.mkdir(parents=True, exist_ok=True)

    records = list(extract_records(root, args.pattern))
    text_records = [record for record in records if record.get("kind") == "text"]
    error_records = [record for record in records if record.get("kind") == "error"]

    with out_jsonl.open("w", encoding="utf-8", newline="") as handle:
        for record in text_records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    if out_csv:
        fieldnames = ["bundle", "script_path", "script_name", "index", "id", "source", "target"]
        with out_csv.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for record in text_records:
                writer.writerow({field: record.get(field, "") for field in fieldnames})

    script_count = len({record["script_path"] for record in text_records})
    bundle_count = len({record["bundle"] for record in text_records})
    char_count = sum(len(record["source"]) for record in text_records)
    print(f"bundles_with_text={bundle_count}")
    print(f"scripts={script_count}")
    print(f"strings={len(text_records)}")
    print(f"source_chars={char_count}")
    print(f"errors={len(error_records)}")
    if error_records:
        for record in error_records[:10]:
            print(f"ERROR {record['bundle']}: {record['error']}")


if __name__ == "__main__":
    main()