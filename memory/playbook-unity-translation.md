# Playbook: Traduccion de Juegos Unity al Espanol

Procedimiento inicial para juegos Unity. A diferencia de Ren'Py, no se empieza traduciendo; se empieza clasificando el build.

## Fase 0 — Preparacion

1. Copiar el juego completo a `proyects Game TL/Unity/<Juego>/`.
2. Crear backup completo:

```powershell
Copy-Item -Recurse "proyects Game TL\Unity\<Juego>" "backups\Unity\<Juego>-original"
```

3. No modificar archivos originales hasta terminar la inspeccion.

Requisitos Python utiles para automatizacion Unity:

```powershell
python -m pip install UnityPy
```

`UnityPy` permite leer bundles y assets desde scripts. Usarlo para inventario/extraccion antes de abrir herramientas GUI.

## Fase 1 — Identificar tipo de build

Revisar:

```text
<Juego>_Data/
  Managed/Assembly-CSharp.dll        # Mono
  il2cpp_data/                       # IL2CPP
  StreamingAssets/
  Resources/
```

Criterios:

- Si existe `<Juego>_Data/Managed/Assembly-CSharp.dll`: build Mono, inspeccionable con dnSpyEx.
- Si existe `<Juego>_Data/il2cpp_data/`: build IL2CPP, evitar parche de codigo como primera opcion.
- Si existe `StreamingAssets/aa/`: probable Addressables.
- Si existen JSON/CSV/XML/TXT sueltos: revisar antes que assets binarios.

## Fase 2 — Inventario de texto

Buscar archivos candidatos:

```powershell
Get-ChildItem "<Juego>_Data" -Recurse -Include *.json,*.csv,*.xml,*.txt,*.bytes | Select-Object FullName,Length
```

Buscar texto ingles plano:

```powershell
Select-String -Path "<Juego>_Data\*" -Pattern "New Game|Settings|Continue|Start|Exit" -Recurse -ErrorAction SilentlyContinue
```

Si hay Addressables, inspeccionar `StreamingAssets/aa/` y bundles con AssetRipper/UABEA.

## Fase 3 — Validar render ES

Antes de traducir masivo, confirmar que la UI muestra:

```text
á é í ó ú ñ Ñ ¿ ¡ ü
```

Ruta rapida recomendada:

1. Instalar BepInEx 5 si el juego es Mono.
2. Instalar XUnity.AutoTranslator.
3. Forzar una linea traducida corta.
4. Arrancar juego y revisar glifos, overflow y TMP fonts.

Si faltan glifos, resolver fuente/TMP fallback antes de MT masiva.

## Fase 4 — Elegir estrategia

### Caso Naninovel + Addressables

Si el juego usa `Elringus.Naninovel.Runtime.dll` y bundles con nombres `naninovel_assets_naninovel_scripts_*.bundle`, priorizar extraccion automatica de `textMap.idToText` con [tools/unity/extract_naninovel_text.py](../tools/unity/extract_naninovel_text.py):

```powershell
python tools\unity\extract_naninovel_text.py `
  "<Juego>_Data\StreamingAssets\aa\StandaloneWindows64" `
  --out-jsonl "<Juego>\_tl_work\naninovel_scripts.jsonl" `
  --out-csv "<Juego>\_tl_work\naninovel_scripts.csv"
```

Esto no modifica bundles. Genera corpus traducible con `id`, `source` y `target`. La reinyeccion debe hacerse despues, usando backups y prueba con pocos bundles antes de procesar todo el juego.

Antes de reinyectar, validar el JSONL traducido con [tools/unity/lint_naninovel_jsonl.py](../tools/unity/lint_naninovel_jsonl.py):

```powershell
python tools\unity\lint_naninovel_jsonl.py `
  "<Juego>\_tl_work\naninovel_scripts.translated.jsonl" `
  --report "logs\unity\<juego>-jsonl-lint.txt"
```

Corregir siempre `errors>0`: targets vacios, sentinels `ZT###`, tags TMP perdidos (`<b>`, `<i>`, `<color>`), variables `[...]`, placeholders `%s/%d` y conteos de `\n`. Los `warnings` de unchanged suelen ser nombres, onomatopeyas o frases cortas, pero conviene revisarlos en QA textual.

