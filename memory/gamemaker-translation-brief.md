# Brief — Traduccion de Juegos GameMaker

Uso personal. Objetivo: localizar texto en juegos GameMaker sin mezclar el flujo con Unity/RPG Maker/Ren'Py.

## Senales de GameMaker

- Builds compilados: `data.win`, `options.ini`, `audiogroup*.dat`, `*.yydebug`.
- Proyectos fuente: `*.yyp`, carpetas `objects/`, `rooms/`, `scripts/`, archivos `*.yy`.
- HTML5: `html5game/`, JS empaquetado, `game.unx` o assets similares.

## Prioridad de enfoques

1. Si hay proyecto fuente (`*.yyp`), editar recursos `.yy`/GML con parser estructurado.
2. Si solo hay build (`data.win`), usar UndertaleModTool/UTMT o herramienta compatible para extraer strings.
3. No editar `data.win` con reemplazo binario salvo que la longitud no cambie y sea prueba controlada.
4. Mantener ids, nombres de objetos/scripts/rooms y placeholders intactos.

## Carpetas del workspace

- Juegos: `proyects Game TL/GameMaker/<Juego>/`.
- Backups: `backups/GameMaker/<Juego>-original/`.
- Logs: `logs/gamemaker/<juego>-*.log`.
