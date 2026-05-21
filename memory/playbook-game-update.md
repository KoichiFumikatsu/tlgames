# Playbook — Actualización de traducción cuando el juego recibe update

Cuando el desarrollador publica una nueva versión del juego, el objetivo es traducir
**solo el delta** (contenido nuevo o modificado) sin reprocesar lo que ya está traducido.
El cache existente es la fuente de verdad — no se toca lo que ya funciona.

---

## Fase 0 — Identificar la nueva versión

1. Descargar el nuevo build desde itch.io (u otra fuente) como ZIP.
2. Verificar la versión antes de extraer:

```python
import zipfile
z = zipfile.ZipFile('nuevo-build.zip')
# Buscar número de versión en rutas
tops = set(n.split('/')[0] for n in z.namelist())
print(tops)
```

3. Extraer **solo los archivos de localización** (no el juego completo):

```python
loc_files = [n for n in z.namelist() if 'Localization/source' in n]  # Unity nativo
# o el equivalente según el engine (ver playbooks específicos)
for n in loc_files:
    z.extract(n, 'new_version/')
```

> Si el juego no usa un directorio de localización identificable, extraer
> los archivos de texto equivalentes (JSON, CSV, .rpy, etc.) y comparar.

---

## Fase 1 — Comparar con la versión anterior

### Para archivos JSON planos (strings.json, grammar.json, etc.)

```python
def flatten(obj, path=''):
    out = {}
    if isinstance(obj, str):
        out[path] = obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f'{path}.{k}' if path else k))
    return out

with open('old/strings.json') as f: old = flatten(json.load(f))
with open('new/strings.json') as f: new = flatten(json.load(f))

added   = {k: v for k, v in new.items() if k not in old}
removed = {k for k in old if k not in new}
changed = {k: (old[k], new[k]) for k in new if k in old and old[k] != new[k]}
```

### Para archivos de escena / línea por línea

```python
import os

old_scenes, new_scenes = set(), set()
for root, _, files in os.walk('old/scenes'):
    for f in files:
        old_scenes.add(os.path.relpath(os.path.join(root, f), 'old/scenes'))
for root, _, files in os.walk('new/scenes'):
    for f in files:
        new_scenes.add(os.path.relpath(os.path.join(root, f), 'new/scenes'))

added_files   = new_scenes - old_scenes
removed_files = old_scenes - new_scenes
changed_files = []
for rel in sorted(new_scenes & old_scenes):
    with open(f'old/scenes/{rel}') as f: oc = f.read()
    with open(f'new/scenes/{rel}') as f: nc = f.read()
    if oc != nc:
        changed_files.append(rel)
```

### Para archivos Ren'Py / RPG Maker

Comparar el corpus extraído (JSONL) de la versión vieja vs. nueva.
Solo procesar los IDs que no están en el cache o cuyo source cambió.

---

## Fase 2 — Traducir solo el delta

**Regla:** si el ID ya está en el cache Y el source no cambió → reutilizar, no retraduce.

```python
with open('cache_strings.json') as f: cache = json.load(f)

# Solo traducir lo que es genuinamente nuevo
to_translate = {k: v for k, v in new_strings.items()
                if f'strings::{k}' not in cache}

# Para strings cuyo source cambió, invalidar el cache
for k, (old_src, new_src) in changed_strings.items():
    rec_id = f'strings::{k}'
    if rec_id in cache:
        del cache[rec_id]   # forzar re-traducción
        to_translate[k] = new_src
```

Traducir el delta con el mismo script/modelo que se usó originalmente
(ver `02_translate.py` en el _tl_work del juego correspondiente).

Para deltas pequeños (<50 strings) se puede hacer en un solo batch con `gpt-4.1-nano`.
Para deltas grandes (>200 strings) usar el pipeline completo con cache y recovery pass.

---

## Fase 3 — Regenerar el corpus traducido

Después de actualizar el cache, regenerar el JSONL de traducción desde el **nuevo source**:

```python
# Re-extraer desde la nueva fuente
records = extract_from_new_source()   # 01_extract.py equivalente

# Aplicar cache actualizado
with open(f'translated_{name}.jsonl', 'w') as f:
    for r in records:
        r['target'] = cache.get(r['id'], '')
        f.write(json.dumps(r, ensure_ascii=False) + '\n')
```

---

## Fase 4 — Actualizar rutas y versión en los scripts

En `03_rebuild.py`:
- Actualizar `SOURCE` para que apunte a la nueva versión extraída.
- Actualizar `VERSION` para que el `manifest.json` refleje la versión correcta.

```python
SOURCE  = "...new_version/.../Localization/source"
VERSION = "0.16.97"   # nueva versión
```

---

## Fase 5 — Rebuild y reempaquetar

```bash
python3 03_rebuild.py    # reconstruye es-kelsie/ desde el nuevo source
python3 04_build_zip.py  # genera es-kelsie.zip
```

Verificar que la salida no tenga WARNs de archivos no encontrados.

---

## Fase 6 — Actualizar el paquete de distribución

Si existe un ZIP de distribución (con instrucciones para el usuario final):

1. Actualizar la versión en `INSTRUCCIONES.txt`.
2. Reemplazar `es-kelsie.zip` dentro del paquete.
3. Reempaquetar y copiar al destino final (ej. `~/Documents/`).

```python
with zipfile.ZipFile('TheDemonLordsLover-ES-Kelsie.zip', 'w', ZIP_DEFLATED) as zf:
    zf.write('es-kelsie.zip')
    zf.write('INSTRUCCIONES.txt')
```

---

## Trampas comunes al actualizar

| Trampa | Síntoma | Fix |
|---|---|---|
| Apuntar `SOURCE` al directorio viejo | `manifest.json` con versión vieja; strings nuevas no aparecen | Actualizar `SOURCE` en `03_rebuild.py` |
| No invalidar cache de strings modificadas | Traducción vieja para texto nuevo | Detectar `changed` (source ≠ old source) y borrar del cache |
| Extraer el ZIP completo (1+ GB) | Lento, ocupa espacio | Extraer solo los archivos de localización con filtro |
| Olvidar actualizar `VERSION` en rebuild | `manifest.json` dice versión vieja | El juego puede rechazar el import o mostrar versión incorrecta |
| Regenerar JSONL desde source viejo | Strings nuevas con `target = ""` | Siempre regenerar el JSONL desde el **nuevo** source tras actualizar el cache |

---

## Caso real: The Demon Lord's Lover 0.16.90 → 0.16.97 (2026-05-21)

- Delta: 31 strings nuevas en `strings.json` (habilidades, tag_labels, UI)
- Grammar: sin cambios
- Scenes (369 archivos): sin cambios
- Costo delta: $0.0001
- Proceso completo: ~5 minutos
