"""Reescribe IN-PLACE el indice final de un .rpa removiendo entradas con prefix.
NO copia el body (1+ GB). Solo reescribe header (primera linea) + indice al final.
Uso: python strip_rpa_entries.py <archivo.rpa> <prefix>
"""
import sys, pickle, zlib, os, shutil

def main():
    rpa_path = sys.argv[1]
    prefix = sys.argv[2]
    bak = rpa_path + ".prestrip.bak"
    if not os.path.exists(bak):
        print(f"[backup] copiando {rpa_path} -> {bak} (puede tardar)...")
        shutil.copy2(rpa_path, bak)
    with open(rpa_path, "rb") as f:
        header_line = f.readline()
        parts = header_line.decode().split()
        assert parts[0] == "RPA-3.0", f"unsupported: {parts[0]}"
        index_offset = int(parts[1], 16)
        key = int(parts[2], 16)
        f.seek(index_offset)
        index = pickle.loads(zlib.decompress(f.read()))
    print(f"entradas totales: {len(index)}")
    to_remove = [k for k in index if k.startswith(prefix)]
    print(f"a eliminar (prefix '{prefix}'): {len(to_remove)}")
    for k in to_remove:
        print(f"  - {k}")
        del index[k]
    print(f"entradas restantes: {len(index)}")
    new_index_blob = zlib.compress(pickle.dumps(index, protocol=2))
    new_header = f"RPA-3.0 {index_offset:016x} {key:08x}\n".encode()
    if len(new_header) != len(header_line):
        print(f"WARN header size cambio {len(header_line)} -> {len(new_header)}; abortar")
        return
    with open(rpa_path, "r+b") as f:
        f.seek(0)
        f.write(new_header)
        f.seek(index_offset)
        f.write(new_index_blob)
        f.truncate(index_offset + len(new_index_blob))
    print(f"OK: nuevo size={os.path.getsize(rpa_path)}")

if __name__ == "__main__":
    main()
