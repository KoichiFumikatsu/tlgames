"""Cuenta bloques pendientes (target vacio) y caracteres source totales."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from lib_rpy import parse_dialogue_file, parse_strings_file

root = pathlib.Path(sys.argv[1])
total_blocks = total_pending = total_chars_pending = 0
for f in root.rglob("*.rpy"):
    try:
        ds = parse_dialogue_file(str(f))
        ss = parse_strings_file(str(f))
    except Exception as e:
        print(f"  SKIP {f.name}: {e}")
        continue
    for b in ds + ss:
        total_blocks += 1
        if not b.current_target.strip():
            total_pending += 1
            total_chars_pending += len(b.source)
print(f"archivos: {sum(1 for _ in root.rglob('*.rpy'))}")
print(f"bloques totales: {total_blocks}")
print(f"bloques pendientes: {total_pending}")
print(f"chars EN pendientes: {total_chars_pending:,}")
