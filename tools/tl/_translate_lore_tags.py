"""Traduce el contenido de los {lore=...} tags en los archivos tl/spanish/.

Flujo:
1. Extrae todos los textos dentro de {lore=...} en los .rpy de tl/spanish/
2. Los manda a OpenAI en un solo request
3. Reemplaza in-place en cada archivo

El tag tiene dos formatos:
  {lore=texto sin comillas}
  {lore="texto con comillas".}   (el punto y las comillas son parte del valor)

No se modifica la estructura del tag, solo el texto interior.
"""
import json, os, re, sys, urllib.request, pathlib

TL_DIR = pathlib.Path("/home/kelsie/projects/tlgames/proyects Game TL/Adventurer Trainer/Adv_Trainer/game/tl/spanish/")
API_KEY = os.environ.get("OPENAI_API_KEY", "")
MODEL   = "gpt-4.1-nano"

SYSTEM_PROMPT = """Eres un traductor profesional de inglés a español rioplatense (Argentina/Uruguay) especializado en visual novels.
Traduce SOLO el texto que te doy. Reglas estrictas:
- Conserva comillas si las hay al inicio/final
- Conserva el punto al final si lo hay (ej: "texto". → "texto traducido".)
- NO traduzcas _b..._/b (son marcadores de formato, déjalos exactos)
- Tono informal, natural, de anime/light novel
- Devuelve SOLO un array JSON con los strings traducidos, en el mismo orden, sin explicaciones"""

def call_openai(texts: list[str]) -> list[str]:
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts))
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Traduce estos {len(texts)} textos al español:\n\n{numbered}\n\nDevuelve un array JSON con exactamente {len(texts)} strings."}
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"}
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read())
    content = data["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    # El modelo puede devolver {"translations": [...]} o directamente [...]
    if isinstance(parsed, list):
        return [str(x) for x in parsed]
    if isinstance(parsed, dict):
        # Si tiene una clave con lista ({"translations": [...]})
        for v in parsed.values():
            if isinstance(v, list):
                return [str(x) for x in v]
        # Si las claves son números ("0", "1", ...) — formato alternativo del modelo
        try:
            keys_sorted = sorted(parsed.keys(), key=lambda k: int(k))
            return [str(parsed[k]) for k in keys_sorted]
        except (ValueError, TypeError):
            pass
    raise ValueError(f"Formato inesperado: {parsed}")

# ── 1. Recopilar todos los lore tags ──────────────────────────────────────────

LORE_RE = re.compile(r'\{lore=([^}]+)\}')

entries = []  # (path, line_index_0based, full_match, lore_content)

for path in sorted(TL_DIR.rglob("*.rpy")):
    if path.suffix == ".bak" or ".bak" in path.name:
        continue
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines(keepends=True)
    for li, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("old "):
            continue
        for m in LORE_RE.finditer(line):
            entries.append({
                "path": path,
                "line": li,
                "start": m.start(1),
                "end": m.end(1),
                "original": m.group(1),
            })

print(f"[lore] Encontrados {len(entries)} lore tags")

if not entries:
    sys.exit(0)

if not API_KEY:
    sys.exit("[lore] ERROR: OPENAI_API_KEY no está seteada")

# ── 2. Traducir ───────────────────────────────────────────────────────────────

originals = [e["original"] for e in entries]
print(f"[lore] Enviando {len(originals)} strings a OpenAI ({MODEL})...")

try:
    translations = call_openai(originals)
except Exception as ex:
    sys.exit(f"[lore] ERROR en API: {ex}")

if len(translations) != len(originals):
    sys.exit(f"[lore] Respuesta inválida: esperaba {len(originals)}, recibí {len(translations)}")

# ── 3. Mostrar diff y aplicar ─────────────────────────────────────────────────

# Agrupar cambios por archivo
from collections import defaultdict
changes_by_file = defaultdict(list)
for i, (e, t) in enumerate(zip(entries, translations)):
    if e["original"] != t:
        changes_by_file[e["path"]].append((e["line"], e["start"], e["end"], e["original"], t))

print(f"\n[lore] {sum(len(v) for v in changes_by_file.values())} reemplazos a aplicar en {len(changes_by_file)} archivos\n")

for path, changes in sorted(changes_by_file.items()):
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
    # Aplicar cambios en orden inverso para no desplazar índices
    changes_by_line = defaultdict(list)
    for line_i, start, end, orig, trans in changes:
        changes_by_line[line_i].append((start, end, orig, trans))

    for li in sorted(changes_by_line.keys(), reverse=True):
        line = lines[li]
        # Reemplazar de derecha a izquierda en la misma línea
        for start, end, orig, trans in sorted(changes_by_line[li], key=lambda x: x[0], reverse=True):
            line = line[:start] + trans + line[end:]
            print(f"  {path.name}:{li+1}")
            print(f"    EN: {orig}")
            print(f"    ES: {trans}")
        lines[li] = line

    path.write_text("".join(lines), encoding="utf-8")

print(f"\n[lore] ✓ Traducción de lore tags completada")
