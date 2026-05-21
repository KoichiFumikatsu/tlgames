# Decisions

Decisiones técnicas y de producto tomadas durante el proyecto, con su razonamiento.

<!-- Ejemplos de qué guardar aquí:
- Fecha | Decisión | Por qué
- Tecnologías elegidas y el porqué del descarte de alternativas
- Trade-offs aceptados conscientemente
- Cambios de rumbo y qué los motivó
-->

## Historial

### 2026-04-30 — ナースコール警備員: pipeline completado — XLSX + binary patch level files

**Estado final:** traducción ES funcional. Selector muestra "Español". Contenido del juego en español al seleccionar ese idioma.

**Decisión de pipeline (ejecutada 2026-04-30):**
1. `SystemText.dat` (XLSX disfrazado) — operado a nivel ZIP/XML directo (NO via openpyxl write) para preservar estructura que EPPlus espera.
   - Extracción: `_tl_work/NurseCall/extract_en.py` → `en_corpus.jsonl` (681 strings, 21 984 chars).
   - Traducción: `translate_en_es.py` (gpt-4.1-nano, batch 25) + `patch_empty.py` para 100 targets vacíos que el batch de 25 no completaba.
   - Reconstrucción: `rebuild_zip.py` — agrega nuevas entradas a `sharedStrings.xml` y actualiza referencias en `sheet2.xml`; también sobreescribe ss-indices de ID 23 en los 5 sheets con "Español".
   - Costo real: ~$0.009 total (estimado en sesión).
2. Labels del dropdown de idioma (hardcodeados en level files Unity, NO en DLL ni XLSX):
   - String "Fellow localize /English" (24 bytes UTF-8) presente en `level0–level10` y `resources.assets` (1 ocurrencia por archivo = 10 archivos).
   - Patch binario: `patch_level_files.py` — reemplaza `\x18\x00\x00\x00Fellow localize /English` por `\x18\x00\x00\x00Español               ` (16 espacios trailing para mantener longitud 24B exacta; Unity parser usa length-prefix).
   - Backups en `backups/Unity/NurseCall-LevelFiles-20260429/`.

**Errores clave y soluciones:**
- `openpyxl` en modo escritura reformatea el XLSX completo → EPPlus no lo lee → juego se cuelga al arrancar. Solución: manipular ZIP/XML directamente.
- `openpyxl` en modo read-only + `read_only=True` cierra el filehandle antes de iterar. Solución: cargar en `BytesIO`.
- `openpyxl` falla con extensión `.dat`. Solución: abrir como `open(path,'rb')` → `BytesIO`.
- `max_column=16384` declarado en sheet → MemoryError al iterar sin `max_col`. Solución: siempre `iter_rows(max_col=2)`.
- gpt-4.1-nano en batch de 25 devuelve `"target": ""` para algunos bloques (≈100/681). Solución: `patch_empty.py` con batch de 10 y verificación por item antes de escribir.
- ID 23 en XLSX se cambió a "Español" en todos los sheets pero el dropdown seguía igual → los labels vienen de level files Unity (binario serializado), no del XLSX.
- Búsqueda en `Assembly-CSharp.dll` dio -1 (UTF-8 y UTF-16). Los strings de dropdown están serializados en los assets de escena Unity.

**Archivos de trabajo en `_tl_work/NurseCall/`:**
- `extract_en.py`, `translate_en_es.py`, `patch_empty.py`, `rebuild_zip.py`, `patch_level_files.py`
- `en_corpus.jsonl` (681 strings EN), `es_corpus.jsonl` (681 strings ES)
- `SystemText_es2.dat` (primer intento, openpyxl-write, no usar), `SystemText_es3.dat` (ZIP/XML, funciona)

**Backups:**
- `backups/Unity/NurseCall-SystemText-original-20260429/SystemText.dat`
- `backups/Unity/NurseCall-LevelFiles-20260429/` (level0–10 + resources.assets)

**Alternativas descartadas:** añadir sheet `es` + parchear DLL — introduce riesgo innecesario; reemplazar con openpyxl write — EPPlus no lee el resultado; parchear DLL para cambiar label de idioma — string no está en DLL.

### 2026-04-29 — ナースコール警備員: clasificado como Unity Mono + XLSX nativo, pipeline sin DLL patch
**Contexto:** `NurseCall_Data/SystemText.dat` es un XLSX real (cabecera PK, leído por `EPPlus.dll`). Contiene 5 hojas (`jp`, `en`, `sc`, `tc`, `ko`), 681 strings traducibles, ~21,984 chars EN. Escenas H pre-renderizadas como video (88 VideoPlayer), sin texto en bundle_0. Selector de idioma integrado en el juego (Settings → Game Settings → Language). IDs 22-26 son los nombres de idioma mostrados en el menú.
**Decisión:** reemplazar contenido del sheet `en` con traducción ES; cambiar ID 23 de `"Fellow localize / English"` a `"Español"`. Conservar el nombre del sheet como `en` para que el mapeo DLL siga funcionando sin parchear Assembly-CSharp.dll.
**Razón:** sin parchar DLL se elimina el mayor riesgo técnico. El sheet `en` ya está mapeado por el engine; solo cambiamos su contenido. Costo ~$0.003 con gpt-4.1-nano, viabilidad ALTA.
**Alternativas descartadas:** añadir sheet `es` nuevo + parchear DLL — más limpio semánticamente pero introduce riesgo innecesario; reemplazar sheet `jp` — el contenido JP es la fuente y no se toca.

### 2026-04-28 — Luna in the Tavern: clasificado como Electron, pipeline JSON puro
**Contexto:** carpeta `proyects Game TL/Luna in the Tavern/` con `Luna-in-the-Tavern.exe`, `chrome_100_percent.pak`, `libEGL.dll`, `resources/app/` con `package.json` (`electron ^9.2.0`), `index.html`, `main.js`, `renderer.js`. Texto principal en `resources/app/static/json/v4_2_allfree.json` (~15MB, 2968 escenas, 26,532 entradas de diálogo, 22,098 strings únicos, ~847k chars únicos). DeepL agotado (5 chars). OpenAI key presente, budget $1.00, costo estimado ~$0.12.
**Decisión:** clasificarlo como Electron (nuevo engine sin playbook previo). Pipeline: backup → extraer strings únicos del campo `"text"` a JSONL → traducir con OpenAI gpt-4.1-nano → reinyectar en JSON → test ejecutando el .exe. Corpus secundario pequeño (inventory_config.json, gallery_locked_v3.json, UI en wrka.html) se traduce en la misma pasada o manualmente.
**Razón:** es el pipeline más simple de todos los proyectos — JSON plano sin binarios, sin tooling especial. No se requieren UABEA, unrpyc, BepInEx ni nada equivalente.
**Alternativas descartadas:** clasificar como RPG Maker MV (no hay `www/`, `js/rmmz_*.js` ni estructura MV/MZ); tratar como Unity (no hay `*_Data/`, `Managed/`, ni assets binarios).

<!-- Formato sugerido:
### YYYY-MM-DD — Título breve
**Contexto:** …
**Decisión:** …
**Razón:** …
**Alternativas descartadas:** …
-->

