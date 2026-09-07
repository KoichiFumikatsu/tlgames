# Playbook: Traduccion RPG Maker al Espanol

## Trampas críticas (pipeline automático)

- **`openai_translate_batch` no se llama directamente con todo el archivo** — espera chunks de `OPENAI_BATCH_SIZE=25`. Usar siempre `_openai_chunked()` en `translate_rpgmaker.py`.
- **DeepL 456 genera notificación por cada string si no se corta el loop** — verificar `if not deepl_active: continue` al inicio del for antes de llamar `deepl_translate`.
- **Estado de cuota DeepL persiste en `.cache/deepl_quota_state.json`** — si el archivo dice hoy, DeepL se salta sin intentar. Se resetea solo al día siguiente.
- **CommonEvents.json puede tener 7000+ strings** — el pipeline puede tardar 30-60 minutos en este archivo solo con OpenAI. Normal, no es un hang.
- **Dos instancias del mismo juego simultáneas** — si el servidor se reinicia con un job corriendo, el subproceso sobrevive. Verificar con `ps aux | grep translate_rpgmaker` y matar el viejo.

## Fase 0 — Preparacion

1. Colocar el juego en `proyects Game TL/RPGMaker/<Juego>/`.
2. Crear backup completo en `backups/RPGMaker/<Juego>-original/`.
3. No modificar `Data/` ni `PBS/` antes de inventario.

## Fase 1 — Identificar engine

Revisar:

```text
Game.ini
RGSS*.dll
mkxp.json
Data/*.rxdata | *.rvdata | *.rvdata2
package.json | www/package.json
data/*.json | www/data/*.json
```

Criterios:

- `RGSS104E.dll` + `Data/Scripts.rxdata` => RPG Maker XP/RGSS.
- `mkxp.json` => ejecuta via mkxp/mkxp-z, comun en Pokemon Essentials moderno.
- `PBS/` + `Plugins/*.rb` => Pokemon Essentials.
- `js/rpg_core.js` / `www/js/rpg_core.js` o `rpg_managers.js` => RPG Maker MV.
- `js/rmmz_core.js` / `www/js/rmmz_core.js` => RPG Maker MZ.

## Fase 2 — Inventario de texto

Pokemon Essentials/RGSS:

- `PBS/*.txt`: datos de Pokemon, items, moves, trainers, metadata.
- `Plugins/**/*.rb`: UI, sistemas, textos hardcodeados.
- `Data/Map*.rxdata`: dialogos/eventos.
- `Data/CommonEvents.rxdata`: eventos comunes.
- `Data/Scripts.rxdata`: scripts Ruby compilados.
- `Data/messages_game.dat`: tabla Ruby Marshal de `MessageTypes`, util como corpus de traduccion, pero no sustituye automaticamente los textos hardcodeados en `Map*.rxdata` si el juego no activa un idioma alternativo. Si el juego sigue en ingles tras traducir `messages_game.dat`, extraer/reinyectar tambien `Map*.rxdata` y `CommonEvents.rxdata`.
- Pokemon Essentials: activar idioma con `Settings::LANGUAGES` en `Data/Scripts.rxdata` y archivos `Data/messages_<fragment>_core.dat`/`Data/messages_<fragment>_game.dat`. Evitar plugins para forzar idioma si `Data/PluginScripts.rxdata` ya existe y el juego depende de su cache.
- Pokemon Essentials/RGSS en Windows: al hacer fixes manuales desde PowerShell, no escribir acentos directamente por stdin; usar escapes `\uXXXX` y decodificar solo esos escapes para no convertir codigos del juego como `\r`, `\b`, `\c[n]`, `\G`.

MV/MZ:

- `data/*.json` o `www/data/*.json`: mapas, common events, database.
- `js/plugins.js` contiene parametros activos de plugins; puede incluir JSON escapado con textos visibles.
- `js/plugins/*.js` o `www/js/plugins/*.js`: textos hardcodeados de plugins.
- En comandos de plugin (`code:357`), no traducir nombres de parametros ni identificadores internos dentro de argumentos JSON. Ejemplo Hero MZ: `QuestSystem/StartQuestScene` requiere `QuestCommands=["orderingQuest","questOrder","questReport"]` y `BackgroundImage={"FileName1","FileName2","XOfs","YOfs"}`; traducirlos a ES causa crash `Unknown quest command ...`.

## Fase 3 — Extraccion

- Usar parser real del formato cuando exista.
- No regex global sobre binarios salvo como ultimo recurso de inventario.
- Mantener claves, ids, symbols y comandos intactos.
- Exportar a JSONL intermedio: `source_file`, `record_id`, `field`, `source`, `target`.

## Fase 4 — MT

