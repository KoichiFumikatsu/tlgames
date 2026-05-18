import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from lib_rpy import parse_dialogue_file, parse_strings_file

root = pathlib.Path(sys.argv[1])
rows = []
for f in root.rglob("*.rpy"):
    ds = parse_dialogue_file(str(f))
    ss = parse_strings_file(str(f))
    p = sum(1 for b in (ds + ss) if not b.current_target.strip())
    if p:
        rows.append((p, str(f.relative_to(root)).replace("\\", "/")))

rows.sort(reverse=True)
print(f"files with pending: {len(rows)}")
for p, path in rows:
    print(f"{p:>3} | {path}")