### 2026-04-28 — Hero in an All-Forgiving Fantasy World RPG: clasificado como RPG Maker MZ
**Contexto:** carpeta `proyects Game TL/Hero in an All-Forgiving Fantasy World RPG/` con `Game.exe`, `package.json`, `js/rmmz_core.js`, `js/rmmz_*.js`, `data/*.json`, `js/plugins.js`; no usa `www/` como carpeta contenedora. Conteo inicial: 69 mapas, 83 JSON, 58 plugins, ~44.440 apariciones traducibles, ~897.172 caracteres de aparicion, ~17.067 strings unicos, ~481.112 caracteres unicos. `CommonEvents.json` concentra ~783k caracteres por aparicion. DeepL disponible 5/500.000; OpenAI acumulado ~$0.8266.
**Decision:** tratarlo como RPG Maker MZ JSON-root, crear pipeline especifico de extraccion/reinyeccion JSONL con deduplicacion por source, traducir con OpenAI `gpt-4.1-nano`, y parchear `data/*.json`/`js/plugins.js` solo despues de backup completo.
**Razon:** DeepL no tiene cuota; el volumen cabe en OpenAI con presupuesto bajo si se deduplica. Editar JSON estructurado es reversible y menos riesgoso que regex sobre archivos completos. Los plugins activos guardan textos visibles en parametros JSON escapados.
**Alternativas descartadas:** esperar DeepL — bloquea el avance; traducir ocurrencias sin deduplicar — duplica coste y tiempo; tocar imagenes/encriptados como primera fase — no hay evidencia inicial de ser el texto principal.

### 2026-04-28 — Pokemon Naughty Version: activar idioma Spanish en Essentials
**Contexto:** `messages_game.dat` traducido no cambiaba el intro/profesora/nombre/rival porque los eventos de mapa siguen guardando texto EN en `Map*.rxdata` y Essentials solo consulta `messages_<idioma>_game.dat` si `Settings::LANGUAGES` no esta vacio. Un intento de reescribir mapas con Python `rubymarshal` tradujo 1473 strings pero corrompio 19 mapas por referencias Marshal; se restauraron desde `_tl_work/Data_original_before_rxdata_text_es6`.
**Decision:** usar el mecanismo nativo de idioma: copiar `Data/messages_game.dat` traducido a `Data/messages_spanish_game.dat`, copiar `messages_core.dat` a `messages_spanish_core.dat`, y parchear `Data/Scripts.rxdata` (`Settings`) con dos entradas `[["English", "english"], ["Espanol", "spanish"]]`. Mantener `Data/PluginScripts.rxdata` intacto; crear tambien `messages_english_*` para evitar indices invalidos si un save tenia `$PokemonSystem.language = 1`.
**Razon:** evita tocar `Map*.rxdata` con un serializador no 100% compatible y permite que `MessageTypes` traduzca los textos de eventos en runtime.
**Alternativas descartadas:** seguir reinyectando `Map*.rxdata` con Python — riesgo de corrupcion; plugin `Plugins/Spanish Language/` + borrar `PluginScripts.rxdata` — causo cierres/ENOENT en este build; sobrescribir solo `messages_game.dat` — no activa traduccion runtime.

### 2026-04-28 — Pokemon Naughty Version: UI hardcodeada y fixes Unicode seguros
**Contexto:** la pantalla de nombre seguia en ingles (`Your name?`, ayuda de teclado) aunque el idioma Spanish cargaba, porque esas cadenas estan hardcodeadas en `Data/Scripts.rxdata` (`Interpreter_Commands`, `UI_TextEntry`, `Utilities`). Algunas correcciones manuales anteriores introdujeron `?` en lugar de tildes por enviar Unicode directo por PowerShell stdin; las fuentes `Power Green*` si cubren `áéíóúñ¿¡ü`.
**Decision:** parchear las cadenas UI en los scripts comprimidos de `Scripts.rxdata` y reescribir los fixes de `messages_game_corpus.es6.jsonl` usando escapes `\uXXXX` con decodificador limitado a Unicode, preservando codigos RPG Maker (`\r`, `\b`, `\c[n]`, `\G`). Aplicar los fixes a `messages_spanish_game.dat` y `messages_game.dat`.
**Razon:** resuelve el ingles visible sin tocar mapas y elimina mojibake real en las entradas corregidas manualmente.
**Alternativas descartadas:** cambiar fuentes — no era la causa, todas las fuentes del juego tienen cmap ES; escribir mapas `Map*.rxdata` — riesgo ya comprobado; usar `unicode_escape` global — convierte `\r` en carriage return y rompe codigos del juego.

### 2026-05-19 — QA semántico Ren'Py via Ollama local

**Decisión:** crear pipeline de QA semántico para archivos `.rpy` con `tools/qa_renpy.py` + `tools/qa_server.py`, usando Ollama (`llama3.2:3b`) en CPU local. Servicio systemd `tlgames-qa` en puerto 8765. Workflow n8n "TL Games QA" (ID `RLVfxeEssZIeL107`) con webhook `POST http://localhost:5678/webhook/tl-qa`.

**Cobertura del QA semántico:**
- Concordancia de género/número
- Calcos del inglés antinaturales
- Mezcla de tuteo/ustedeo
- Nombres de personaje traducidos cuando no deberían
- Frases literalmente traducidas incomprensibles en español
- Pares de 1-2 palabras se saltean (stats, atributos — sin contexto suficiente)

**Comandos:**
```bash
# Archivo individual
python3 tools/qa_renpy.py "proyects Game TL/<juego>/game/tl/spanish/script.rpy" --report logs/qa.md

# Directorio completo
python3 tools/qa_renpy.py "proyects Game TL/<juego>/game/tl/spanish/"

# Via HTTP (para n8n o scripts externos)
curl -X POST http://localhost:8765/qa -H "Content-Type: application/json" \
  -d '{"file": "/ruta/absoluta/al/archivo.rpy"}'
```

**Razón:** el lint estructural existente (`lint_naninovel_jsonl.py`) solo cubre JSONL Unity. Los `.rpy` no tenían QA automatizado. Ollama local evita costos de API y mantiene privacidad del contenido adulto.

**Limitaciones conocidas:**
- `llama3.2:3b` es conservador con strings cortos — tiende a dar OK en pares de 1-2 palabras (filtrados por diseño).
- CPU only (i7-8665U) — un lote de 40 pares tarda ~30-60s. Aceptable para volúmenes de sesión (~50-100 pares/día).
- Cubre solo formato `old "..." / new "..."` de string blocks. Dialogue blocks (formato `"speaker" "text"`) pendientes.

**Alternativas descartadas:** Claude API para QA (costo + privacidad); lint regex manual (no detecta calcos ni género); OpenAI para QA (costo, y Ollama es suficiente para este caso).

### 2026-05-21 — The Demon Lord's Lover: pipeline nativo ZIP completado al 100%

**Estado final:** 9.282 entradas traducidas (2191 strings + 1079 grammar + 6012 scenes), 0 vacíos. ZIP final: `es-kelsie.zip` (296 KB). Importar via Settings → Translations → Import translation. Costo total: ~$0.002 (solo el recovery pass; las 9k iniciales venían de una sesión anterior con cuenta agotada).

