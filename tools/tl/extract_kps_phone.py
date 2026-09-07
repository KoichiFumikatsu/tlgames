#!/usr/bin/env python3
# Extrae strings traducibles del sistema phone "KPS" (Kesash Phone System).
# Detecta:
#   1) Bloques DSL: kps_build_conversation_list(""" ... """)
#   2) Bloques Python literal: (define|default) NAME = [ ... ]
#
# Por linea reconoce: Speaker: msg | {dict} | [choices] | code:... (skip)
# Emite JSONL: {"id","file","line","col_start","col_end","source","kind","speaker"}
# kind: dialog|system|choice|delete|reply
#
# Uso: python3 extract_kps_phone.py <archivo.rpy>...  --out corpus.jsonl

import argparse
import ast
import io
import json
import re
import sys
import tokenize
from pathlib import Path

SPECIAL_KEYS = {"image", "video", "sender", "scale", "code"}
ASSET_EXT_RE = re.compile(r"\.(png|jpg|jpeg|svg|gif|webp|mp4|webm|wav|ogg|mp3)$", re.I)

BLOCK_DSL_RE = re.compile(
    r'(?P<head>(?:default|define)\s+\w+\s*=\s*kps_build_conversation_list\s*\(\s*)"""',
)
BLOCK_LITERAL_RE = re.compile(
    r'^(?P<head>(?:default|define)\s+\w+\s*=\s*)\[',
    re.M,
)


