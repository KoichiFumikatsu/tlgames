# Playbook — KPS Phone System (Kesash Phone System)

**Cuándo aplicar:** juegos Ren'Py que usan el sistema de "phone" de Kesash (autor `randomfox_` en Discord, itch.io: `kesash`). Detectado por:

- Archivo `game/phone.rpy` que define la función `kps_build_conversation_list(script_text)` (típicamente alrededor de la línea 620).
- Archivos `game/test_char_*.rpy` o similares con `default|define <name> = kps_build_conversation_list("""...""")` o `default|define <name> = [ {"speaker":"texto"}, ... ]`.
- Cabecera de copyright `© Kesash` en `phone.rpy`.

**Síntoma sin playbook:** `renpy translate spanish` del SDK genera solo `tl/spanish/{script,screens,common,options}.rpy`. Los chats del phone (que contienen 80%+ del contenido) quedan en inglés porque no son `say` statements ni strings marcados con `_("...")`. El pipeline reporta éxito pero el juego en español muestra casi todo en inglés.

---

## Estructura del contenido traducible

Los chats están en dos formatos coexistentes:

### Formato A — DSL plano dentro de triple-quote

```python
define angie_convo1 = kps_build_conversation_list("""
Angie: Happy birthday, baby!
Lycian: This is so awesome babe!
{"image":"Icons/KissyFace.svg", "sender":"Angie"}
["React with a sweet vibe", "Angie_C1"],["React with a naughty vibe", "Angie_C2"]
""")
```

Tipos de línea:
- `Speaker: mensaje` — diálogo (speaker arbitrario, lowercase o no).
- `{"key":"value", ...}` — dict de una línea. Keys especiales:
  - `image`, `video`, `sender`, `scale` → metadata, NO traducir.
  - `code` → código Python, NO traducir.
  - `system` → mensaje de sistema, TRADUCIR el valor.
  - `delete` → si valor es texto (no `.png/.svg/...`), TRADUCIR y debe coincidir con la traducción del mensaje original.
  - `reply` → TRADUCIR.
  - Cualquier otra key → es nombre de speaker, valor es mensaje, TRADUCIR.
- `[["text","branch"], ...]` o `["text","branch"],["text","branch"]` — choices. TRADUCIR solo índice 0 de cada sublista (el branch label es identificador interno).
- `code: codigo` o `code: '''multi\nline'''` o `code: """..."""` — código Python, NO traducir.

### Formato B — Lista Python literal multi-línea

```python
define iris_choice_2 = [
    {"iris":"You picked option 2 :)"},
    {"system":"User has gone offline"},
    [["Theres only one option", "iris_after_choices"]]
]
```

Mismas reglas semánticas que Formato A pero parseable directamente con `ast.parse(mode='eval')` envolviendo en `[...]`.

---

## Pipeline (auto)

Scripts en `tools/tl/`:

| Script | Función |
|---|---|
| `extract_kps_phone.py` | Detecta ambos formatos. Por bloque DSL: parser custom siguiendo la lógica de `phone.rpy:620`. Por literal: `ast.parse(eval)` + walk. Emite JSONL con offsets exactos `(file, line, col_start, col_end, source, kind, speaker)`. |
| `reinject_kps_phone.py` | Lee JSONL con `target`. Reemplazo posicional in-place, ORDEN DESCENDENTE por (line, col_start) para no descuadrar offsets. Backup `.kps_bak` por archivo. Escapa comillas según el delimitador detectado. |

### Comandos

```bash
# 1. Extraer corpus
python3 tools/tl/extract_kps_phone.py \
  game/phone.rpy game/test_char_*.rpy \
  --out _tl_work/<Juego>/corpus.jsonl

# 2. Traducir (script ad-hoc por juego, ver _tl_work/LimitsofDeviation/02_translate.py)
python3 _tl_work/<Juego>/02_translate.py

# 3. Reinyectar in-place sobre la copia ya traducida (con TL del pipeline)
python3 tools/tl/reinject_kps_phone.py _tl_work/<Juego>/corpus_translated_target.jsonl

# 4. Recompilar
rm "<target>/game/"test_char_*.rpyc
$RENPY_SDK "<target>" compile
$RENPY_SDK "<target>" lint   # opcional, verificación
```