**Decisión de pipeline (ejecutada 2026-05-20–2026-05-21):**
1. Identificación del formato nativo: strings binarios en `Game.dll` (`TranslationImport`, `ReadManifest`, `ValidateManifest`) → README oficial en `gitgud.io/ayumu98/the-demon-lords-lover-translations`. ZIP sin wrapper folder: `manifest.json` + `strings.json` + `grammar.json` + `scenes/**/*.scene`.
2. Extracción (`01_extract.py`): walk JSON anidado por dot-path para strings; grammar con skip de campos booleanos (`isinstance(text, str)`); scenes con índice `(rel_path, lineno)`, preservando speaker/narración/indentación.
3. Traducción (`02_translate.py`): gpt-4.1-nano, batch 40, SYSTEM_COMMON para strings+scenes, SYSTEM_GRAMMAR para grammar. Strip markdown fences antes de parsear JSON.
4. Recovery (`05_recover_scenes.py`): batch 1 para 160 entradas que quedaron vacías por cuenta agotada. 160/160 recuperadas.
5. Correcciones manuales en grammar (MT produjo pronombres incorrectos): `masculine.reflexive` él→ella, `feminine.object` su→la, nonbinary subject/object/reflexive.
6. Rebuild (`03_rebuild.py`): fallback source cuando target vacío; `rebuild_scenes` reconstruye líneas respetando indentación y prefijo `speaker:`.
7. ZIP (`04_build_zip.py`): arcname relativo a `es-kelsie/` sin wrapper folder.

**Errores clave y soluciones:**
- `TypeError: object of type 'bool' has no len()` en grammar: campos booleanos como `plural: true` — fix: `if not isinstance(text, str): continue`.
- JSON parse errors de batches: OpenAI a veces envuelve en markdown fences — fix: regex strip `^```(?:json)?\s*` / `\s*```$`.
- Mismatch 40→41 items en batch 58: 3 reintentos fallidos, 40 entradas quedaron vacías → cubiertos por recovery pass.
- OpenAI 429 insufficient_quota durante recovery inicial → sesión posterior con saldo recargado.

**Archivos de trabajo en `_tl_work/TheDemonLordsLover/`:**
- `01_extract.py`, `02_translate.py`, `03_rebuild.py`, `04_build_zip.py`, `05_recover_scenes.py`
- `corpus_*.jsonl`, `translated_*.jsonl`, `cache_*.json`
- `es-kelsie/` (371 archivos), `es-kelsie.zip`

**Alternativas descartadas:** parchear binarios directamente — el sistema nativo es más limpio y reversible; usar Gemini — OpenAI con nueva recarga fue suficiente.

### 2026-04-28 — Hypno Academy: XUnity ES antes de reinyeccion binaria
**Contexto:** Hypno Academy usa Unity Mono y BepInEx/XUnity. El corpus inicial salio de regex binaria sobre assets, mezclando texto real con falsos positivos binarios. DeepL quedo agotado (499995/500000), OpenAI tradujo 3740/3982 pero tuvo timeouts/respuestas irregulares, y Gemini se colgo.
**Decision:** probar primero una via no invasiva con XUnity: `Language=es`, `FromLanguage=en`, `MaxCharactersPerTranslation=1000`, exportando `BepInEx/Translation/es/Text/_AutoGeneratedTranslations.txt` desde `static_strings_corpus.final.cleaned.jsonl` con filtro conservador. No reinyectar assets hasta depurar el corpus.
**Razon:** reduce riesgo de corromper assets y permite validar si los textos runtime y los glifos ES se muestran bien. El filtro excluye targets vacios, binarios, unchanged y entradas que rompen formato `source=target`.
**Alternativas descartadas:** reinyeccion directa del corpus 93.9% — riesgo alto por falsos positivos binarios; reintentar DeepL — sin cuota; Gemini inmediato — runner inestable.

### 2026-04-28 — Pokemon Naughty Version: clasificado como RPG Maker XP / Pokemon Essentials
**Contexto:** El usuario agrego `Pokemon Naughty Version` y creo segmentos `RPGMaker/` y `GameMaker/`. Inspeccion: `Game.ini` con `Library=RGSS104E.dll`, `Scripts=Data\Scripts.rxdata`, `Title=Pokemon Naughty Version`; estructura `Data/`, `PBS/`, `Plugins/*.rb`, `mkxp.json` con `windowTitle` Pokemon Essentials v21.1.
**Decision:** clasificarlo como RPG Maker XP/RGSS con Pokemon Essentials/mkxp-z y moverlo a `proyects Game TL/RPGMaker/Pokemon Naughty Version/`. Crear backup en `backups/RPGMaker/PokemonNaughtyVersion-original/` y carpetas `logs/rpgmaker/`, `logs/gamemaker/`, `backups/GameMaker/`.
**Razon:** no hay `data.win`, `*.yyp` ni estructura GameMaker. Los indicadores RGSS/PBS/Plugins Ruby son concluyentes para RPG Maker XP/Pokemon Essentials.
**Alternativas descartadas:** GameMaker — no coincide la estructura; Unity/Ren'Py — no hay `*_Data`, `Managed`, `.rpy` ni flujo equivalente.

### 2026-04-28 — Pokemon Naughty Version: PBS primero, aplicado con backup local
**Contexto:** Pokemon Essentials expone muchos nombres/descripciones/dialogos estructurados en `PBS/*.txt`; `Data/*.rxdata` y `Plugins/*.rb` requieren tooling separado. DeepL no tenia cuota suficiente y OpenAI `gpt-4.1-nano` completo el corpus PBS.
**Decision:** extraer 10.294 campos PBS, traducirlos con OpenAI, lintar placeholders/sentinels, aplicar primero a `_tl_work/PBS_translated` y luego copiar al `PBS/` real tras crear snapshot en `_tl_work/PBS_original_before_spanish_apply`.
**Razon:** PBS es texto plano y reversible. La validacion final dio 10.294/10.294 traducidos, 0 vacios, 0 sentinels, 0 issues de lint, 21 archivos modificados y 10.294 lineas aplicadas. Re-extraccion del PBS aplicado queda parseable; las 6 diferencias son frases tipo risa en mayusculas que el extractor filtra por heuristica.
**Alternativas descartadas:** tocar `Data/*.rxdata` sin parser RGSS/Marshal — riesgo alto; sobrescribir PBS sin snapshot local — menos reversible; esperar a traducir plugins antes de PBS — retrasa una fase segura y visible.
**Pendiente:** recompilar/actualizar datos de Pokemon Essentials desde PBS para runtime si el juego no lee PBS directamente, y hacer pase canon sobre nombres oficiales que quedaron en ingles o literales (`Repel`, habilidades, algunos objetos/movimientos).

### 2026-04-28 — XUnity AutoTranslator: translators en ruta del core activo
**Contexto:** Hypno Academy tenia `XUnity.AutoTranslator` duplicado en `BepInEx/plugins/` y `BepInEx/plugins/XUnity.AutoTranslator/`. BepInEx cargo el core de raiz y omitio el duplicado; por eso no encontraba endpoints aunque los DLL existian en la subcarpeta nested. Log: `Could not find the configured endpoint 'GoogleTranslateV2'` y luego `'GoogleTranslate'`.
**Decision:** copiar los DLL de `BepInEx/plugins/XUnity.AutoTranslator/Translators/*.dll` a `BepInEx/plugins/Translators/`. Mantener `Endpoint=GoogleTranslate`.
**Razon:** el core activo busca translators relativos a su propia ubicacion. Tras copiar, desaparecio el error de endpoint y XUnity cargo `--- Loading Global Translations ---` / `Loaded translation text files`.
**Alternativas descartadas:** cambiar nombres de endpoint a ciegas — no resuelve si los DLL no estan en la ruta escaneada; depender solo de traducciones estaticas con endpoint invalido — carga parcial pero limita fallback runtime.

