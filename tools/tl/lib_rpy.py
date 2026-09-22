"""
Utilidades compartidas: parseo de .rpy de traduccion y tokenizacion de tags.

Dos formatos soportados:
  A) translate spanish <label>: con pares "# char \"source\"" + char ""
  B) translate spanish strings: con pares old "..." / new ""
"""
import re
from dataclasses import dataclass, field
from typing import Optional

# Tokens a proteger (orden importa: los mas especificos primero)
TOKEN_PATTERNS = [
    (re.compile(r"\{[a-zA-Z_][^{}]*\}"), "TAG"),       # {color=#00ff00}, {i}, {/color}, etc.
    (re.compile(r"\[[^\[\]]+\]"), "VAR"),              # [mc], [name!t]
    (re.compile(r"\|[A-Za-z0-9_]+\|"), "PLACE"),       # |msg_Thinking_Question1|
    (re.compile(r"\\n"), "NL"),                        # literal \n
    (re.compile(r"\\\""), "QUOTE"),                    # escaped quote
    (re.compile(r"%\([a-zA-Z_]+\)[sd]"), "PCT"),       # %(name)s formatting
]

# Línea de diálogo Ren'Py: [quién [atributos…]] "texto" [nointeract | with X | (multiple=2) …]
# El prefijo y el sufijo no llevan comillas; el texto admite \" escapadas.
DIALOGO_RE = re.compile(r'^([^"]*?)\s*"((?:[^"\\]|\\.)*)"\s*([^"]*?)\s*$')


def partir_dialogo(linea: str):
    """(prefijo, texto, sufijo) de una línea de diálogo ya sin indentación ni '#', o None."""
    m = DIALOGO_RE.match(linea.strip())
    if not m:
        return None
    return m.group(1).strip(), m.group(2), m.group(3).strip()


@dataclass
class DialogueBlock:
    """Bloque 'translate spanish <label>:' del script.rpy."""
    label: str
    char: str                   # mc, pc, pcu, un, "" (narrador)
    source: str                 # texto EN original
    line_start: int             # 0-indexed line del bloque 'translate'
    line_comment: int           # linea del '# char "source"'
    line_target: int            # linea del 'char ""'
    current_target: str         # contenido actual de la linea target (vacio o ya traducido)
    kind: str = "dialogue"

@dataclass
class StringBlock:
    """Par old/new dentro de 'translate spanish strings:'."""
    source: str
    line_old: int
    line_new: int
    current_target: str
    kind: str = "string"
    source_file: str = ""       # path original del comentario (renpy/common/...)

