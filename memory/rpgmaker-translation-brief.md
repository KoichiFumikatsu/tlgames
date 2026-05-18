# Brief — Traduccion de Juegos RPG Maker

Uso personal. Objetivo: localizar, extraer, traducir y probar juegos RPG Maker sin mezclar el flujo con Ren'Py o Unity.

## Variantes comunes

- RPG Maker XP / RGSS: `Game.exe`, `Game.ini`, `RGSS*.dll`, `Data/*.rxdata`, scripts Ruby.
- RPG Maker VX / VX Ace: `Game.ini`, `RGSS2xx/3xx.dll`, `Data/*.rvdata` o `*.rvdata2`.
- RPG Maker MV / MZ: `www/` o raiz del juego con `package.json`, `js/rpg_*.js` / `js/rmmz_*.js`, `data/*.json`.
- Pokemon Essentials: base RPG Maker XP/RGSS + `PBS/`, `Plugins/*.rb`, `Data/Scripts.rxdata`, a veces `mkxp.json`.

## Prioridad de enfoques

1. Identificar version exacta por `Game.ini`, DLL RGSS, `mkxp.json`, `www/`, `package.json`, `js/rpg_*.js` o `js/rmmz_*.js`.
2. Hacer backup completo antes de tocar `Data/`, `PBS/` o scripts.
3. Preferir archivos fuente editables (`PBS/*.txt`, `Plugins/*.rb`, JSON MV/MZ) antes de binarios.
4. Para XP/VX/Ace, extraer texto de `Data/*.rxdata/rvdata/rvdata2` con herramienta que entienda Ruby Marshal/RGSS.
5. Validar fuentes antes de MT: tildes, `ñ`, `¿`, `¡`, `ü`.

## Pokemon Essentials

- Textos de datos: `PBS/*.txt`.
- UI/sistema/plugins: `Plugins/**/*.rb` y `Data/Scripts.rxdata`.
- Eventos/mapas/dialogo: `Data/Map*.rxdata` y `Data/CommonEvents.rxdata`.
- Traduccion debe preservar nombres internos, ids, symbols Ruby, comandos de evento y placeholders.

## Carpetas del workspace

- Juegos: `proyects Game TL/RPGMaker/<Juego>/`.
- Backups: `backups/RPGMaker/<Juego>-original/`.
- Logs: `logs/rpgmaker/<juego>-*.log`.