### 2026-04-27 — Segmentacion por engine dentro del mismo workspace
**Contexto:** El flujo Ren'Py ya tiene memoria, scripts y decisiones muy especificas. Se va a iniciar un nuevo proyecto Unity y existe riesgo de mezclar requisitos de Ren'Py con Unity.
**Decision:** mantener el mismo workspace `c:\xampp\htdocs\tl`, pero segmentar por engine: `proyects Game TL/Unity/`, `logs/unity/`, `backups/Unity/`, `memory/unity-translation-brief.md` y `memory/playbook-unity-translation.md`. No mover juegos Ren'Py existentes para no romper rutas históricas.
**Razon:** reutiliza herramientas, `.env`, logs y memoria comun sin contaminar el flujo tecnico de cada engine.
**Alternativas descartadas:** workspace separado por engine — duplica configuracion y herramientas; mezclar todos los juegos planos en `proyects Game TL/` — aumenta confusion y riesgo de aplicar pasos Ren'Py a Unity.

### 2026-04-27 — Dimension 69: Naninovel/Addressables via UnityPy
**Contexto:** Dimension 69 fue movido a `proyects Game TL/Unity/Dimension 69/`. Inspeccion inicial: Unity Mono (`Assembly-CSharp.dll` presente, sin `il2cpp_data`), Addressables en `StreamingAssets/aa`, `Elringus.Naninovel.Runtime.dll`, `Naninovel.Common.dll`, `Unity.TextMeshPro.dll` y scripts como bundles `naninovel_assets_naninovel_scripts_*.bundle`.
**Decision:** instalar `UnityPy` y crear `tools/unity/extract_naninovel_text.py` para extraer `textMap.idToText` de los bundles Naninovel a JSONL/CSV antes de cualquier modificacion. Primer corpus: 230 bundles/scripts, 26.667 strings, 1.485.147 caracteres fuente, 0 errores. Prueba de reinyeccion sobre copia en `_tl_work/reinject_test/`: `obj.save_typetree(tree)` + `env.file.save()` conserva el cambio y recarga OK.
**Razon:** los textos no estan como archivos planos ni `TextAsset`; estan serializados en `MonoBehaviour` dentro de bundles Addressables. UnityPy lee y puede reguardar el typetree de forma automatizable, evitando trabajo manual con GUI.
**Alternativas descartadas:** dnSpy como primer paso — el texto principal no esta hardcodeado; AssetRipper/UABEA manual como primer paso — demasiado lento para 230 bundles; XUnity como estrategia principal — util para QA/glifos, pero no da un corpus limpio para traduccion masiva.

### 2026-04-27 — Dimension 69: MT OpenAI sobre JSONL Naninovel
**Contexto:** DeepL no cubre el volumen de Dimension 69 (~1.49M caracteres fuente). Se creo `tools/unity/translate_jsonl_openai.py` para traducir `naninovel_scripts.jsonl` a `naninovel_scripts.translated.jsonl` sin tocar bundles.
**Decision:** usar OpenAI `gpt-4.1-nano` con presupuesto `OPENAI_BUDGET_USD=1.00`. Batch 100 y 50 se probaron pero quedaron con latencia alta/salida silenciosa en ciertos tramos; batch 10 con `--flush-every 1` es el modo estable. El archivo de salida se guarda por lote y la cache OpenAI evita recobrar strings ya traducidos al reanudar.
**Razon:** batch pequeno reduce fallos por respuestas JSON irregulares y hace reanudacion granular. El costo por batch es bajo (~0.00008-0.00013 USD en el tramo observado), por lo que el overhead extra es aceptable frente a estabilidad.
**Alternativas descartadas:** DeepL completo — cuota insuficiente; Gemini — mas requests y calidad inferior; batch 100/50 — menos requests pero peor latencia/observabilidad en este corpus.

### 2026-04-27 — Dimension 69: parche Naninovel aplicado con BK
**Contexto:** `naninovel_scripts.translated.jsonl` llego a 26.667/26.667 strings. Lint tecnico `tools/unity/lint_naninovel_jsonl.py` quedo en `errors=0`; la re-extraccion de `_tl_work/patched_bundles` comparada contra targets finales dio `missing=0`, `mismatch=0`.
**Decision:** reemplazar los 230 bundles Naninovel reales en `Dimension69_Data/StreamingAssets/aa/StandaloneWindows64` por los bundles traducidos de `_tl_work/patched_bundles`, manteniendo BK previo en `backups/Unity/Dimension69-BK-before-spanish-patch-20260427-141312/StandaloneWindows64`.
**Razon:** la verificacion inversa desde el juego ya parcheado dio 230 scripts, 26.667 strings, `errors=0` de extractor y comparacion `expected=26667 actual=26667 missing=0 mismatch=0`, asi que el reemplazo es reversible y validado.
**Alternativas descartadas:** copiar sin BK — no reversible; modificar bundles en sitio antes de lint/re-extraccion — riesgo alto de parche opaco.

### 2026-04-27 — Dimension 69: CRC de Addressables desactivado para bundles traducidos
**Contexto:** tras aplicar los bundles traducidos, el juego quedaba en pantalla negra al pulsar Start. `Player.log` mostro `CRC Mismatch` para `naninovel_assets_naninovel_scripts_questevents_mainquests_intro_*.bundle`; Addressables rechazaba el bundle reserializado aunque UnityPy lo extraia correctamente.
**Decision:** crear `tools/unity/patch_addressables_bundle_crc.py` y aplicarlo a `catalog.bin` para poner `CRC=0` en las 230 entradas Naninovel modificadas, actualizando tambien el tamaño de bundle y `catalog.hash`. BK previo del catalogo en `backups/Unity/Dimension69-BK-before-catalog-crc-patch-20260427-141952`.
**Razon:** `CRC=0` evita que `AssetBundle.LoadFromFile` valide el CRC viejo del catalogo, que ya no coincide tras la reserializacion de UnityPy. Es un cambio local, acotado a los bundles traducidos y reversible con el BK.
**Alternativas descartadas:** restaurar bundles y abandonar reinyeccion — perderia la traduccion; recalcular CRC Unity exacto fuera de Unity Editor — no trivial desde Python; parchear todos los CRC del catalogo — innecesariamente amplio.

### 2026-04-26 — Scripts de fix post-MT en pipeline obligatorio (Tropicali QA)
**Contexto:** Primer arranque ingame de Tropicali tras MT con OpenAI gpt-4.1-nano detectó dos clases de bugs sistemáticos que el lint marcaba pero no bloqueaban compile:
1. Sentinels `ZT###`/`ZG###` huérfanos: el modelo a veces pega el sentinel al token siguiente perdiendo la `Z` final (ej. `ZT002Si estás...` en vez de `ZT002Z Si estás...`). `detokenize()` no los reconoce y quedan literales en el target → crash con `'/b' closes a text tag that isn't open`. 33 casos en story.rpy de Tropicali.
2. Multi-line strings con `\n` real (LF físico) en vez de `\n` literal cuando el source tiene `\n` literal y el modelo responde con salto físico. Compile falla con `Could not parse string`. 2 casos en common.rpy.
**Decisión:** crear `tools/tl/fix_zt_sentinels.py` (re-tokeniza el `# "source"` adyacente y restaura el token original tolerando ausencia de Z final) y consolidar el ya existente `tools/tl/_fix_multiline_strings.py` como **paso obligatorio del pipeline** después de `postprocess.py` y antes de `find_untranslated.py`. Playbook actualizado.
**Razón:** son fallos sistemáticos del MT no detectables sin parsear con conocimiento del tokenizador. Pre-compile fallaba con error críptico; ingame fallaba con escena del menú inicial.
**Alternativas descartadas:** prompt más estricto al modelo — no garantiza 100%; lint-based fail — bloquea pipeline pero no auto-repara.