def tokenize(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Reemplaza tokens por sentinelas T0_NN y devuelve (texto_tokenizado, mapa)."""
    mapping = []
    def repl(match, kind):
        idx = len(mapping)
        mapping.append((kind, match.group(0)))
        # Usar marcador que MT no rompa: letras + digitos
        return f"ZT{idx:03d}Z"
    out = text
    for pat, kind in TOKEN_PATTERNS:
        out = pat.sub(lambda m, k=kind: repl(m, k), out)
    return out, mapping

def detokenize(text: str, mapping: list[tuple[str, str]]) -> str:
    """Restaura tokens. Tolera espacios/mayusculas introducidos por MT."""
    for idx, (_kind, original) in enumerate(mapping):
        # MT puede devolver Zt001Z, ZT 001 Z, zt001z, etc.
        pat = re.compile(rf"[Zz]\s*[Tt]\s*0*{idx}\s*[Zz]")
        text = pat.sub(lambda m, o=original: o, text)
    return text

_NL_DESPUES = re.compile(r"(\\n)\.?[ \t]+")   # "\n. Por favor" / "\n Por favor" → "\nPor favor"
_NL_ANTES = re.compile(r"[ \t]+(\\n)")        # "Store \n" → "Store\n"


def normalizar_saltos(source: str, target: str) -> str:
    """El MT trata el sentinela de \\n como palabra y le pega '. ' o espacios alrededor.
    Se limpian sólo cuando el source no los tiene (respeta "\\n " o " \\n" originales)."""
    if "\\n" not in target:
        return target
    if not re.search(r"\\n\.?[ \t]", source):
        target = _NL_DESPUES.sub(r"\1", target)
    if not re.search(r"[ \t]\\n", source):
        target = _NL_ANTES.sub(r"\1", target)
    return target


def parse_dialogue_file(path: str) -> list[DialogueBlock]:
    """Parsea un .rpy de dialogos (script.rpy style)."""
    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()
    blocks: list[DialogueBlock] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"translate\s+spanish\s+(\S+):\s*$", line, re.IGNORECASE)
        if not m:
            i += 1
            continue
        label = m.group(1)
        line_start = i
        # Buscar siguiente '# char "source"' y la linea de destino
        j = i + 1
        comment_line = None
        target_line = None
        while j < len(lines):
            stripped = lines[j].strip()
            if re.match(r"translate\s+spanish\s+", stripped, re.IGNORECASE):
                break
            if comment_line is None and stripped.startswith("#"):
                # Solo es comentario de fuente si tiene comillas
                if '"' in stripped:
                    comment_line = j
            elif comment_line is not None and target_line is None and stripped:
                # Primera linea no vacia no-comentario despues del comentario
                target_line = j
                break
            j += 1
        if comment_line is None or target_line is None:
            i += 1
            continue
        # Extraer char y source del comentario: '# ve neu "texto" nointeract' → char "ve neu"
        cp = partir_dialogo(lines[comment_line].strip().lstrip("#"))
        if not cp:
            i += 1
            continue
        char, source, _ = cp
        # Extraer target actual (misma forma, con o sin atributos/sufijo)
        tp = partir_dialogo(lines[target_line])
        current = tp[1] if tp else ""
        blocks.append(DialogueBlock(
            label=label, char=char, source=source,
            line_start=line_start, line_comment=comment_line,
            line_target=target_line, current_target=current,
        ))
        i = j if j > i else i + 1
    return blocks

def parse_strings_file(path: str) -> list[StringBlock]:
    """Parsea un .rpy con 'translate spanish strings:'."""
    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()
    blocks: list[StringBlock] = []
    i = 0
    current_src_comment = ""
    while i < len(lines):
        stripped = lines[i].strip()
        # Capturar comentario de origen: # renpy/common/00xxx.rpy:N
        cm = re.match(r"#\s*([^\s\"]+\.rpy):\d+", stripped)
        if cm:
            current_src_comment = cm.group(1)
        m = re.match(r'old\s+"(.*)"\s*$', stripped)
        if not m:
            i += 1
            continue
        source = m.group(1)
        line_old = i
        # Siguiente linea deberia ser 'new "..."'
        if i + 1 >= len(lines):
            break
        nm = re.match(r'new\s+"(.*)"\s*$', lines[i + 1].strip())
        if not nm:
            i += 1
            continue
        blocks.append(StringBlock(
            source=source, line_old=line_old, line_new=i + 1,
            current_target=nm.group(1), source_file=current_src_comment,
        ))
        i += 2
    return blocks

def write_target_line(original_line: str, new_text: str) -> str:
    """Reemplaza el contenido entre comillas preservando indentacion y prefijo (char)."""
    # Detectar indent
    indent_match = re.match(r"(\s*)", original_line)
    indent = indent_match.group(1) if indent_match else ""
    rest = original_line.strip()
    # Caso 'old "..."' / 'new "..."'
    if rest.startswith("new ") or rest.startswith("old "):
        prefix = rest.split('"', 1)[0]
        return f'{indent}{prefix}"{_escape(new_text)}"\n'
    # Caso 'char [atributos] "..." [sufijo]' o '"..."': se conservan prefijo y sufijo
    p = partir_dialogo(rest)
    if not p:
        return original_line
    prefijo, _, sufijo = p
    return f'{indent}{prefijo + " " if prefijo else ""}"{_escape(new_text)}"{" " + sufijo if sufijo else ""}\n'

def _escape(text: str) -> str:
    """Escapa comillas internas sin tocar las ya escapadas, y los saltos de línea reales (romperían el .rpy)."""
    text = text.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")
    # Paso 1: proteger secuencias ya escapadas
    # Simple: reemplazar " por \" si no esta ya escapado
    return re.sub(r'(?<!\\)"', r'\\"', text)
