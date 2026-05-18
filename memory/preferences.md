# Preferences

Preferencias de colaboración, estilo de código, y cómo el usuario quiere que trabajes.

<!-- Ejemplos de qué guardar aquí:
- Estilo de comunicación (ej. "Respuestas concisas, sin resúmenes al final")
- Convenciones de código preferidas
- Herramientas favoritas
- Flujos de trabajo (ej. "Siempre crear rama antes de editar")
- Cosas a evitar (ej. "No agregar comentarios redundantes")
-->

## Flujo de trabajo

- Evitar trabajo manual aunque sean pocos casos. Preferir soluciones que automaticen incluso el post-edit.
- **Traducción Ren'Py — chequeo obligatorio de fuentes ANTES de MT**: ejecutar `check_fonts.py` sobre `game/` (y `game/fonts/` si existe) y resolver overrides en `game/tl/<lang>/<mismo nombre>.ttf` antes de lanzar el pipeline de MT. No traducir si una fuente de diálogo/UI/choice no soporta `áéíóúñ¿¡üÑÉÍÓÚÁÜ`. Caso Maeves: las 5 fuentes (RobySoho, Cheeky Rabbit, Next Sunday, HorrorFont, CHERL___) no tenían cobertura ES → reemplazadas por DejaVuSans con path-override.
- Mantener actualizada la memoria (`memory/`) durante la sesión, no solo al final.
