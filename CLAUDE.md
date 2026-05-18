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

## Reglas

- No escribas información efímera (estado de tareas en curso, detalles de la conversación actual).
- No dupliques información ya derivable del código o del historial de git.
- Convierte fechas relativas a absolutas (ej. "el jueves" → "2026-04-30").
