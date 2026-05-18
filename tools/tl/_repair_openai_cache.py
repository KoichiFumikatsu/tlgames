import json
from datetime import datetime
from pathlib import Path

p = Path("tools/tl/.cache/openai.json")
if not p.exists():
    raise SystemExit(f"cache not found: {p}")

s = p.read_text(encoding="utf-8")
bak = p.with_name("openai.json.bak_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
bak.write_text(s, encoding="utf-8")

try:
    json.loads(s)
    print("cache OK")
except json.JSONDecodeError as e:
    print(f"broken at pos={e.pos} line={e.lineno} col={e.colno}")
    head = s[: e.pos].rstrip()
    while head and head[-1] not in "}]":
        head = head[:-1]
    obj = json.loads(head)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"cache repaired, backup={bak}")
