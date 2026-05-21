# User

Información sobre el usuario: rol, objetivos, experiencia técnica, contexto personal relevante para el trabajo.

## Perfil

- **Plataforma:** Linux (Ubuntu 24.04, hostname Fumilinux) — migrado desde Windows. Rutas de sesiones anteriores (`C:\renpy-8.2\`, `%LOCALAPPDATA%\`) son históricas y no aplican en este entorno.
- **Idioma:** español (conversación y entregables).

## Proyecto actual — Traducción personal de juegos al español

- **Alcance:** múltiples juegos en distintos engines. Uso personal, sin distribución pública por ahora.
- **Naturaleza:** exploratoria — evaluar viabilidad técnica y establecer un flujo replicable para futuros juegos.
- **Brief de referencia:** [traduccion-juegos-brief.md](../traduccion-juegos-brief.md).

## Juegos concretos identificados

- **FromTheSin** (2026-04-24) — Ren'Py 8.2.0. Ubicación: `proyects Game TL/FromTheSin/`. Assets empaquetados en `.rpa` (scripts, fonts, images, audio, archive). Ya trae `game/tl/italian/` con un intento previo de MT (script de terceros con ruta `D:\Test Renpy\...`, ignorable).
- **Dimension 69** (2026-04-24) — Unity con backend **Mono** (MonoBleedingEdge + `Assembly-CSharp.dll`). Ubicación: `proyects Game TL/Dimension 69/`. Addressables activos en `Dimension69_Data/StreamingAssets/aa/`. Presencia de `UnityEngine.LocalizationModule.dll` (sistema de i18n por confirmar inspeccionando la DLL).
- **Luna in the Tavern** (2026-04-28) — **Electron** (Chromium 9.2.0 + Node.js). Ubicación: `proyects Game TL/Luna in the Tavern/`. Texto principal en `resources/app/static/json/v4_2_allfree.json` (JSON plano). 22,098 strings únicos, ~847k chars únicos. Corpus secundario pequeño: `inventory_config.json`, `gallery_locked_v3.json`, UI en `wrka.html`. Sin playbook previo para Electron — pipeline más simple de todos los proyectos.
- **ナースコール警備員** (2026-04-29, completado 2026-04-30) — **Unity Mono**. Ubicación: `proyects Game TL/Unity/ナースコール警備員/`. Texto en `NurseCall_Data/SystemText.dat` (XLSX real leído por `EPPlus.dll`). 5 hojas: `jp`, `en`, `sc`, `tc`, `ko`. 681 strings traducibles, ~21,984 chars EN. Escenas H en video pre-renderizado (88 VideoPlayer). Pipeline ejecutado: manipulación ZIP/XML directa sobre SystemText.dat (openpyxl write no es compatible con EPPlus) + binary patch en level0–10 y resources.assets para los labels del dropdown de idioma. Selector muestra "Español". Costo real: ~$0.009. Scripts en `_tl_work/NurseCall/`. Ver decisions.md 2026-04-30.
- **The Demon Lord's Lover** (2026-05-20, completado 2026-05-21) — **Unity Mono** con sistema de traducción nativo. Versión 0.16.90, company ayumu98. Ubicación: `proyects Game TL/Unity/The Demon Lords Lover/the-demon-lords-lover-linux/`. Texto en `StreamingAssets/Localization/source/`: `strings.json` (JSON anidado), `grammar.json` (pronouns/nouns/separators con campos booleanos), `scenes/**/*.scene` (formato custom con `[comandos]`, `char: texto`, narración, menús indentados, tokens `{placeholder}`). Pipeline nativo: ZIP sin wrapper con `manifest.json` → import in-game via Settings → Translations → Import translation. 9.282 entradas totales (2191 strings + 1079 grammar + 6012 scenes), 100% traducidas. Costo: ~$0.002 recovery pass. Scripts en `_tl_work/TheDemonLordsLover/`. ZIP final: `_tl_work/TheDemonLordsLover/es-kelsie.zip` (296 KB). Ver decisions.md 2026-05-21.

## Juego activo (2026-05-19)

- **Adventurer Trainer** — Ren'Py. Ubicación: `proyects Game TL/Adventurer Trainer/Adv_Trainer/`. Traducción en curso en `game/tl/spanish/`. Archivos principales: `script.rpy`, `reputation.rpy`, `screens.rpy`, `common.rpy`. No hay tl-es-style.md propio todavía — usar convenciones generales.

## QA semántico automatizado (desde 2026-05-19)

- **Script directo:** `python3 tools/qa_renpy.py <archivo_o_dir.rpy> [--report logs/qa.md]`
- **Servidor HTTP:** `http://localhost:8765/qa` — `POST {"file": "/ruta"}` o `{"dir": "/ruta"}` — servicio systemd `tlgames-qa` (activo en boot)
- **n8n workflow:** "TL Games QA" en `http://localhost:5678/webhook/tl-qa` — requiere que el workflow esté activado en la UI
- **Modelo:** Ollama `llama3.2:3b` vía `http://localhost:11434`
- **Cobertura:** solo Ren'Py `old/new` format por ahora. Para JSONL Naninovel ya existe `tools/unity/lint_naninovel_jsonl.py`.
- **Filtro:** pares de 1-2 palabras (stats, atributos) se saltean — no tienen contexto suficiente para QA semántico.

## Entorno instalado (2026-04-24)

- Preexistente: VS Code, Git, winget v1.28.
- Python 3.12.10 (scope user, `%LOCALAPPDATA%\Programs\Python\Python312\`), pip 26.0.1.
- Paquete pip: `unrpa` 2.3.0.
- Extensión VS Code: `LuqueDaniel.languague-renpy` 2.2.2.
- Ren'Py SDK 8.2.3 en `C:\renpy-8.2\renpy-8.2.3-sdk\`.
- Tools portables en `tools/` del proyecto:
  - `unrpyc/` (v2.0.4 — `un.rpyc`, `un.rpy`, `bytecode-39.rpyb`).
  - `UABEA/` (v8 — `UABEAvalonia.exe`).
  - `AssetRipper/` (1.3.12 — `AssetRipper.GUI.Free.exe`).
  - `dnSpyEx/` (6.5.1 — `dnSpy.exe`).
  - `BepInEx/` (5.4.23.5 win_x64 — payload a copiar dentro del juego).
  - `XUnity.AutoTranslator/` (5.6.1 variante BepInEx — payload encima de BepInEx).
