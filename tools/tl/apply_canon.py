"""
Pre-rellena el glosario con nombres canonicos confirmados en definitions.rpy.
El usuario solo revisa/ajusta lo ya pre-rellenado, no empieza desde cero.
"""
import json
from pathlib import Path

GLOSSARY = Path(__file__).parent / "tl-es-glossary.json"

# Canonicos confirmados (source -> target). Si target == source, solo sirve
# para proteger del MT (evita que "Linea" -> "linea").
CANON_CHARACTERS = {
    "Zell": "Zell",
    "Eris": "Eris",
    "Linea": "Linea",
    "Lily": "Lily",
    "Silika": "Silika",
    "Nova": "Nova",
    "Ada": "Ada",
    "Cluster": "Cluster",
    "Yurei": "Yurei",
    "Kironomiya": "Kironomiya",
    "Cetia": "Cetia",
    "Rinoa": "Rinoa",
    "Altra": "Altra",
    "Rika": "Rika",
    "Cibbon": "Cibbon",
    "Machine": "Maquina",
    "Machines": "Maquinas",
    "Unit": "Unidad",
    "Units": "Unidades",
}

CANON_TERMS = {
    # Compuestos primero (matchean por longitud desc, antes que los simples)
    "Third Precept": "Tercer Precepto",
    "Unit A.D.A. Type-00": "Unidad A.D.A. Tipo-00",
    "Eris and Linea": "Eris y Linea",
    # Sustantivos invariables / nombres propios de mundo
    "Mana": "Mana",
    # All-caps invariables (adverbios, imperativos, interjecciones, siglas)
    "CEU": "CEU",
    "ADA": "ADA",
    "WHY": "POR QUE",
    "STOP": "DETENTE",
    "WHAT": "QUE",
    "WHO": "QUIEN",
    "HUH": "EH",
    "BREATHE": "RESPIRA",
    "CAREFUL": "CUIDADO",
    "IMPOSSIBLE": "IMPOSIBLE",
    "PRESENCE": "PRESENCIA",
    "MOONS": "LUNAS",
    "SOOO": "TAAAN",
    "AAAAAAGGHH": "AAAAAAGGHH",
    # NO incluir sustantivos comunes (Precept, Brigade, Catalyst, Helix...)
    # ni adverbios/conjugaciones (THE, HIGH, COMING...). Dependen de
    # contexto - se delegan a MT con oracion completa.
}

# Terminos a LIMPIAR (vaciar target si estan rellenos con version incorrecta)
# Incluye:
#  - Adverbios/preps/conjugaciones (THE, HIGH, COMING...) que rompen
#    concordancia de genero/numero/tiempo.
#  - Sustantivos comunes traducibles (Precept, Brigade...) cuya traduccion
#    depende del articulo que los precede ("The Precepts: I" -> el MT
#    necesita ver el sustantivo entero para concordar). Se delegan al MT
#    con la oracion completa. Trade-off: pierden consistencia entre
#    apariciones (a veces "Precepto", a veces "Mandamiento") pero ganan
#    gramatica correcta. Los compuestos (Third Precept, Eris and Linea)
#    siguen en CANON_TERMS y se traducen como bloque.
CANON_TERMS_CLEAR = [
    # Adverbios/preposiciones/verbos conjugados
    "THE", "HIGH", "ELEVATED", "ANNOYING", "COMING", "BOWED",
    "FALLING", "UPON", "GUESS", "KNEW", "Elemental",
    # Sustantivos comunes (delegar a MT con contexto)
    "Precept", "Precepts", "Catalyst", "Brigade", "Helix", "Abyss",
    "Blessing", "Blessings", "Adventurers", "Crystal",
]

# Onomatopeyas: marcar como preservar (target = source para proteger del MT)
ONOMATOPEIAS = [
    "Sigh", "Haah", "Hah", "Gasp", "Slurp", "Lick", "Pant", "Panting",
    "Inhale", "Cough", "Sniff", "Giggle", "Giggles", "Mhm", "Ngh", "Hgn",
    "Ghn", "Hmmm", "Hmmmm", "Hmmmmmm", "Oooh", "Fuuu", "Haaah", "Heeey",
    "Aaand", "Hehehe", "Hooray",
]
for o in ONOMATOPEIAS:
    CANON_CHARACTERS.setdefault(o, o)

def main():
    data = json.loads(GLOSSARY.read_text(encoding="utf-8"))
    chars = data.setdefault("characters", {})
    terms = data.setdefault("terms", {})

    applied = 0
    for src, tgt in CANON_CHARACTERS.items():
        if src in chars and not chars[src]["target"]:
            chars[src]["target"] = tgt
            chars[src]["notes"] = "auto (canon)"
            applied += 1
        elif src not in chars:
            # Agregar si falta (nombre canonico no aparece en escaneo)
            chars[src] = {"source": src, "target": tgt, "count": 0, "notes": "auto (canon, manual)"}
            applied += 1

    for src, tgt in CANON_TERMS.items():
        if src in terms and not terms[src]["target"]:
            terms[src]["target"] = tgt
            terms[src]["notes"] = "auto (canon)"
            applied += 1
        elif src not in terms:
            terms[src] = {"source": src, "target": tgt, "count": 0, "notes": "auto (canon, manual)"}
            applied += 1

    cleared = 0
    for src in CANON_TERMS_CLEAR:
        for bucket in (terms, chars):
            if src in bucket and bucket[src].get("target"):
                bucket[src]["target"] = ""
                bucket[src]["notes"] = "cleared (depende de genero/numero, MT con contexto)"
                cleared += 1

    GLOSSARY.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"aplicados {applied} targets canonicos | vaciados {cleared} (genero/numero)")
    print(f"characters: {len(chars)} | terms: {len(terms)}")

if __name__ == "__main__":
    main()
