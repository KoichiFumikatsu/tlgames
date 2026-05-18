"""Extrae solo fuentes (.ttf/.otf) de un archive.rpa Ren'Py."""
import pickle, zlib, os, sys, pathlib

rpa_path = sys.argv[1]
out_root = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else pathlib.Path(".")

with open(rpa_path, "rb") as rpa:
    header = rpa.readline().decode().strip().split()
    off = int(header[1], 16)
    key = int(header[2], 16) if len(header) > 2 else 0
    rpa.seek(off)
    idx = pickle.loads(zlib.decompress(rpa.read()))

fonts = [k for k in idx if k.lower().endswith((".ttf", ".otf"))]
print(f"[extract] {len(fonts)} fuentes encontradas")

with open(rpa_path, "rb") as rpa:
    for fn in fonts:
        parts = idx[fn]
        out_path = out_root / fn
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "wb") as out:
            for entry in parts:
                # entry puede ser (offset, length) o (offset, length, prefix)
                if len(entry) == 3:
                    o, l, prefix = entry
                else:
                    o, l = entry
                    prefix = b""
                if isinstance(prefix, str):
                    prefix = prefix.encode("latin-1")
                o ^= key
                l ^= key
                if prefix:
                    out.write(prefix)
                    l -= len(prefix)
                rpa.seek(o)
                out.write(rpa.read(l))
        print(f"  -> {out_path} ({out_path.stat().st_size} bytes)")
