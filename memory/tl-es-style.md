# FromTheSin — Guia de estilo ES

Referencia para el pase humano de pulido sobre la salida MT. Se aplica despues
de `translate.py` + `lint.py`.

## Reglas generales

- **Nombres propios se preservan**: Zell, Eris, Linea, Lily, Silika, Nova,
  Ada, Cluster, Yurei, Kironomiya, Cetia, Rinoa, Altra, Rika. El glosario los
  protege en `target: "<nombre>"`.
- **Terminos del mundo** con mayuscula: Precept/Preceptos, Catalyst/Catalizador,
  Brigade/Brigada, Unit A.D.A. Type-00. Mantener mayuscula en ES.
- **Formato narrativo**: usar "—" para dialogos internos cuando quepan; en la
  mayoria de casos conservar comillas dobles ya presentes en el source.
- **Onomatopeyas** (Sigh, Haah, Slurp, Gasp, Inhale, Pant, Cough, Lick, Mhm,
  Hehehe, etc.): se dejan igual o se adaptan minimamente ("*suspiro*",
  "*jadeo*"). No traducir literal.
- **Caps enfaticos** (SOOO ANNOYING, WHY, STOP, HUH): conservar caps, traducir
  el contenido. Ej. `"WHY"` -> `"POR QUE"` (sin signo inicial para ahorrar
  espacio/respetar caps).
- **Tuteo**: usar "tu" (no "usted") para todo dialogo casual. Usted solo si un
  personaje lo justifica (formal/reverente).
- **Genero por defecto masculino** para el MC (Zell). Si el usuario eligiera
  otro nombre al iniciar, el juego no sabra cambiar concordancias — eso es
  limitacion conocida.

## Voz por personaje

### pcu (IA, fuente Stray Robotalk → VT323)
- **Registro**: robotico, frases cortas, sin emocion.
- **Ejemplos de tono**:
  - EN `"System online."` → `"Sistema activo."`
  - EN `"Processing request... Standby."` → `"Procesando solicitud... Espera."`
  - EN `"Warning: memory corruption in sector seven."` → `"Advertencia: corrupcion de memoria en el sector siete."`
- **Evitar**: exclamaciones, diminutivos, expresiones humanas.
- **Sin tildes**: VT323 soporta tildes, pero si aparece texto muy largo el
  pcu tiene solo ~38% de slack vertical, asi que preferir frases directas.

### mc (Zell, protagonista, POV interno)
- **Registro**: coloquial, introspectivo. Puede dudar, hacer pausas con "...".
- **Placeholders `|msg_Thinking_*|`**: preservar textualmente. Son iconos.
- Pensamientos entre parentesis se mantienen: `"(Ou sea... donde estoy?)"`.

### p3 (Third Precept)
- **Registro**: solemne, profetico, amenazante. Frases mas largas permitidas.
- Evitar contracciones coloquiales.

### e (Eris) / ll (Linea) / l (Lily) / n (Nova) / s (Silika)
- Tono casual, variedad por personaje. Se afina en el pase de pulido.
- Linea y Lily tienden a ser mas dulces; Nova mas directa/sarcastica
  (ajustar segun lectura).

### un / un2 (???)
- Mantener misterio. No revelar identidad en la traduccion.

## Consideraciones tecnicas

- **Expansion ES >150% del EN** en `lint.py` → revisar overflow en textbox
  (dialogue_width=1116, dialogue_ypos=75, textbox_height=278 → 203 px utiles).
- **`\n` literal**: conservar exactamente el mismo numero.
- **Variables `[Zell]`, `[mc!t]`**: no tocar. El tokenizador las protege.
- **Tags `{color=#XXX}...{/color}`, `{i}...{/i}`**: no tocar. Idem.
- **Placeholders `|msg_...|`, `|emote_...|`, `|icon_...|`**: idem, son marcadores
  graficos.

## Flujo de trabajo

1. `build_glossary.py` → genera `tl-es-glossary.json`
2. **Usuario revisa y completa targets** del glosario
3. `translate.py <archivo.rpy>` → traduce via MyMemory + aplica glosario
4. `lint.py <archivo.rpy>` → reporta issues
5. Humano corrige issues y pule voz
6. Probar en juego (preferencias → idioma → spanish)
