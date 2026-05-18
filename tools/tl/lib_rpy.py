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
        # Extraer char y source del comentario
        cm = re.match(r'#\s*(\S+)?\s*"(.*)"\s*$', lines[comment_line].strip())
        if not cm:
            # Caso narrador: # "..."
            cm = re.match(r'#\s*"(.*)"\s*$', lines[comment_line].strip())
            if not cm:
                i += 1
                continue
            char = ""
            source = cm.group(1)
        else:
            char = cm.group(1) or ""
            source = cm.group(2)
        # Extraer target actual
        tm = re.match(r'(\S+)?\s*"(.*)"\s*$', lines[target_line].strip())
        current = tm.group(2) if tm else ""
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
    # Caso 'char "..."' o '"..."'
    m = re.match(r'(\S+)?\s*"(.*)"\s*$', rest)
    if not m:
        return original_line
    char = m.group(1) or ""
    if char:
        return f'{indent}{char} "{_escape(new_text)}"\n'
    return f'{indent}"{_escape(new_text)}"\n'

def _escape(text: str) -> str:
    """Escapa comillas internas sin tocar las ya escapadas."""
    # Paso 1: proteger secuencias ya escapadas
    # Simple: reemplazar " por \" si no esta ya escapado
    return re.sub(r'(?<!\\)"', r'\\"', text)