- DeepL si cabe en cuota.
- OpenAI si requiere contexto o volumen grande.
- Proteger placeholders: `\v[n]`, `\n[name]`, `\c[n]`, `%s`, `{1}`, `[VAR]`, Ruby interpolation `#{...}`.
- No traducir symbols Ruby, filenames, ids, switches/variables internas.
- En MV/MZ, tratar `plugin_command_args` como zona mixta: traducir solo valores claramente visibles para usuario; preservar claves, enums, comandos DSL y arrays de identificadores.
- En MV/MZ, no traducir referencias de assets aunque esten en JSON de datos. Ejemplo Hero MZ: `Tilesets.json` campo `tilesetNames` debe conservar rutas como `DreamlandStarter/FD_Grasslands_B`; traducirlas a `FD_Praderas_B` causa `Failed to load img/tilesets/...`.
- En MV/MZ, preservar tambien nombres tecnicos de assets en eventos y mapas: SE/BGM/BGS/ME (`add/Footsteps_Grassland`), `battleback1Name`, `parallaxName`, `Show Picture` (`Explore/Grassland`), faces/characters/titles. Si la referencia traducida no existe en disco y la del backup si, restaurar la del backup.
- En opciones de eventos MV/MZ, sufijos como `if(...)` y `en(...)` pueden ser sintaxis de plugins de elecciones; no traducirlos a `si(...)` ni reordenarlos. Traducir solo la etiqueta visible antes del sufijo, por ejemplo `Touch if(v[113]!=0)` -> `Tocar if(v[113]!=0)`.
- En comandos de script MV/MZ (`code:355` y continuaciones `code:655`), preservar el JavaScript exactamente desde el original. Identificadores como `Scene_Menu`, `Window_MenuCommand`, `SceneManager` o `$gameVariables` no son texto visible; traducirlos causa `ReferenceError`.

## Fase 5 — Reinyeccion

- Reinyectar en copia de trabajo primero.
- Para `PBS/*.txt` y JSON, escribir UTF-8 y preservar estructura.
- Para `rxdata/rvdata`, usar serializador compatible; no editar bytes a mano si cambia longitud.

## Fase 6 — QA

- Arrancar juego.
- Revisar menu, dialogos, batalla, mochila, Pokedex, opciones, quests.
- Revisar overflow: RPG Maker XP tiene cajas pequenas; abreviar antes que reducir legibilidad.
- Revisar fuentes: acentos, `ñ`, `¿`, `¡`, `ü`.

## Lint automatico (pipeline stage `lint_qa`) — desde 2026-05-24

El pipeline ahora corre `tools/tl/lint_rpgmaker.py` para `engine=rpgmaker` (antes el stage se saltaba con `engine_unsupported`). Compara `<data>/<archivo>.json.bak` (source EN) contra `<archivo>.json` (target ES) recorriendo las mismas rutas que `translate_rpgmaker.extract_strings()`.

Checks emitidos:
- `CTRL` — control codes RPGMaker perdidos/alterados (`\C[n] \I[n] \N[n] \V[n] \P[n] \G \. \! \> \< \^ \{ \}`, `%1..%9`).
- `EMPTY` — target vacio con source no vacio.
- `UNCHANGED` — target == source. Filtra nombres propios CamelCase (`Raphaela`) y speaker labels (`[Ruby]`); el resto suele ser onomatopeya legitima o traduccion olvidada — revisar caso por caso.
- `EN_RESID` — heuristica suave de palabras EN comunes en target. Ruido esperable; no bloquear por esto.
- `OVERFLOW` — source < 30 chars y `len(target)/len(source) > 1.4` → riesgo desborde en labels/choices/botones.
- `EXPAND` — ratio > 1.6 general.

Salida: stdout JSON con `summary`, `issues_total`, `strings_compared`, `files_no_bak`. Pipeline persiste en `job.lint_report` y `job.stages.lint_qa.details`. No es bloqueante.

Si un archivo no tiene `.json.bak` (extract no encontro strings EN traducibles), queda en `files_no_bak` y no se compara.

`STAGE_PCT["rpgmaker"]` ajustado a `translate:75, lint_qa:5, package:10` para reservar progreso al lint.

## Mejoras pendientes de lint (playbook futuro, no bloqueantes)

Discutidas 2026-05-24; aplican a engines con strings cortos visibles (labels, choices, botones):

1. **Prompt con `max_length` explicito** — cuando `extract_strings` clasifique un string como label/choice (< 30 chars), pasar instruccion al traductor "maximo N caracteres" en el prompt OpenAI/DeepL.
2. **Glosario de abreviaciones canonicas** — entradas pre-MT para terminos que rompen layout: `Configuracion → Ajustes`, `Guardado Rapido → G. Rapido`, etc.
3. **Re-prompt automatico** — strings flagged `OVERFLOW` se reintentan con instruccion de brevedad antes de reportar.

Casos historicos observados: botones tipo "Achievements" → "Logros" caben; "Quick Save" → "Guardado Rapido" se desborda. Choices de 2 lineas EN pueden volverse 3 en ES y romper layout.
