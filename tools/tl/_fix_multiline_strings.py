"""Repara strings de Ren'Py con newlines literales (saltos de línea reales)
dentro de comillas. Convierte cualquier salto interno en \\n.
"""
import sys, re, pathlib

ROOT = pathlib.Path(sys.argv[1])
fixed_total = 0

# Estado: dentro de string si hay un " sin cerrar en una línea
def fix_file(p: pathlib.Path) -> int:
    text = p.read_text(encoding="utf-8")
    lines = text.split("\n")
    out = []
    fixed = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        # Cuento " no escapadas en la línea
        unescaped = re.findall(r'(?<!\\)"', line)
        if len(unescaped) % 2 == 1:
            # Hay string sin cerrar; concateno hasta ver cierre
            buf = line
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                buf = buf + "\\n" + nxt.lstrip()
                fixed += 1
                u2 = re.findall(r'(?<!\\)"', nxt)
                if len(u2) % 2 == 1:
                    break
                j += 1
            out.append(buf)
            i = j + 1
        else:
            out.append(line)
            i += 1
    if fixed:
        p.write_text("\n".join(out), encoding="utf-8")
    return fixed

for f in ROOT.rglob("*.rpy"):
    n = fix_file(f)
    if n:
        fixed_total += n
        print(f"  {f.relative_to(ROOT)}: {n} líneas unidas")

print(f"\nTOTAL: {fixed_total} fixes")
