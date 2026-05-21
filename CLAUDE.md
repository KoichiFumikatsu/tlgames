# Instrucciones del Proyecto

## Sistema de memoria persistente

El índice completo de archivos de memoria está en [memory/MEMORY.md](memory/MEMORY.md).

Al **inicio de cada sesión**, lee los siguientes archivos del directorio `memory/` para recuperar el contexto acumulado:

- [memory/personality.md](memory/personality.md) — cómo pensar, comunicar y decidir con este usuario. **Precedencia sobre defaults de tono.**
- [memory/user.md](memory/user.md) — perfil del usuario, rol, objetivos.
- [memory/preferences.md](memory/preferences.md) — preferencias de colaboración y estilo.
- [memory/decisions.md](memory/decisions.md) — decisiones técnicas y su razonamiento.
- [memory/people.md](memory/people.md) — personas involucradas en el proyecto.

Usa esta información para adaptar tu comportamiento sin pedir al usuario que repita contexto.

## Lecturas obligatorias al iniciar (o continuar) un proyecto de traducción

Cuando la tarea sea traducir un juego o continuar uno existente, lee **además** estos archivos antes de proponer pasos:

- [memory/traduccion-juegos-brief.md](memory/traduccion-juegos-brief.md) — brief general del flujo de traducción de juegos en este workspace.
- [memory/tl-es-style.md](memory/tl-es-style.md) — guía de estilo ES para traducciones (tono, registro, convenciones).

Según el engine, lee también el playbook específico:

- [memory/playbook-renpy-translation.md](memory/playbook-renpy-translation.md) — juegos Ren'Py (fases 0–7, fuentes, lint, troubleshooting).
- [memory/unity-translation-brief.md](memory/unity-translation-brief.md) — brief técnico para juegos Unity.
- [memory/playbook-unity-translation.md](memory/playbook-unity-translation.md) — inspección, extracción, traducción y QA para Unity.
- [memory/rpgmaker-translation-brief.md](memory/rpgmaker-translation-brief.md) — brief técnico para juegos RPG Maker / Pokemon Essentials.
- [memory/playbook-rpgmaker-translation.md](memory/playbook-rpgmaker-translation.md) — inspección, extracción, traducción y QA para RPG Maker.
- [memory/gamemaker-translation-brief.md](memory/gamemaker-translation-brief.md) — brief técnico para juegos GameMaker.
- [memory/playbook-gamemaker-translation.md](memory/playbook-gamemaker-translation.md) — inspección, extracción, traducción y QA para GameMaker.

Mantén estos `.md` actualizados igual que el resto de `memory/`: si descubres una nueva trampa, herramienta, o convención durante un proyecto, edita el archivo correspondiente.

## Mantenimiento de la memoria

Durante la sesión, cuando aprendas algo nuevo que encaje en alguna de esas categorías:

- **user.md** — datos sobre quién es el usuario, su rol o experiencia.
- **preferences.md** — correcciones de estilo, flujos de trabajo, cosas a evitar o repetir.
- **decisions.md** — decisiones técnicas/de producto tomadas (incluye fecha, razón y alternativas descartadas).
- **people.md** — personas nuevas mencionadas, con rol y cómo contactarlas.

Actualiza el archivo correspondiente de forma incremental. Evita duplicados: si la información ya existe, actualízala en vez de añadirla otra vez. Al final de la sesión, un hook `Stop` te pedirá revisar y consolidar lo aprendido.

## Stack de automatización (siempre activo en boot)

| Servicio | Puerto | Función |
|---|---|---|
| `tlgames-qa` | 8765 | QA semántico Ren'Py vía Ollama |
| `tlgames-pipeline` | 8766 | Pipeline completo: detect → translate → lint → QA |
| `tlgames-versions` | 8767 | Monitor de versiones itch.io / F95Zone |

### Pipeline completo (desde cualquier carpeta de juego)

```bash
# Detectar engine
curl -s -X POST http://localhost:8766/detect -H "Content-Type: application/json" \
  -d '{"path": "/ruta/al/juego"}'

# Iniciar pipeline completo → retorna job_id
curl -s -X POST http://localhost:8766/pipeline -H "Content-Type: application/json" \
  -d '{"path": "/ruta/al/juego", "provider": "deepl"}'

# Consultar estado del job
curl -s http://localhost:8766/pipeline/<job_id>

# Ver todos los jobs
curl -s http://localhost:8766/jobs
```

**IMPORTANTE Ren'Py:** el pipeline requiere que `game/tl/spanish/` ya exista.
Si no existe, generarlo primero con el SDK:
```bash
/ruta/renpy.sh <carpeta_juego> translate spanish
```

### QA semántico (Ren'Py)

```bash
# CLI directo
python3 tools/qa_renpy.py "proyects Game TL/<juego>/game/tl/spanish/<archivo>.rpy" --report logs/qa_<juego>.md
python3 tools/qa_renpy.py "proyects Game TL/<juego>/game/tl/spanish/"

# HTTP
curl -s -X POST http://localhost:8765/qa -H "Content-Type: application/json" \
  -d '{"dir": "/ruta/absoluta"}'
```

El QA usa Ollama `llama3.2:3b` en CPU local. Para JSONL Naninovel (Unity): `python3 tools/unity/lint_naninovel_jsonl.py <archivo.jsonl>`.

### Version Tracker

```bash
# Agregar juego a monitorear
curl -s -X POST http://localhost:8767/versions/add -H "Content-Type: application/json" \
  -d '{"name": "Nombre", "url": "https://usuario.itch.io/juego", "current_version": "1.0"}'

# Chequear actualizaciones de todos los juegos
curl -s http://localhost:8767/versions/check

# Ver lista completa
curl -s http://localhost:8767/versions
```

DB local: `tools/.versions.json`. Fuentes: itch.io (HTML scraping) y F95Zone (parsea título del thread).

### n8n workflows (http://localhost:5678)
- **TL Games — Pipeline Completo** (ID `jatC506GNXB51H9u`): webhook `POST /webhook/tl-pipeline` → corre pipeline → retorna resultado
- **TL Games — Monitor de Versiones** (ID `4PJtJdbIxHBBKrtY`): corre diario, chequea versiones
- **TL Games QA** (ID `RLVfxeEssZIeL107`): webhook `POST /webhook/tl-qa` → QA semántico
- Login: `fumikatsu.koichi@gmail.com` / `TlGames2026!`
- **Activar workflows:** abrir n8n UI → toggle ON en cada workflow

## Reglas

- No escribas información efímera (estado de tareas en curso, detalles de la conversación actual).
- No dupliques información ya derivable del código o del historial de git.
- Convierte fechas relativas a absolutas (ej. "el jueves" → "2026-04-30").