def _line_col_of(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    last_nl = text.rfind("\n", 0, offset)
    col = offset - (last_nl + 1)
    return line, col


def _string_token_offsets(line_text: str):
    """Devuelve lista de (col_start, col_end, value) para cada token STRING en la linea."""
    out = []
    try:
        toks = list(tokenize.tokenize(io.BytesIO(line_text.encode("utf-8")).readline))
    except tokenize.TokenizeError:
        return out
    for tok in toks:
        if tok.type != tokenize.STRING:
            continue
        # tok.start = (lineno, col)  ; tok.end = (lineno, col)
        if tok.start[0] != tok.end[0]:
            continue  # solo single-line strings dentro de la linea
        col_s = tok.start[1]
        col_e = tok.end[1]
        raw = tok.string
        # Excluir f-strings? Conservar pero anotar.
        try:
            val = ast.literal_eval(raw)
            if not isinstance(val, str):
                continue
        except Exception:
            # f-string o algo raro: usar contenido entre comillas
            if raw.startswith(("f", "F", "rf", "Rf", "rF", "RF")):
                # f-string: extraer literal entre comillas. Reinyectar conservaria el prefijo.
                m = re.match(r'^[fFrR]+(["\'])(.*)\1$', raw, re.S)
                if not m:
                    continue
                val = m.group(2)
            else:
                continue
        out.append((col_s, col_e, val))
    return out


def _is_asset_path(s: str) -> bool:
    return bool(ASSET_EXT_RE.search(s.strip()))


def _emit_dialog(entries, file_path, line_no, col_s, col_e, src, speaker, kind):
    if not src.strip():
        return
    if _is_asset_path(src):
        return
    eid = f"{file_path.name}:{line_no}:{col_s}"
    entries.append({
        "id": eid,
        "file": str(file_path),
        "line": line_no,
        "col_start": col_s,
        "col_end": col_e,
        "source": src,
        "kind": kind,
        "speaker": speaker,
    })


def _scan_line(line_text: str, line_no: int, file_path: Path, entries: list):
    """Analiza una sola linea del bloque y emite traducibles."""
    stripped = line_text.strip()
    if not stripped or stripped.startswith("#"):
        return

    # Identificar comentarios inline (despues de codigo). Simple: cortar en " #" no dentro de string.
    # Por simplicidad omitimos esa limpieza; la linea se procesa entera.

    # CASE 1: dict de una sola linea  {"k":"v", ...}
    if stripped.startswith("{") and stripped.endswith("}") or (
        stripped.startswith("{") and stripped.endswith("},")
    ):
        # Intentar parsear el dict para entender semantica
        text_for_eval = stripped.rstrip(",")
        parsed = None
        try:
            parsed = ast.literal_eval(text_for_eval)
        except Exception:
            # Puede contener f"..." que ast no acepta. Caer a token-based.
            pass

        strings = _string_token_offsets(line_text)
        # Cada par ordenado en `strings` deberia mapear a clave/valor del dict en orden:
        # token0=key1, token1=val1, token2=key2, token3=val2, ...
        if isinstance(parsed, dict):
            keys = list(parsed.keys())
            values = list(parsed.values())
            # Mapeo asumiendo orden estable Python 3.7+
            pairs = []
            it = iter(strings)
            for k, v in zip(keys, values):
                try:
                    k_tok = next(it)
                    v_tok = next(it)
                except StopIteration:
                    break
                pairs.append((k, k_tok, v, v_tok))
            for k, k_tok, v, v_tok in pairs:
                if not isinstance(v, str):
                    continue
                if k == "code":
                    continue
                if k in SPECIAL_KEYS:
                    continue
                if k == "system":
                    _emit_dialog(entries, file_path, line_no, v_tok[0], v_tok[1], v, "system", "system")
                elif k == "delete":
                    if not _is_asset_path(v):
                        _emit_dialog(entries, file_path, line_no, v_tok[0], v_tok[1], v, "delete", "delete")
                elif k == "reply":
                    _emit_dialog(entries, file_path, line_no, v_tok[0], v_tok[1], v, "reply", "reply")
                else:
                    # Speaker key
                    _emit_dialog(entries, file_path, line_no, v_tok[0], v_tok[1], v, k, "dialog")
        else:
            # Fallback: si no parsea, ignorar (probablemente f-string complejo)
            return
        return

    # CASE 2: choices  [["text","branch"], ...]   o   ["text","branch"], ["text2","branch2"]
    if stripped.startswith("["):
        # Envolver en lista para asegurar parseo uniforme
        candidates = ["[" + stripped + "]", stripped]
        parsed = None
        for cand in candidates:
            try:
                parsed = ast.literal_eval(cand)
                break
            except Exception:
                continue
        # Aceptar tuples y normalizar a lista
        if isinstance(parsed, tuple):
            parsed = list(parsed)
        if not isinstance(parsed, list):
            return
        # Desempaquetar wrappers
        if len(parsed) == 1 and isinstance(parsed[0], list) and parsed[0] and isinstance(parsed[0][0], list):
            parsed = parsed[0]
        elif len(parsed) == 1 and isinstance(parsed[0], list) and parsed[0] and isinstance(parsed[0][0], (list, tuple)):
            parsed = list(parsed[0])
        strings = _string_token_offsets(line_text)
        # Cada sublista [text, branch] aporta 2 strings (a veces solo 1 si branch es ident)
        # Vamos a iterar matchando 1 a 1 string-token con elementos string del array aplanado.
        flat_vals = []
        for sub in parsed:
            if isinstance(sub, list) and sub:
                flat_vals.extend([(i, x) for i, x in enumerate(sub) if isinstance(x, str)])
        if not flat_vals:
            return
        for (idx_in_sub, val), tok in zip(flat_vals, strings):
            # Solo el primer string de cada sublista es texto visible (choice label)
            if idx_in_sub == 0:
                _emit_dialog(entries, file_path, line_no, tok[0], tok[1], val, "speaker", "choice")
        return

    # CASE 3: Speaker: msg
    # Mismo logic que phone.rpy: find primer ":" en la linea (sin lstrip)
    work = line_text.lstrip()
    indent = len(line_text) - len(work)
    colon = work.find(":")
    if colon == -1:
        return
    speaker = work[:colon].strip()
    if speaker == "code":
        return
    # Speakers invalidos (probablemente codigo o algo no-dialogo)
    if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', speaker):
        return
    msg = work[colon + 1:]
    msg_lstripped = msg.lstrip(" \t")
    leading_ws = len(msg) - len(msg_lstripped)
    msg_clean = msg_lstripped.rstrip()
    if not msg_clean:
        return
    if _is_asset_path(msg_clean):
        return
    col_s = indent + colon + 1 + leading_ws
    col_e = col_s + len(msg_clean)
    # Mapear speakers especiales a su kind
    kind = "dialog"
    if speaker == "system":
        kind = "system"
    elif speaker == "delete":
        kind = "delete"
    elif speaker == "image" or speaker == "video":
        return
    _emit_dialog(entries, file_path, line_no, col_s, col_e, msg_clean, speaker, kind)


def _scan_dsl_block(text: str, start_line: int, file_path: Path, entries: list):
    """Procesa lineas crudas del bloque DSL. start_line es el num de linea de la primera linea de contenido."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if not stripped:
            i += 1
            continue

        # Detectar code: ''' o code: """  (multi-linea code) -> skip todo el bloque
        # Usar mismo metodo que phone.rpy
        work = raw.lstrip()
        colon = work.find(":")
        if colon != -1:
            speaker = work[:colon].strip()
            msg = work[colon + 1:].lstrip(" \t")
            if speaker == "code" and msg.startswith(("'''", '"""', "```")):
                delim = msg[:3]
                rest = msg[3:]
                if delim in rest:
                    i += 1
                    continue
                i += 1
                while i < len(lines):
                    if delim in lines[i]:
                        break
                    i += 1
                i += 1
                continue

        _scan_line(raw, start_line + i, file_path, entries)
        i += 1


def _scan_literal_block(text: str, start_line: int, file_path: Path, entries: list, file_text: str):
    """Parsea el bloque [ ... ] con ast y emite strings con offsets reales del archivo.
    text: contenido entre [ y ] (sin los corchetes externos).
    start_line: linea (1-based) del archivo donde empieza el contenido.
    file_text: texto completo del archivo para mapear offsets a (line,col).
    """
    # Envolver con \n para que las columnas no se desplacen.
    # Linea 1 de src = "[", linea 2 = primera linea real de content.
    src = "[\n" + text + "\n]"
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError:
        return

    # linea_archivo = start_line + (lineno_src - 2)
    line_offset = start_line - 2

    file_lines = file_text.splitlines()

    def emit_str_node(node, kind: str, speaker: str):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            return
        line_no = node.lineno + line_offset
        col_s = node.col_offset
        col_e = node.end_col_offset
        if line_no - 1 >= len(file_lines):
            return
        # El nodo puede ocupar varias lineas (triple-quoted) — saltar
        if node.end_lineno != node.lineno:
            return
        src_val = node.value
        _emit_dialog(entries, file_path, line_no, col_s, col_e, src_val, speaker, kind)

    def walk_list_value(v):
        if isinstance(v, ast.List):
            # Choice list: [text, branch_label]  o  [[text, branch], [text, branch]]
            for elt in v.elts:
                if isinstance(elt, ast.List) and elt.elts:
                    first = elt.elts[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        emit_str_node(first, "choice", "choice")
                elif isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    # Forma plana [text, branch] - solo primer string
                    if elt is v.elts[0]:
                        emit_str_node(elt, "choice", "choice")

    def walk_dict(d):
        for k, v in zip(d.keys, d.values):
            if not isinstance(k, ast.Constant) or not isinstance(k.value, str):
                continue
            key = k.value
            if key == "code":
                continue
            if key in SPECIAL_KEYS:
                continue
            if not isinstance(v, ast.Constant):
                continue
            if not isinstance(v.value, str):
                continue
            if key == "system":
                emit_str_node(v, "system", "system")
            elif key == "delete":
                if not _is_asset_path(v.value):
                    emit_str_node(v, "delete", "delete")
            elif key == "reply":
                emit_str_node(v, "reply", "reply")
            else:
                # Speaker key
                emit_str_node(v, "dialog", key)

    outer = tree.body
    if not isinstance(outer, ast.List):
        return
    for item in outer.elts:
        if isinstance(item, ast.Dict):
            walk_dict(item)
        elif isinstance(item, ast.List):
            walk_list_value(item)


def _find_dsl_blocks(text: str):
    """Encuentra todos los bloques kps_build_conversation_list(\"\"\"...\"\"\")
    Devuelve list[(content, start_line_of_content)]."""
    out = []
    pos = 0
    while True:
        m = BLOCK_DSL_RE.search(text, pos)
        if not m:
            break
        # Buscar """ de cierre
        open_end = m.end()  # justo despues del primer """
        close = text.find('"""', open_end)
        if close == -1:
            break
        content = text[open_end:close]
        # start line: la primera linea de contenido es la que sigue al """
        start_line = text.count("\n", 0, open_end) + 1
        # Si el primer caracter es \n, el contenido real empieza en la siguiente
        if content.startswith("\n"):
            content = content[1:]
            start_line += 1
        out.append((content, start_line))
        pos = close + 3
    return out


def _find_literal_blocks(text: str):
    """Encuentra (define|default) NAME = [ ... ] con balance de corchetes.
    Excluye los que estan dentro de kps_build_conversation_list (no aplica, sintaxis diferente)."""
    out = []
    for m in BLOCK_LITERAL_RE.finditer(text):
        start = m.end() - 1  # posicion del '['
        # Balance bracket
        depth = 0
        in_str = None
        i = start
        N = len(text)
        while i < N:
            c = text[i]
            if in_str:
                if c == "\\":
                    i += 2
                    continue
                if c == in_str:
                    in_str = None
                i += 1
                continue
            if c in ('"', "'"):
                # detectar triple
                if text[i:i+3] in ('"""', "'''"):
                    triple = text[i:i+3]
                    end = text.find(triple, i+3)
                    if end == -1:
                        i = N
                        break
                    i = end + 3
                    continue
                in_str = c
                i += 1
                continue
            if c == "#":
                # comentario hasta fin de linea
                nl = text.find("\n", i)
                i = (nl if nl != -1 else N)
                continue
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    end_block = i  # inclusivo
                    content = text[start + 1:end_block]
                    start_line = text.count("\n", 0, start + 1) + 1
                    if content.startswith("\n"):
                        content = content[1:]
                        start_line += 1
                    out.append((content, start_line))
                    break
            i += 1
    return out


def extract_file(path: Path) -> list:
    text = path.read_text(encoding="utf-8")
    entries = []
    for content, start_line in _find_dsl_blocks(text):
        _scan_dsl_block(content, start_line, path, entries)
    for content, start_line in _find_literal_blocks(text):
        _scan_literal_block(content, start_line, path, entries, text)
    return entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", help="archivos .rpy a procesar")
    ap.add_argument("--out", required=True, help="JSONL de salida")
    args = ap.parse_args()

    all_entries = []
    for f in args.files:
        p = Path(f)
        ents = extract_file(p)
        all_entries.extend(ents)
        print(f"[extract] {p.name}: {len(ents)} strings", file=sys.stderr)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for e in all_entries:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"[extract] total: {len(all_entries)} -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
