"""Repara strings con sentinels ZT### que el MT devolvió sin la Z final.

Para cada bloque con `ZT\\d+` en el target:
  1. Lee el comentario `# "source"` que precede.
  2. Re-tokeniza el source con lib_rpy.tokenize() para reconstruir el mapping.
  3. Sustituye ZT### (con o sin Z final) por el token original.
"""
import sys, re, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from lib_rpy import tokenize  # noqa: E402

ROOT = pathlib.Path(sys.argv[1])
SENT_RE = re.compile(r"[Zz]\s*[Tt]\s*0*(\d+)\s*[Zz]?")

total_fixed = 0
total_blocks_fixed = 0

for fp in ROOT.rglob("*.rpy"):
    text = fp.read_text(encoding="utf-8")
    if "ZT" not in text:
        continue
    lines = text.split("\n")
    file_fixed = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        # buscar linea con ZT\d+ en target string
        if re.search(r"ZT\d+", line):
            # buscar comentario # "..." inmediatamente arriba (puede haber líneas en blanco)
            src_text = None
            for k in range(i - 1, max(-1, i - 6), -1):
                s = lines[k].strip()
                m = re.match(r'#\s*(?:\S+\s+)?"(.*)"\s*$', s)
                if m:
                    src_text = m.group(1)
                    break
                if s.startswith("translate "):
                    break
            if src_text is not None:
                _, mapping = tokenize(src_text)
                def repl(m, mp=mapping):
                    idx = int(m.group(1))
                    if 0 <= idx < len(mp):
                        return mp[idx][1]
                    return m.group(0)
                new_line = SENT_RE.sub(repl, line)
                if new_line != line:
                    lines[i] = new_line
                    file_fixed += 1
                    n = len(re.findall(r"ZT\d+", line)) - len(re.findall(r"ZT\d+", new_line))
                    total_fixed += n
        i += 1
    if file_fixed:
        fp.write_text("\n".join(lines), encoding="utf-8")
        total_blocks_fixed += file_fixed
        print(f"  {fp.name}: {file_fixed} bloques reparados")

print(f"\nTOTAL: {total_blocks_fixed} bloques, {total_fixed} sentinels restaurados")
