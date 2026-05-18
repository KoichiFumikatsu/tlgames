from __future__ import annotations

import argparse
import hashlib
import struct
from pathlib import Path


def patch_catalog(catalog_path: Path, bundle_root: Path, update_size: bool) -> tuple[int, list[str]]:
    data = bytearray(catalog_path.read_bytes())
    patched = 0
    missing: list[str] = []

    for bundle_path in sorted(bundle_root.rglob("*.bundle")):
        name = bundle_path.name.encode("utf-8")
        pos = bytes(data).find(name)
        if pos < 0:
            missing.append(bundle_path.name)
            continue

        name_len = len(name)
        internal_len_offset = pos + name_len
        if internal_len_offset + 4 > len(data):
            missing.append(f"{bundle_path.name} (truncated internal length)")
            continue

        internal_len = struct.unpack_from("<I", data, internal_len_offset)[0]
        hash_len_offset = internal_len_offset + 4 + internal_len + 16
        if hash_len_offset + 4 > len(data):
            missing.append(f"{bundle_path.name} (truncated hash length)")
            continue

        hash_len = struct.unpack_from("<I", data, hash_len_offset)[0]
        crc_offset = hash_len_offset + 4 + hash_len + 8
        size_offset = crc_offset + 4
        if size_offset + 4 > len(data):
            missing.append(f"{bundle_path.name} (truncated crc/size)")
            continue

        old_crc = struct.unpack_from("<I", data, crc_offset)[0]
        old_size = struct.unpack_from("<I", data, size_offset)[0]
        new_size = bundle_path.stat().st_size

        struct.pack_into("<I", data, crc_offset, 0)
        if update_size:
            struct.pack_into("<I", data, size_offset, new_size)

        patched += 1
        print(
            f"patched {bundle_path.name} crc={old_crc:08x}->00000000 "
            f"size={old_size}->{new_size if update_size else old_size}"
        )

    catalog_path.write_bytes(data)
    return patched, missing


def write_hash_file(catalog_path: Path) -> str:
    digest = hashlib.md5(catalog_path.read_bytes()).hexdigest()
    hash_path = catalog_path.with_suffix(".hash")
    if hash_path.exists():
        hash_path.write_text(digest, encoding="ascii")
    return digest


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch Addressables catalog bundle CRCs to 0 for modified local bundles.")
    parser.add_argument("catalog", type=Path)
    parser.add_argument("bundle_root", type=Path)
    parser.add_argument("--keep-size", action="store_true")
    parser.add_argument("--update-hash", action="store_true")
    args = parser.parse_args()

    patched, missing = patch_catalog(args.catalog, args.bundle_root, update_size=not args.keep_size)
    print(f"patched={patched}")
    print(f"missing={len(missing)}")
    for item in missing:
        print(f"missing {item}")

    if args.update_hash:
        digest = write_hash_file(args.catalog)
        print(f"catalog_hash_md5={digest}")

    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())