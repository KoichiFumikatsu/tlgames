"""Traduce strings hardcoded `$ hint = "..."` en archivos .rpy del source.

Filtra los que ya están en español (heurística: contienen tildes/ñ o palabras ES comunes)
y manda los English a OpenAI gpt-4.1-nano. Reemplaza in-place con backup .hint-bak.

Uso:
  python tools\\tl\\_translate_hints_inline.py "proyects Game TL\\Broken Dreams\\game" --apply
"""
from __future__ import annotations
import argparse, json, os, re, shutil, sys, urllib.request
from pathlib import Path

HINT_RE = re.compile(r'^(\s*\$\s*hint\s*=\s*)"(.*)"\s*$')

def looks_spanish(s: str) -> bool:
    if any(ch in s for ch in "áéíóúñÁÉÍÓÚÑ¿¡üÜ"):
        return True
    es_words = {" la ", " el ", " los ", " las ", " que ", " mi ", " tu ",
                " soy ", " está ", " esta ", " este ", " pero ", " porque ",
                " ahora ", " también ", " todo ", " gracias "}
    low = " " + s.lower() + " "
    return sum(1 for w in es_words if w in low) >= 3

def translate_batch(texts: list[str], api_key: str) -> list[str]:
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {"type": "object",
                          "properties": {"i": {"type": "integer"}, "t": {"type": "string"}},
                          "required": ["i", "t"], "additionalProperties": False},
            }
        },
        "required": ["items"], "additionalProperties": False
    }
    payload = {
        "model": "gpt-4.1-nano",
        "messages": [
            {"role": "system",
             "content": "Translate hint/objective texts from English to Spanish (Latin America, neutral). Preserve tone of an internal monologue. Keep parenthetical instructions like '(GO TO THE LIBRARY)' translated as '(IR A LA BIBLIOTECA)'. Preserve line breaks (\\n) exactly. Do NOT add or remove punctuation. Output JSON {items:[{i, t}]}."},
            {"role": "user", "content": json.dumps([{"i": i, "s": t} for i, t in enumerate(texts)], ensure_ascii=False)}
        ],
        "response_format": {"type": "json_schema",
            "json_schema": {"name": "tl", "strict": True, "schema": schema}},
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode("utf-8"))
    items = json.loads(data["choices"][0]["message"]["content"])["items"]
    out = [""] * len(texts)
    for it in items:
        out[it["i"]] = it["t"]
    if any(not s for s in out):
        raise RuntimeError("missing items")
    usage = data.get("usage", {})
    print(f"  tokens in={usage.get('prompt_tokens')} out={usage.get('completion_tokens')}")
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    # Cargar .env
    env = Path("c:/xampp/htdocs/tl/.env").read_text(encoding="utf-8")
    api_key = next((l.split("=",1)[1].strip() for l in env.splitlines()
                    if l.startswith("OPENAI_API_KEY=")), None)
    if not api_key:
        sys.exit("OPENAI_API_KEY no encontrado en .env")

    root = Path(args.dir)
    hits = []  # (path, line_idx, prefix, text_en)
    for f in sorted(root.glob("*.rpy")):
        lines = f.read_text(encoding="utf-8").split("\n")
        for i, line in enumerate(lines):
            m = HINT_RE.match(line)
            if not m:
                continue
            text = m.group(2)
            if looks_spanish(text):
                continue
            hits.append((f, i, m.group(1), text))

    print(f"hits a traducir: {len(hits)}")
    if not hits:
        return
    for f, i, _, t in hits[:5]:
        print(f"  {f.name}:{i+1} {t[:80]}...")

    if not args.apply:
        print("\n[dry] use --apply")
        return

    # Traducir en un solo batch (33 strings caben sobrados)
    texts = [h[3] for h in hits]
    translated = translate_batch(texts, api_key)

    # Aplicar por archivo
    by_file: dict[Path, list] = {}
    for (f, i, prefix, _), tr in zip(hits, translated):
        by_file.setdefault(f, []).append((i, prefix, tr))

    for f, edits in by_file.items():
        bak = f.with_suffix(f.suffix + ".hint-bak")
        if not bak.exists():
            shutil.copy2(f, bak)
        lines = f.read_text(encoding="utf-8").split("\n")
        for i, prefix, tr in edits:
            # escapar comillas dobles literales en target
            tr_esc = tr.replace('\\', '\\\\').replace('"', '\\"')
            lines[i] = f'{prefix}"{tr_esc}"'
        f.write_text("\n".join(lines), encoding="utf-8")
        print(f"  [apply] {f.name}: {len(edits)} hints (backup: {bak.name})")

if __name__ == "__main__":
    main()
