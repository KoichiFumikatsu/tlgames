"""
Escanea los .rpy de origen (EN) y propone un glosario inicial para revision humana.

Salida: tools/tl/tl-es-glossary.json con secciones:
  - characters: nombres propios frecuentes (>=2 apariciones, capitalizados)
  - terms: palabras/frases tecnicas repetidas
  - placeholders: |msg_...| detectados (no se traducen, solo se listan)

El usuario revisa y completa las traducciones en 'target' antes de correr translate.py.
"""
import json
import re
from collections import Counter
from pathlib import Path

SRC_DIR = Path(r"C:\xampp\htdocs\tl\proyects Game TL\FromTheSin\game")
OUT = Path(__file__).parent / "tl-es-glossary.json"

# Archivos EN originales decompilados (no los tl/spanish)
SRC_FILES = [
    "script.rpy", "definitions.rpy", "achievements.rpy",
    "scene_trackers.rpy", "special_labels.rpy",
]

# Stopwords muy comunes que NO queremos como glosario
STOP = {
    "The", "And", "But", "You", "Your", "His", "Her", "That", "This", "With",
    "What", "When", "Where", "Why", "How", "Who", "Not", "For", "From", "Into",
    "Was", "Are", "Were", "Have", "Has", "Had", "Will", "Would", "Could", "Should",
    "Its", "They", "Their", "Them", "She", "Him", "Our", "Now", "Then", "Here",
    "There", "All", "Some", "One", "Two", "Three", "First", "Last", "Next",
    "After", "Before", "Again", "Still", "Just", "Only", "Very", "Well", "Also",
    "Yes", "No", "Yeah", "Okay", "Oh", "Ah", "Hey", "Hmm", "Uh", "Um",
    "Like", "Can", "Get", "Got", "Know", "See", "Let", "Come", "Go",
    "Say", "Said", "Tell", "Told", "Feel", "Felt", "Think", "Thought",
    "Make", "Made", "Take", "Took", "Give", "Gave", "Put",
    "A", "An", "I", "Me", "My", "Mine", "If", "Or", "So", "As", "At", "By", "In", "On", "To", "Of", "Up", "Be", "Is", "Do", "Did", "It",
}

def extract_dialogue_text(path: Path) -> list[str]:
    """Extrae strings de dialogo del .rpy original (no tl/)."""
    with path.open(encoding="utf-8", errors="ignore") as fh:
        content = fh.read()
    # Lineas tipo: char "text", "text", label "text"
    texts = []
    for m in re.finditer(r'^\s*(\S+\s+)?"((?:[^"\\]|\\.)*)"\s*$', content, re.MULTILINE):
        t = m.group(2)
        if t:
            texts.append(t)
    return texts

def strip_tags(text: str) -> str:
    text = re.sub(r"\{[^{}]*\}", " ", text)
    text = re.sub(r"\[[^\[\]]+\]", " ", text)
    text = re.sub(r"\|[A-Za-z0-9_]+\|", " ", text)
    text = text.replace("\\n", " ").replace("\\\"", '"')
    return text

def main():
    all_texts = []
    for name in SRC_FILES:
        p = SRC_DIR / name
        if not p.exists():
            print(f"skip (no existe): {p}")
            continue
        texts = extract_dialogue_text(p)
        print(f"{name}: {len(texts)} strings")
        all_texts.extend(texts)

    cleaned = [strip_tags(t) for t in all_texts]

    # 1. Nombres propios: capitalizados, no al inicio de oracion obvia
    name_counter: Counter = Counter()
    for text in cleaned:
        # Tokens con mayuscula inicial (no primera palabra de frase)
        for m in re.finditer(r"(?<![\.\?!]\s)(?<!^)\b([A-Z][a-zA-Z]{2,})\b", text):
            w = m.group(1)
            if w not in STOP:
                name_counter[w] += 1
        # Tambien palabras todas en mayuscula (eg SYSTEM, ERROR)
        for m in re.finditer(r"\b([A-Z]{3,})\b", text):
            w = m.group(1)
            if w not in STOP:
                name_counter[w] += 1

    # 2. Placeholders |msg_...|
    place_counter: Counter = Counter()
    for t in all_texts:
        for m in re.finditer(r"\|([A-Za-z0-9_]+)\|", t):
            place_counter[m.group(1)] += 1

    # 3. Terminos compuestos posibles: sustantivos repetidos >= 4 veces (heuristica blanda)
    # Lo dejamos para que el usuario agregue manualmente; por ahora solo sacamos top nombres.

    characters = {}
    terms = {}
    for word, count in name_counter.most_common():
        if count < 2:
            break
        entry = {"source": word, "target": "", "count": count, "notes": ""}
        # Heuristica: si esta en TODAS mayusculas, probablemente termino tecnico
        if word.isupper():
            terms[word] = entry
        else:
            characters[word] = entry

    placeholders = {p: {"count": c, "preserve": True} for p, c in place_counter.most_common()}

    glossary = {
        "_meta": {
            "generated_from": [str(SRC_DIR / n) for n in SRC_FILES],
            "instructions": (
                "Completa 'target' con la traduccion preferida. Deja '' para no forzar. "
                "characters: nombres propios (normalmente se mantienen igual). "
                "terms: tecnicismos que queremos traducir consistentemente."
            ),
        },
        "characters": characters,
        "terms": terms,
        "placeholders": placeholders,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        json.dump(glossary, fh, ensure_ascii=False, indent=2)
    print(f"\nGuardado: {OUT}")
    print(f"  characters: {len(characters)}")
    print(f"  terms: {len(terms)}")
    print(f"  placeholders: {len(placeholders)}")

if __name__ == "__main__":
    main()
