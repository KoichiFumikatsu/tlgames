"""
Guía de estilo ES compartida por los traductores LLM (OpenAI/Gemini) y por el QA.

Es la versión "de máquina" de la guía humana (memoria tl-es-style.md): reglas
cortas que caben en un system prompt. Cambiar aquí = cambia en todos los juegos.
"""

REGLAS_ESTILO = (
    "GUÍA DE ESTILO (español latinoamericano neutro):\n"
    "- Tuteo siempre ('tú', 'te', 'tu'); nada de 'vos' ni 'usted' salvo que el personaje sea formal o reverente en el original.\n"
    "- Nombres propios de personajes y lugares NO se traducen ni se adaptan (Alya sigue siendo Alya).\n"
    "- Términos del mundo con mayúscula (Precept, Catalyst, Brigade) se traducen conservando la mayúscula (Precepto, Catalizador, Brigada).\n"
    "- Onomatopeyas y suspiros (Sigh, Haah, Gasp, Mhm, Hehe, Ugh): no traducir literal; dejar igual o adaptar mínimo (*suspiro*, *jadeo*, jeje).\n"
    "- Gritos en MAYÚSCULAS (WHY, STOP, SOOO ANNOYING): traducir el contenido conservando las mayúsculas.\n"
    "- Nada de calcos: 'hacer sentido' → 'tener sentido', 'tener un buen tiempo' → 'pasarla bien', 'actualmente' (actually) → 'en realidad'.\n"
    "- Pensamientos entre paréntesis y puntos suspensivos se conservan tal cual.\n"
    "- Frases cortas y naturales; el español se expande, evita rodeos para que quepa en el cuadro de diálogo.\n"
    "- Signos de apertura ¿ ¡ en preguntas y exclamaciones normales; en gritos de una sola palabra en mayúsculas puede omitirse el de apertura.\n"
)


def con_estilo(prompt: str) -> str:
    """Anexa la guía de estilo a un system prompt existente."""
    return prompt.rstrip("\n") + "\n\n" + REGLAS_ESTILO