Para reinyectar, usar [tools/unity/reinject_naninovel_text.py](../tools/unity/reinject_naninovel_text.py), que escribe bundles parcheados en una carpeta aparte:

```powershell
python tools\unity\reinject_naninovel_text.py `
  "<Juego>\_tl_work\naninovel_scripts.translated.jsonl" `
  --bundle-root "<Juego>_Data\StreamingAssets\aa\StandaloneWindows64" `
  --out-root "<Juego>\_tl_work\patched_bundles"
```

Nota de encoding: no generar JSONL con acentos desde comandos PowerShell ambiguos. Usar Python con `encoding="utf-8"` para escribir JSONL. En Dimension 69, una prueba creada con PowerShell produjo mojibake; la misma reinyeccion con JSONL UTF-8 escrito desde Python preservo `áéíóú ñ Ñ ¿¡ ü` correctamente.

Tras reinyectar, verificar por extraccion inversa antes de copiar al juego real:

```powershell
python tools\unity\extract_naninovel_text.py `
  "<Juego>\_tl_work\patched_bundles" `
  --out-jsonl "<Juego>\_tl_work\patched_extract.jsonl" `
  --out-csv "<Juego>\_tl_work\patched_extract.csv"
```

Comparar `patched_extract.jsonl` contra los `target` del JSONL traducido por `(bundle name, id, index)`. En Dimension 69: `strings=26667`, `errors=0`, `mismatch=0`. El contador `patched_strings` del reinjector puede ser menor que el total porque solo cuenta valores que cambiaron fisicamente; strings iguales al source y repeticiones de ids no suman como cambios.

Addressables puede bloquear bundles modificados aunque UnityPy los lea bien. Si al iniciar aparece pantalla negra y `Player.log` muestra `CRC Mismatch. Provided ..., calculated ...` seguido de `Resource '<script>' failed to load`, parchear el catalogo local antes de probar:

```powershell
python tools\unity\patch_addressables_bundle_crc.py `
  "<Juego>_Data\StreamingAssets\aa\catalog.bin" `
  "<Juego>\_tl_work\patched_bundles" `
  --update-hash
```

Hacer BK previo de `catalog.bin`, `catalog.hash` y `settings.json`. La herramienta pone `CRC=0` solo en las entradas de bundles modificados y actualiza el tamaño. `CRC=0` hace que `AssetBundle.LoadFromFile` no valide CRC, necesario cuando el bundle local fue reserializado.

### Caso XLSX-como-DAT (EPPlus runtime) — ナースコール警備員

Patrón: archivo `.dat` con cabecera `PK` (ZIP). El juego usa `EPPlus.dll` en `Managed/` para leer Excel en runtime. Texto en 5 sheets (`jp`, `en`, `sc`, `tc`, `ko`); IDs numéricos en col A, texto en col B como sharedString. Estrategia: reemplazar contenido del sheet `en` con ES.

**CRÍTICO: no usar `openpyxl` en modo escritura.** openpyxl reformatea el XLSX completo con estructura que EPPlus rechaza → juego se cuelga al arrancar. Manipular siempre a nivel ZIP/XML.

**Pipeline completo:**

1. Extracción:
```python
# Abrir con BytesIO para evitar error de extensión .dat
with open(DAT, "rb") as fh:
    buf = io.BytesIO(fh.read())
wb = load_workbook(buf, read_only=True, data_only=True)
ws = wb["en"]
# SIEMPRE especificar max_col=2; sin ello MemoryError (max_column=16384 declarado)
for row in ws.iter_rows(min_row=2, min_col=1, max_col=2, values_only=True):
    ...