### 2026-04-26 — OpenAI como provider de fallback cuando DeepL no alcanza
**Contexto:** Tropicali (Ren'Py 8.1.1, ~1.28 MB de fuentes .rpy) excede los chars disponibles en DeepL Free (~55k restantes de 500k). Maeves Academy ya validó el flujo OpenAI con gpt-4.1-nano (budget tracker, batch 25, calidad alta para diálogo, tono y género).
**Decisión:** cuando DeepL no alcanza, **OpenAI es el provider por defecto** (no Gemini). Gemini queda solo como opción explícita si el usuario la pide. Pipeline: `_run_openai_all.py` → `_run_openai_small_batch.py` → `_run_openai_tiny_batch.py` (passes con batches decrecientes para recuperar fallos). Budget control vía `OPENAI_BUDGET_USD` (default 0.50).
**Razón:** OpenAI gpt-4.1-nano maneja mejor matices, tono, género y contexto narrativo que MT puro. Costo controlado: ~$0.10/1M input + $0.40/1M output → un VN completo cabe en $0.50–1.00. Resultado en Maeves fue superior a DeepL en consistencia de personaje.
**Alternativas descartadas:** Gemini lite gratis — calidad inferior en VN largas y rate limits diarios molestos; MyMemory — calidad insuficiente.

### 2026-04-24 — Python 3.12 vía winget, scope user
**Contexto:** Python no estaba instalado; el alias del Microsoft Store interceptaba `python`.
**Decisión:** instalar Python 3.12.10 vía `winget` con `--scope user`.
**Razón:** sin admin, sin tocar el Python del sistema si luego lo hubiera; 3.12 es estable y ampliamente soportado por las tools del pipeline (unrpa, unrpyc). El alias del Store hay que desactivarlo manualmente en Settings → App execution aliases.
**Alternativas descartadas:** instalador `.exe` de python.org (más pasos manuales); Python 3.13 (menor compatibilidad con wheels de ciertas tools).

### 2026-04-24 — Ren'Py SDK 8.2.3, fuera del proyecto
**Contexto:** el juego FromTheSin declara versión 8.2.0 en `script_version.txt`.
**Decisión:** instalar Ren'Py SDK 8.2.3 (último de la rama 8.2.x) en `C:\renpy-8.2\renpy-8.2.3-sdk\`.
**Razón:** mantener la misma rama mayor que el juego para evitar diferencias en `Generate Translations`. Ubicarlo fuera del proyecto porque pesa ~350 MB y se reutilizará para futuros juegos.
**Alternativas descartadas:** Ren'Py 8.3.x (rama más nueva, riesgo mínimo pero innecesario); dentro del proyecto (ensuciaría el repo).

### 2026-04-24 — Tools portables centralizadas en `tools/`
**Contexto:** UABEA, AssetRipper, dnSpyEx, BepInEx, XUnity.AutoTranslator y unrpyc son zips portables de GitHub releases.
**Decisión:** centralizar todas en `tools/` dentro del proyecto, una subcarpeta por tool.
**Razón:** portabilidad, no requieren admin, mantiene el setup autocontenido y reproducible.
**Versiones fijadas:** unrpyc 2.0.4, UABEA v8, AssetRipper 1.3.12, dnSpyEx 6.5.1, BepInEx 5.4.23.5 (win_x64), XUnity.AutoTranslator 5.6.1 (variante BepInEx, no IL2CPP).
**Alternativas descartadas:** AssetStudio original (Perfare) — repo archivado desde 2023; BepInEx 6 — aún en preview, 5.x es LTS de facto; variante IL2CPP de XUAT — Dimension 69 es Mono.

### 2026-04-24 — Priorizar XUnity.AutoTranslator antes que reempaquetar assets (Unity)
**Contexto:** Dimension 69 es Mono con Addressables. El flujo AssetRipper → editar → UABEA reimportar es frágil con `data.unity3d` monolítico y bundles addressables.
**Decisión:** antes de tocar assets, probar BepInEx 5 + XUnity.AutoTranslator como MVP para validar que el motor de texto renderiza caracteres españoles.
**Razón:** overlay no invasivo, reversible, tarda minutos en probarse; si el atlas de TMP no soporta `á é í ó ú ñ ¿ ¡`, se detecta ahí sin haber invertido esfuerzo en reimportar nada.
**Alternativas descartadas:** ir directo a editar StringTables — se pierde tiempo si al final los glifos no están en la fuente.

### 2026-04-24 — Glosario solo admite términos invariables en contexto
**Contexto:** el glosario inicial incluía entradas como `THE→LA`, `HIGH→ALTO`, `COMING→VIENE`. Estas rompen concordancia de género/número en español porque dependen del sustantivo que acompañan (`the water`→`la agua` ✗; `moons are coming`→singular ✗).
**Decisión:** restringir el glosario a nombres propios, sustantivos de género fijo, imperativos, interjecciones, siglas y compuestos completos. Términos dependientes de contexto se delegan al MT con la oración entera. Implementado vía lista `CANON_TERMS_CLEAR` en `tools/tl/apply_canon.py` que vacía esos targets.
**Razón:** el glosario sustituye pre-MT (token → término), por lo que no tiene visibilidad del sustantivo siguiente. El MT con contexto resuelve mejor género/número.
**Alternativas descartadas:** glosario por contexto (regex con sustantivo siguiente) — frágil y costoso para el beneficio; reglas post-MT por concordancia — duplicaría lógica del MT.

### 2026-04-24 — Resiliencia del pipeline de traducción
**Contexto:** runs largos contra MyMemory pueden cortarse por red, rate-limit o agotamiento de cuota (~10k palabras/día con email registrado).
**Decisión:** `translate.py` ahora cachea por bloque (no cada 25), reintenta con backoff [2s, 5s, 15s] y aborta limpio tras 8 errores consecutivos guardando estado en disco.
**Razón:** evitar pérdida de progreso y malgaste de cuota en cascadas de errores. El run del 2026-04-24 traduzco 485 bloques antes de agotar cuota; con la nueva resiliencia el archivo quedó válido y el cache reutilizable.
**Alternativas descartadas:** circuit breaker más complejo (innecesario para uso personal).

### 2026-04-24 — Sanitizer de saltos de línea post-MT
**Contexto:** MyMemory a veces inserta `\r\n` reales dentro de strings, lo que rompe la sintaxis Ren'Py (strings ocupan una sola línea física).
**Decisión:** `translate_text` convierte cualquier salto de línea real en `\\n` literal antes de devolver.
**Razón:** caso `Loading will lose unsaved progress.\nAre you sure...` rompió `compile`. Sin esto, cada string con `\n` interno requería fix manual.
**Alternativas descartadas:** parser que detecte y arregle post-write — más frágil, hace doble trabajo.

### 2026-04-24 — Bug del decompilado: `screen say(who, what, emote)`
**Contexto:** unrpyc perdió el valor por defecto del parámetro `emote` en `screen say` de FromTheSin. Crashea al primer diálogo.
**Decisión:** parche manual en `proyects Game TL/FromTheSin/game/screens.rpy:96` cambiando a `screen say(who, what, emote=""):`.
**Razón:** bug preexistente, no relacionado con la traducción. Sin este fix el juego no arranca ni en inglés.

### 2026-04-24 — Selector de idioma habilitado en Preferences
**Contexto:** el bloque `vbox` con `Language(...)` actions en `screens.rpy:1531` estaba comentado, no permitía elegir Spanish.
**Decisión:** añadir bloque activo con English/Spanish/Italian/Russian justo debajo del comentado.
**Razón:** sin esto el usuario no podía cambiar al idioma traducido aunque `tl/spanish/` existiera.

### 2026-04-24 — Migración a DeepL Free como provider principal
**Contexto:** MyMemory traducía mal frases comunes ("don't worry" → "Don no te preocupes", "completely" duplicado, etc.). Cuota agotada a los 564/2916 diálogos. API key de DeepL Free disponible (1M chars/mes según dashboard; el endpoint `/v2/usage` reporta 500k pero es discrepancia conocida — confiar en dashboard). Key con suffix `:fx` indica free tier.
**Decisión:** añadir adapter DeepL en `translate.py` con flag `--provider deepl|mymemory`, default `deepl`. Cache separado en `.cache/deepl.json`. API key vía env `DEEPL_API_KEY` o `--deepl-key`. Endpoint `https://api-free.deepl.com/v2/translate`.
**Razón:** calidad notablemente superior, cuota suficiente para un juego completo (FromTheSin ~250k chars), formato XML `tag_handling` opcional. MyMemory sigue disponible como fallback.
**Alternativas descartadas:** Google Translate (sin tier gratis serio); LibreTranslate self-hosted (overhead innecesario para uso personal).

### 2026-04-24 — Re-traducción completa con DeepL desde .bak
**Contexto:** ~564 diálogos ya traducidos con MyMemory mostraban calidad inconsistente.
**Decisión:** restaurar todos los `.bak` en `tl/spanish/` y re-traducir todo desde cero con DeepL en una sola pasada (~3000 strings totales).
**Razón:** consistencia estilística > esfuerzo perdido. El re-run completo con DeepL costó ~5 min y dejó traducciones uniformes.
**Alternativas descartadas:** mantener MyMemory en lo ya hecho y completar pendiente con DeepL — mezcla dos estilos.

### 2026-04-24 — Post-procesador determinista para errores sistemáticos
**Contexto:** DeepL traduce `Don't` (contracción) como honorífico español: `(Don't connect.) → (Don no conectar.)`. 27 ocurrencias.
**Decisión:** crear `tools/tl/postprocess.py` con regex contextuales que detectan inicio fuerte de oración (`. ! ? ¡ ¿ " ( [ |`) vs. medio de oración (coma, espacio) para decidir mayúscula/minúscula al reemplazar.
**Razón:** errores sistemáticos del MT son corregibles con reglas. Idempotente, reutilizable por archivo o `--all`. Solo toca líneas de traducción (ignora `#` comentarios y `old "..."`).
**Alternativas descartadas:** `--no-splitting-tags` u otros flags DeepL (no atacan la causa); regex global sin contexto (rompería capitalización legítima).

### 2026-04-24 — Detector de inglés residual con marcadores TODO[en]
**Contexto:** DeepL deja palabras sin traducir cuando son nombres propios o cuando el modelo no las reconoce ("something", "size", "here", "inhale", etc.). En 2916 strings el usuario no puede revisarlas todas.
**Decisión:** crear `tools/tl/find_untranslated.py` que parsea cada par (EN, ES) y marca palabras del target que aparecen tal cual en el source y no están en allowlist (cognados, onomatopeyas, nombres propios, términos Ren'Py). Modo `--add-markers` inserta `# TODO[en]: ...` **después** de la línea (insertar antes rompe el parser de Ren'Py por la dependencia comment+target).
**Razón:** automatiza la detección, deja la decisión de traducción al humano vía búsqueda en editor. Idempotente: re-ejecutar limpia los marcadores antiguos. 747 → 348 hits tras ampliar allowlist con nombres del juego.
**Alternativas descartadas:** lint en CI (no pertinente proyecto personal); diff visual side-by-side (más caro, sin mejor outcome).

### 2026-04-24 — Sanitizer en parser de marcadores: insertar después, no antes
**Contexto:** primera versión de `--add-markers` insertaba el comentario TODO antes de la línea target. Esto rompió `parse_dialogue_file` porque toma el primer `#` como comentario fuente y la siguiente línea no-comentario como target — el TODO se interpretaba como fuente.
**Decisión:** insertar el marcador justo después de la línea target.
**Razón:** Ren'Py tolera comentarios dentro del bloque sin afectar lógica; el parser propio respeta la estructura comment-source + target-line.

### 2026-04-24 — Análisis de fuentes: cmap + render visual antes de reemplazar
**Contexto:** FromTheSin tiene varias fuentes custom (`VarelaRound`, `Romudiane`, `Barlow-SemiBold`, `Bartina`, `Stray Robotalk Regular`). Antes de traducir hay que verificar cobertura de glifos ES (tildes, ñ, ¿, ¡).
**Decisión:** dos pasos. (1) `tools/_downloads/check_fonts.py` escanea el cmap de cada `.ttf` para detectar caracteres soportados. (2) `render_textbox_v2.py` renderiza muestras EN/ES a tamaño real del juego (1116×203 px @ 34pt, 5 muestras de longitud creciente). Solo reemplazar la fuente que falla.
**Razón:** evita reemplazos innecesarios; `VarelaRound` y `Romudiane` ya soportan ES y reemplazarlas degradaría la estética. Solo `Stray Robotalk Regular` (personaje pcu/máquina) carecía de tildes/ñ.
**Alternativas descartadas:** insertar glifos faltantes con fuente fallback inline (Ren'Py soporta `gui.font_replacements` pero degrada legibilidad por mezcla de tipografías); saltar tildes (rompe lectura).

### 2026-04-24 — VT323 como override para Stray Robotalk
**Contexto:** se necesita una fuente con estética terminal/retro/máquina y cobertura ES completa.
**Decisión:** usar `VT323.ttf` (Google Fonts, OFL) renombrada como `Stray Robotalk Regular.ttf` y colocada en `game/fonts/tl/spanish/`. Ren'Py automáticamente prefiere ese path cuando el idioma activo es spanish.
**Razón:** licencia compatible, glifos completos ES, mantiene la estética de monitor antiguo del personaje pcu. Verificada visualmente con renders del textbox real.
**Alternativas descartadas:** modificar la fuente original con FontForge (fragil, viola TOS si no es libre); usar Px437 IBM (más pixelada, peor legibilidad a 34pt).

### 2026-04-24 — Onomatopeyas como glosario locked (target == source)
**Contexto:** el MT traduce "Sigh" → "suspirar", "Gasp" → "jadear", rompiendo la convención narrativa.
**Decisión:** añadir entradas al glosario con target idéntico al source para forzar passthrough.
**Razón:** simplifica vs lista negra externa; reusa la maquinaria de protect_glossary que ya bypaseaba el MT.

### 2026-04-24 — Compuestos completos sí van al glosario
**Contexto:** "Third Precept" → "Tercer Precepto" funciona como bloque pero "Precept" suelto rompe (depende del artículo).
**Decisión:** glosario admite compuestos N-gram completos como entradas atómicas. La tokenización los reemplaza primero.
**Razón:** evita que el MT traduzca palabra por palabra perdiendo el calco oficial. No introduce el problema de concordancia porque el bloque ya incluye su determinante.

### 2026-04-25 — Pipeline case-insensitive para nombre de idioma
**Contexto:** Broken Dreams trae traducción humana en `tl/Spanish/` (capital S). El parser de `lib_rpy.py` y los detectores en `translate.py`/`find_untranslated.py`/`lint.py` tenían hardcoded `translate spanish` lowercase, lo que hacía que el pipeline no viera ningún bloque del juego.
**Decisión:** todos los matches de `translate <lang>` en los scripts del pipeline son case-insensitive. El header del archivo `.rpy` y el `Language("...")` del selector deben coincidir entre sí, pero pueden ser cualquier capitalización.
**Razón:** los autores eligen capitalización arbitraria (vimos `spanish`, `Spanish`, podría aparecer `ES`). El pipeline debe adaptarse al juego, no al revés.

### 2026-04-25 — Vaciar mirrors antes de MT (clear_mirror_targets.py)
**Contexto:** `renpy.exe . translate <lang>` rellena los nuevos targets con copia del source, no con string vacío. `translate.py` por diseño solo procesa targets vacíos para no pisar trabajo humano. Resultado: pipeline veía 0 pendientes en BD aunque hubiera 8051.
**Decisión:** introducir paso obligatorio `clear_mirror_targets.py --all <tl_dir>` entre Fase 1 y Fase 4. Solo vacía bloques con `target == source`; preserva traducciones humanas reales (target ≠ source).
**Razón:** mantiene la garantía "translate.py no pisa nada humano" sin sacrificar ergonomía. Backup `.mirror-bak` por archivo para reversibilidad.
**Alternativas descartadas:** modificar `translate.py` para considerar `target == source` como pendiente — frágil porque hay casos legítimos donde la traducción correcta es idéntica (ej. "OK", nombres propios).

### 2026-04-25 — check_fonts.py movido a tools/tl/ con fontTools
**Contexto:** el playbook referenciaba `tools/_downloads/check_fonts.py` pero no existía en este workspace. Necesario para Fase 1.5.
**Decisión:** crear `tools/tl/check_fonts.py` usando `fontTools` (pip install fonttools). Reporta cobertura ES (tildes, ñ, ¿¡, ü) y tipográficas (« » — – …) por fuente, escaneando recursivamente carpetas.
**Razón:** fontTools es estándar de facto, parsea cmap fiable; mantenerlo en `tools/tl/` agrupa todo el pipeline en un sitio.

### 2026-04-25 — Detección de traducción humana preexistente (Fase 0.5)
**Contexto:** Broken Dreams trae 2670 líneas humanas de 2022 dentro de `tl/Spanish/`. Regenerarlas con MT habría destruido trabajo del autor.
**Decisión:** añadir Fase 0.5 al playbook que verifica `tl/<lang>/` antes de generar. Contar coverage humana (target ≠ source) y solo aplicar MT a los gaps. Documentar el case del idioma encontrado.
**Razón:** muchos juegos crowd-translated tienen avances parciales en repos comunitarios; preservar es la opción correcta éticamente y casi siempre la traducción humana es mejor que MT.

### 2026-04-25 — translate.py procesa siempre ambos formatos (mixed-aware)
**Contexto:** `custom_screens.rpy` de Broken Dreams empieza con bloques `translate Spanish foo:` (dialogue) y luego trae `translate Spanish strings:`. `detect_format()` solo lee 4 KB del header y al ver `strings:` clasificaba todo el archivo como strings, dejando los 92 bloques dialogue sin traducir.
**Decisión:** `main()` ahora detecta `has_strings` y `has_dialogue` por separado y ejecuta los procesos correspondientes en orden, independientemente de cuál apareció primero. Caso simétrico al ya soportado `dialogue → strings`.
**Razón:** el orden de bloques en el archivo .rpy lo decide Ren'Py al generar y puede variar. El pipeline no debe asumir layout fijo.



### 2026-04-25 � postprocess.py: regla "I residual" + soporte multi-proyecto
**Contexto:** DeepL deja el pronombre "I" ingl�s sin traducir cuando le precede un tag Ren'Py (ej. `{i}I no deber�a molestarla`) o al inicio de oraci�n. En Broken Dreams se observaron ~50 casos en archivos del batch 1.
**Decisi�n:** a�adir regla regex en `postprocess.py`: `(inicio|tras puntuaci�n fuerte|tras }) + I + min�scula espa�ola` ? eliminar el `I`. Tambi�n se a�adi� flag `--root <dir>` para procesar cualquier proyecto, no solo FromTheSin.
**Raz�n:** patr�n sistem�tico y determin�stico, f�cil de capturar y reversible. Multi-proyecto evita duplicar el script.


### 2026-04-25 — strip_rpa_entries.py: limpiar tl/<lang>/ embebidos en .rpa
**Contexto:** Broken Dreams content.rpa contenía 16 archivos 	l/Spanish/*.rpy[c] (versión vieja del juego) además de los nuestros en disco. Ren'Py los carga ambos → Exception: A translation for "X" already exists. La compilación fallaba sin que los .rpy en disco tuvieran duplicados visibles.
**Decisión:** nuevo script 	ools/tl/strip_rpa_entries.py que reescribe in-place el índice de un .rpa removiendo entradas por prefijo. NO copia el body (1.4 GB en BD). Hace backup .prestrip.bak. Operación: leer header + índice al final → eliminar claves → reescribir header (mismo size) + índice truncando archivo.
**Razón:** alternativa (extraer .rpa entero, borrar, reempacar) requería decidir si reempacar o dejar todo descomprimido (problema con assets binarios + cargar desde disco vs archive). Reescribir solo el índice es minimalmente invasivo y rápido.
**Alternativas descartadas:** descomprimir todo el .rpa (riesgo de duplicar 1.4 GB de assets en disco); usar rchive config Ren'Py para que ignore tl/ (no soportado nativamente); modificar tl/<lang>/common.rpy para borrar duplicados (no funciona porque la versión del .rpa carga primero por orden alfabético interno).

### 2026-04-25 — Preflight 0.4.1 y 0.4.2 obligatorios antes de Fase 1
**Contexto:** en BD se descubrió a posteriori (durante Fase 7 compile) que (a) el source EN tenía 2 bloques con : sin contenido (scene sea_25 with fade :, show grain_overlay_3:) y (b) el .rpa contenía 	l/Spanish/ embebido. Ambos hubieran fallado igual sin tocar el pipeline MT. El descubrimiento tardío hace dudar del estado del MT y causa rework innecesario.
**Decisión:** añadir al playbook dos preflight checks obligatorios antes de la Fase 1 (generate translations):
  1. Compile dry-run del source EN (
enpy.exe . compile) y resolver errores de sintaxis.
  2. Inspeccionar .rpa por entradas 	l/<lang>/; si las hay, strip_rpa_entries.py antes de continuar.
**Razón:** mover la detección de problemas al inicio del pipeline ahorra 1-2 horas de re-debug al final y evita atribuir falsamente fallos al MT.

### 2026-04-26 — .env central + auto-loader para credenciales
**Contexto:** las API keys (DeepL y futuras) vivían solo en variables de entorno de la sesión actual; cada terminal nueva exigía re-export y quedaban en el historial de PowerShell. No había archivo único de verdad.
**Decisión:** crear `.env` en la raíz del workspace (`c:\xampp\htdocs\tl\.env`) con todas las claves en formato `KEY=value`. Crear `tools/tl/_env.py` con `load_env()` sin dependencias externas que busca el primer `.env` subiendo desde cwd y desde la ubicación del script. Se importa al inicio de `translate.py` (`from _env import load_env; load_env()`) y solo escribe en `os.environ` las claves que no estén ya seteadas (env vars existentes ganan). `.gitignore` excluye `.env`.
**Razón:** una sola fuente de verdad, no se commitea, no requiere reexport por sesión, no contamina el historial de PowerShell. `python-dotenv` es overkill para 30 líneas de loader.
**Alternativas descartadas:** dependencia `python-dotenv` (innecesaria); guardar keys en `memory/` (visible y no es ese su propósito); mantener solo env vars manuales (frágil).

### 2026-04-26 — fix_empty_blocks.py: artefacto de unrpyc en Ren'Py 8.x
**Contexto:** Maeves Academy Witcher (Ren'Py 8.1.4) decompilado con unrpyc 2.0.4 produce miles de errores `expects a non-empty block` en patrón `show/scene/hide <X> at <transform>:` con bloque vacío. unrpyc añade `:` espurio cuando el original era inline (`show X at Y` sin bloque). En Maeves: 7645 líneas en 52 archivos.
**Decisión:** crear `tools/tl/fix_empty_blocks.py` que recorre `.rpy` recursivamente y quita el `:` final cuando la siguiente línea no-vacía no está más indentada que la sentencia. Modo `--dry` para preview.
**Razón:** editar a mano 7645 líneas no es viable. Patrón único y determinista, regex simple. Caso real: Maeves pasó de 7645 errores a 0 tras una pasada.
**Alternativas descartadas:** parchear unrpyc (más invasivo, no garantiza estabilidad para futuros juegos); recompilar desde otra fuente (no disponible); ignorar warnings (compile aborta, no son warnings).
### 2026-04-26 — Gemini 2.5-flash-lite + batch como alternativa a DeepL para volumen
**Contexto:** Maeves Academy Witcher tiene ~1M chars EN→ES; DeepL Free agota su cupo de 1M/mes con un solo juego. Probada Gemini API: en single-string el free tier de gemini-2.5-flash es 250 RPD, inviable para ~25k strings. Se descubrió que el problema era no usar batching.
**Decisión:** implementar gemini_translate_batch en 	ranslate.py que envía un JSON array a Gemini (con 
esponseSchema=ARRAY of STRING para forzar mismo N de items) y resuelve N strings por request. Default: gemini-2.5-flash-lite (15 RPM, 1000 RPD, 250k TPM) con batch_size=25 → ~25k strings/día. Fallback automático per-item si el batch falla (size mismatch / PROHIBITED_CONTENT), y de ahí a DeepL si hay key.
**Razón:** lite cubre la mayoría de juegos en una jornada manteniendo calidad aceptable (verificado en Maeves: tono natural, tildes, tags {i}{w=1.0} preservadas). Para diálogo delicado o calidad superior queda --gemini-model gemini-2.5-flash (250 RPD pero con batch sigue rindiendo). Las cuotas son por proyecto, no por key — escalado vertical mediante batch_size, no múltiples keys.
**Alternativas descartadas:** Ollama local (HW insuficiente — RX 570 4GB); MyMemory para volumen (calidad muy inferior); pagar DeepL Pro (~/mes innecesario para uso personal); Groq (no probado, dejar como reserva).

### 2026-04-27 - Pausa Dimension 69; foco en Hypno Academy
**Contexto:** El desarrollador de Dimension 69 ya esta trabajando en una version oficial en espanol, por lo que el esfuerzo de parche local deja de ser prioritario. El siguiente proyecto activo pasa a ser Hypno Academy (Unity).
**Decision:** pausar todo trabajo de traduccion/reinyeccion en Dimension 69 y continuar con Hypno Academy. Para avanzar rapido sin depender de tipetrees legibles en assets de escena, se prepara pipeline runtime con BepInEx + XUnity.AutoTranslator sobre copia de seguridad previa.
**Razon:** evita rework en un juego que recibira traduccion oficial y desbloquea progreso inmediato en el nuevo objetivo. En Hypno Academy no se detecto una fuente de texto plana equivalente a Naninovel por inspeccion inicial, asi que runtime MT es el camino de menor friccion para arrancar.
**Alternativas descartadas:** continuar parcheando Dimension 69 en paralelo (duplicacion de esfuerzo); forzar reinyeccion manual de assets de Hypno Academy sin mapa de campos fiable (alto riesgo y bajo rendimiento).

### 2026-04-27 - Hypno Academy: doorstop winhttp no engancha
**Contexto:** Se instalo BepInEx + XUnity en Hypno Academy con backup previo. El juego arranca, pero no se genera `AutoTranslatorConfig.ini` ni carpetas `Translation`, y no aparecen trazas de BepInEx en `output_log.txt`.
**Decision:** no continuar con la via `winhttp.dll` como injector principal para este juego; marcar el estado como bloqueo tecnico de inyeccion por proxy.
**Razon:** inspeccion del PE (`Hypno-Academy.exe`) muestra imports minimos (`UnityPlayer.dll`, `KERNEL32.dll`) y no carga `winhttp.dll`, por lo que Doorstop no llega a ejecutarse en esta build.
**Alternativas descartadas:** seguir iterando configuracion de XUnity sin resolver el punto de entrada del injector; asumir que el plugin carga en subcarpetas sin evidencia en logs.

### 2026-04-27 - Hypno Academy: extraccion estatica como flujo principal
**Contexto:** Con la via runtime bloqueada, se necesita un metodo fiable para obtener corpus traducible sin depender de inyeccion. Hypno Academy usa Unity Mono + Fungus y almacena texto en escenas/assets binarios (`level*`, `sharedassets*.resS`, `resources.*`).
**Decision:** adoptar extraccion estatica por scanner binario y normalizacion a JSONL estandar. Se crearon `tools/unity/extract_static_strings.py` y `tools/unity/prepare_static_corpus.py`. Primera corrida sobre `Hypno-Academy_Data` produjo 110892 strings unicos crudos y 3982 candidatos traducibles, luego normalizados a `static_strings_corpus.jsonl`.
**Razon:** desbloquea el pipeline sin runtime hook, con salida reproducible y apta para MT por lotes (`source/target`). La muestra extraida incluye dialogo real de historia, nombres y UI, suficiente para continuar con traduccion masiva y luego reinyeccion.
**Alternativas descartadas:** esperar un injector alterno antes de extraer (bloquea progreso); extraer manualmente en GUI (lento y no reproducible).