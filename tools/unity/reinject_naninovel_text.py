import argparse
import json
import shutil
from collections import defaultdict
from pathlib import Path

import UnityPy


def load_translations(path: Path):
    by_bundle = defaultdict(dict)
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            target = record.get("target") or ""
            if not target.strip():
                continue
            bundle = record.get("bundle")
            text_id = record.get("id")
            if not bundle or not text_id:
                raise ValueError(f"Missing bundle/id at line {line_number}")
            by_bundle[bundle][text_id] = target
    return by_bundle


def resolve_bundle_path(bundle_ref: str, bundle_root: Path):
    bundle_path = Path(bundle_ref)
    if bundle_path.exists():
        return bundle_path
    candidate = bundle_root / bundle_ref
    if candidate.exists():
        return candidate
    candidate = bundle_root / bundle_path.name
    if candidate.exists():
        return candidate
    raise FileNotFoundError(bundle_ref)


def output_path_for(bundle_path: Path, bundle_root: Path, out_root: Path):
    try:
        relative = bundle_path.relative_to(bundle_root)
    except ValueError:
        relative = Path(bundle_path.name)
    return out_root / relative


def patch_bundle(bundle_path: Path, replacements: dict[str, str], out_path: Path):
    env = UnityPy.load(str(bundle_path))
    changed = 0
    for obj in env.objects:
        if str(obj.type.name) != "MonoBehaviour":
            continue
        tree = obj.read_typetree()
        id_to_text = tree.get("textMap", {}).get("idToText", {})
        keys = id_to_text.get("keys") or []
        values = id_to_text.get("values") or []
        if len(keys) != len(values):
            continue

        touched = False
        for index, text_id in enumerate(keys):
            target = replacements.get(text_id)
            if target is None:
                continue
            if values[index] != target:
                values[index] = target
                changed += 1
                touched = True
        if touched:
            obj.save_typetree(tree)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if changed:
        with out_path.open("wb") as handle:
            handle.write(env.file.save())
    else:
        shutil.copy2(bundle_path, out_path)
    return changed


def main():
    parser = argparse.ArgumentParser(description="Reinject translated Naninovel textMap strings into Unity bundles.")
    parser.add_argument("translations_jsonl")
    parser.add_argument("--bundle-root", required=True)
    parser.add_argument("--out-root", required=True)
    args = parser.parse_args()

    translations_path = Path(args.translations_jsonl)
    bundle_root = Path(args.bundle_root).resolve()
    out_root = Path(args.out_root)
    by_bundle = load_translations(translations_path)

    patched_bundles = 0
    patched_strings = 0
    for bundle_ref, replacements in sorted(by_bundle.items()):
        bundle_path = resolve_bundle_path(bundle_ref, bundle_root).resolve()
        out_path = output_path_for(bundle_path, bundle_root, out_root)
        changed = patch_bundle(bundle_path, replacements, out_path)
        if changed:
            patched_bundles += 1
            patched_strings += changed
        print(f"{changed}\t{bundle_path.name}")

    print(f"patched_bundles={patched_bundles}")
    print(f"patched_strings={patched_strings}")
    print(f"out_root={out_root}")


if __name__ == "__main__":
    main()