```

2. Traducción con gpt-4.1-nano batch 25. Si aparecen `"target": ""` vacíos después del batch (bug conocido con ciertos bloques): usar `patch_empty.py` con batch de 10 y verificación por item.

3. Reconstrucción (ZIP/XML directo — ver `_tl_work/NurseCall/rebuild_zip.py`):
   - Parsear `xl/worksheets/sheet2.xml` con ElementTree para mapear `ID → ss_index` de col B.
   - Añadir nuevas entradas al final de `xl/sharedStrings.xml` (nunca modificar las existentes; otros sheets dependen de sus índices).
   - Actualizar referencias `<v>OLD</v>` → `<v>NEW</v>` en sheet2.xml con regex `<c r="B\d+"[^>]*t="s"[^>]*><v>(\d+)</v></c>`.
   - Reempacar ZIP preservando todos los demás archivos byte-por-byte.
   - IDs con source idéntico colapsan en el dict `old_to_new` (681 IDs → ~660 entradas únicas); es normal.

4. Label del selector de idioma (ID 23 en cada sheet):
   - Cambiar en `sharedStrings.xml` directamente los ss-indices de ID 23 en los 5 sheets a "Español".
   - **No es suficiente**: los labels del dropdown también están hardcodeados en los level files de Unity.

**Labels de idioma en level files — binary patch:**
Los strings "Fellow localize /English", "Fellow localize /簡体字", etc. están serializados en `level0–level10` y `resources.assets` (1 ocurrencia por archivo, 10 archivos total). NO están en `Assembly-CSharp.dll`.

Formato Unity serializado: `[4B length LE][N bytes UTF-8 string]` sin null terminator, alineado a 4B.

Patch seguro: mantener misma longitud, reemplazar bytes de string + padding con espacios trailing:
```python
OLD = "Fellow localize /English"   # 24 bytes
NEW = "Español" + " " * 16         # 8 + 16 = 24 bytes (espacios trailing; UI los recorta)
prefix = len(OLD.encode("utf-8")).to_bytes(4, "little")
data = data.replace(prefix + OLD.encode("utf-8"), prefix + NEW.encode("utf-8"))
```
Hacer backup de todos los level files antes del patch. Ver `_tl_work/NurseCall/patch_level_files.py`.

**Errores frecuentes en este caso:**
- `openpyxl.utils.exceptions.InvalidFileException`: extensión `.dat` → usar `open(rb)` + `BytesIO`.
- `ValueError: seek of closed file` en `read_only=True`: el filehandle se cierra antes de iterar → `BytesIO`.
- `MemoryError` al `iter_rows` sin `max_col` → añadir `max_col=2`.
- Juego se cuelga en arranque tras reescritura openpyxl → usar reconstrucción ZIP/XML.

### Caso A — Archivos de texto directos

Traducir el archivo manteniendo estructura. Usar parser real cuando sea JSON/CSV/XML; no regex global.

### Caso B — Unity Localization / StringTables

Extraer tablas con AssetRipper/UABEA, traducir valores y reimportar. Mantener keys intactas.

### Caso C — TextAssets en bundles/assets

Exportar TextAssets, traducir, reimportar con UABEA o herramienta compatible. Documentar bundle original y archivo tocado.

### Caso D — Texto runtime/hardcodeado

Primero probar XUnity.AutoTranslator. Si no cubre lo necesario y el build es Mono, inspeccionar `Assembly-CSharp.dll` con dnSpyEx.

## Fase 5 — Traduccion automatica

Provider recomendado:

1. DeepL si el volumen cabe en cuota.
2. OpenAI si el volumen es grande o requiere mejor contexto.
3. Gemini solo si el usuario lo pide explicitamente.

Antes de enviar a MT:

- Extraer strings a formato intermedio (`json/csv`) con `id`, `source`, `target`.
- Preservar placeholders: `{0}`, `%s`, `<color>`, `<sprite>`, `\n`, tags TMP.
- No traducir keys, ids, nombres de archivos ni rutas.

## Fase 6 — Reinyeccion y QA

1. Reinyectar manteniendo formato/binario original.
2. Arrancar juego.
3. Revisar menu principal, settings, dialogos, choices, inventario y textos largos.
4. Confirmar que no hay tofu, overflow grave ni placeholders rotos.
5. Guardar logs y decisiones nuevas.

## Reglas criticas

- No asumir que Unity Localization existe solo porque esta `UnityEngine.LocalizationModule.dll`.
- No tocar `.dll` antes de inspeccionar assets y archivos sueltos.
- No traducir placeholders ni tags TMP.
- No reempacar bundles sin backup.
- Si el juego usa IL2CPP, priorizar assets/XUnity sobre codigo.