---

## Trampas críticas

1. **El pipeline estándar reporta éxito sin traducir el phone.** Hay que correr este playbook como POST-paso al pipeline normal. No es opcional para juegos con KPS.

2. **`ast.literal_eval(line)` vs `ast.parse(mode='eval')`** — los literal blocks pueden contener referencias a variables (`{"code": sarah_starting_dialogue_conversation_populator}`). `literal_eval` falla; usar `ast.parse(mode='eval')` y caminar Constant nodes.

3. **`ast.literal_eval` en DSL devuelve tuple si la línea es `[...], [...]`** (no list). Hay que probar primero `"[" + line + "]"` (envoltura) y aceptar tuple → list.

4. **Offsets ast con envoltura `[` al inicio se desplazan +1 columna en línea 1**. Solución: envolver como `"[\n" + content + "\n]"` y compensar `line_offset = start_line - 2`.

5. **Bloques `code: '''...'''` multi-línea contienen código Python con strings que se ven en el juego** (ej. `kps_send_message_to_phone(conv, 'sender', 'TEXTO VISIBLE')`). El extractor los SALTA correctamente. Limitación conocida: esos strings no se traducen. Frecuencia: bajo (típicamente comentarios técnicos del autor); el contenido principal de la historia NO usa este patrón.

6. **Speaker validation:** filtrar speakers que no matchen `^[A-Za-z_][A-Za-z0-9_]*$` para evitar falsos positivos cuando una línea de código pseudo-Python entra al parser.

7. **F-strings `f"..."`** — son válidos en literal blocks (`{"kesash":f"If you want {var}"}`). El extractor actual los OMITE (ast.Constant solo captura literales puros). Si un juego los usa intensivamente, ampliar `emit_str_node` para aceptar `ast.JoinedStr` y reconstruir el f-string con piezas traducibles.

8. **Compilación in-place vs tl/spanish/:** este sistema NO usa `tl/<lang>/`. Las traducciones se escriben en los .rpy fuente directamente. Por eso:
   - `_force_spanish.rpy` del pipeline sigue siendo necesario (cambia preferences.language).
   - No hay archivo `tl/spanish/test_char_*.rpy` — el SDK no genera nada porque no detecta strings traducibles.
   - Borrar `.rpyc` viejos de los archivos modificados antes de recompilar.

9. **Strings hardcoded en screens (`text "Relationship Score"`)** — no cubierto por este playbook. Esos son strings normales de Ren'Py y deberían ir en `tl/spanish/screens.rpy` vía SDK estándar; verificar si el SDK los detecta.

---

## Decisiones técnicas

- **Por qué edición posicional y no regeneración del bloque:** preserva 100% el formato del autor (indentación, comentarios, líneas en blanco). Reduce riesgo de romper Python literal.
- **Por qué no incluir `code:` strings:** parseo robusto del Python interno requiere otro extractor recursivo. Costo > beneficio en los juegos vistos.
- **Por qué backup `.kps_bak` (no `.bak`):** distinguir del `.bak` que algunos juegos ya tienen por su cuenta.

---

## Historial de aplicación

| Juego | Versión | Strings extraídos | Resultado |
|---|---|---|---|
| Limits of Deviation Chapter 1 | pc (2026-05-04) | 587 (510 dialog, 51 system, 20 choice, 4 reply, 2 delete) | Aplicado 2026-05-24. ZIP en `~/Documents/games tl/LimitsofDeviation-Chapter_1-pc-spanish.zip` (170MB). Compile + lint OK. |
