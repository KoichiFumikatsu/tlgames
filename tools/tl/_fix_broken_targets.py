"""One-shot: vaciar targets malformados generados por Ren'Py translate spanish
cuando el source EN tenia comillas escapadas (\\\")."""
import re, pathlib, sys

root = pathlib.Path(sys.argv[1])
# Pattern: indented + opening quote + any non-quote chars + backslash + space + "" at EOL
pat = re.compile(r'^(\s*)"(?:\\.|[^"\\])*\\ ""\s*$', re.MULTILINE)
n = 0
for f in root.rglob("*.rpy"):
    orig = f.read_text(encoding="utf-8")
    new = pat.sub(r'\1""', orig)
    if new != orig:
        f.write_text(new, encoding="utf-8")
        n += 1
        print(f"  fixed: {f.relative_to(root)}")
print(f"files fixed: {n}")
