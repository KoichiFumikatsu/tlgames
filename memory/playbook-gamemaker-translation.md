# Playbook: Traduccion GameMaker al Espanol

## Fase 0 — Preparacion

1. Colocar el juego en `proyects Game TL/GameMaker/<Juego>/`.
2. Crear backup completo en `backups/GameMaker/<Juego>-original/`.
3. Identificar si hay fuente (`*.yyp`) o solo build compilado (`data.win`).

## Fase 1 — Identificar version/formato

Buscar:

```text
data.win
options.ini
*.yyp
objects/**/*.yy
rooms/**/*.yy
scripts/**/*.yy
```

## Fase 2 — Inventario de texto

- Proyecto fuente: strings en `.yy`, `.gml`, rooms, objects, scripts y localization si existe.
- Build: strings dentro de `data.win`, code entries y texture pages si hay texto en imagen.

## Fase 3 — Extraccion

- Preferir UndertaleModTool/UTMT para `data.win`.
- Exportar strings a JSONL/CSV con id estable.
- Separar strings UI/dialogo de nombres internos.

## Fase 4 — MT

- Proteger placeholders: `{0}`, `%s`, `%d`, `\n`, variables GML, markup propio.
- No traducir resource names, object names, script names ni paths.

## Fase 5 — Reinyeccion y QA

- Reimportar con herramienta compatible.
- Probar menu, opciones, dialogo, inventario, guardado/carga.
- Revisar overflow y fuentes.
