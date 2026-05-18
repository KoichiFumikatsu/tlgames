# Playbook: Traduccion RPG Maker al Espanol

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
