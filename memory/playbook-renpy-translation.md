# Playbook: Traducción de juegos Ren'Py al Español

Procedimiento reproducible para traducir un juego Ren'Py de inglés a español
con calidad razonable y mínimo trabajo manual. Construido sobre el caso
**FromTheSin** (Ren'Py 8.2, ~3000 strings, ~250k chars).

> **Cuándo usar este playbook:** juego comercial o indie en formato Ren'Py
> (`.rpa` archives o `.rpy` directos), con o sin traducción oficial existente
> a otros idiomas (italiano, ruso, etc.).
>
> **Cuándo NO aplica:** juegos Unity (ver brief para XUnity.AutoTranslator),
> juegos con loader propio o engines distintos.

---

## 1. Requisitos del entorno (una sola vez)

### Software base
| Tool | Versión | Ubicación recomendada | Para qué |
|---|---|---|---|
| Python | 3.12.x | `winget install Python.Python.3.12 --scope user` | Scripts del pipeline |
| Ren'Py SDK | misma rama mayor que el juego (8.2.3 si juego es 8.2.x) | `C:\renpy-8.2\renpy-8.2.3-sdk\` | Generate Translations + compile |
| unrpyc | 2.0.4 | `tools/unrpyc/` | Decompilar `.rpyc` cuando faltan `.rpy` |
| unrpa | última | pip install: `pip install unrpa` | Extraer `.rpa` archives |

### API Translation
| Provider | Tier | Limitación | Comentario |
|---|---|---|---|
| **DeepL Free** | gratis con registro | 1M chars/mes (dashboard); el endpoint `/v2/usage` puede devolver 500k por bug — confiar en el dashboard | Calidad alta. Key con suffix `:fx`. Default. |
| MyMemory | gratis con email | ~10k palabras/día | Calidad media. Útil si DeepL agota. |

### Variables de entorno
```powershell
$env:DEEPL_API_KEY = "<tu-key>:fx"
```

### Estructura de carpetas esperada
```
<workspace>/
  proyects Game TL/<NombreJuego>/
    game/
      *.rpa              # archives originales (a extraer)
      tl/spanish/        # destino de la traducción
  tools/
    tl/                  # scripts del pipeline (commit en repo)
    unrpyc/              # decompilador (commit en repo)
  memory/                # notas de proyecto persistentes
```

---

## 2. Pipeline completo (paso a paso)

### Fase Pre-flight — Verificar entorno

Antes de tocar el juego, verificar que todo esté instalado:

```powershell
python --version                                       # 3.12.x
python -c "import unrpa; import fontTools"             # OK silencioso
Test-Path "C:\renpy-8.2\renpy-8.2.3-sdk\renpy.exe"     # True
Test-Path "tools\unrpyc\un.rpy"                        # True
[bool]$env:DEEPL_API_KEY                               # True
```

Si falta algo: `pip install unrpa fonttools` o `winget install Python.Python.3.12 --scope user`.

### Fase 0 — Preparación del juego

**0.1 Backup completo** del juego original antes de tocar nada.
```powershell
Copy-Item -Recurse "<ruta-original>" "backups/<NombreJuego>-original/"
```

**0.2 Extraer `.rpa` archives** si los hay:
```powershell
cd "proyects Game TL/<NombreJuego>/game"
python -m unrpa -mp . content.rpa  # repetir para cada .rpa
```

**0.3 Decompilar `.rpyc` → `.rpy`** SOLO si faltan los fuentes. Detectar primero:
```powershell
$rpyc = Get-ChildItem -Filter "*.rpyc" | Where-Object { -not (Test-Path ($_.FullName -replace '\.rpyc$','.rpy')) }
if ($rpyc) { Write-Host "Hay $($rpyc.Count) .rpyc sin fuente — decompilar" }
else { Write-Host "Todos los .rpyc tienen .rpy — saltar 0.3" }
```
Muchos juegos modernos empacan los `.rpy` originales junto a los `.rpyc` dentro
del `.rpa`, en cuyo caso esta fase no aplica (ej. **Broken Dreams**).

Si toca decompilar:
```powershell
Copy-Item tools/unrpyc/un.rpy "proyects Game TL/<NombreJuego>/game/"
Copy-Item tools/unrpyc/un.rpyc "proyects Game TL/<NombreJuego>/game/"
& "C:\renpy-8.2\renpy-8.2.3-sdk\renpy.exe" "proyects Game TL/<NombreJuego>" force_recompile
# Lanzar el juego una vez; un.rpy genera los .rpy faltantes.
# Después borrar un.rpy/un.rpyc del game.
```

**0.4 Verificar arranque en inglés.** Si crashea, hay bugs de decompilado
(ej. parámetros con default perdidos en `screen say`, etc.). Anotar y
parchearlos antes de seguir. Patrón típico:
- `screen <name>(arg)` debería ser `screen <name>(arg=""):` → revisar parámetros con default.
- Comparar con `un.rpy` original si fue decompilado.

**0.4.1 Compile dry-run del source en inglés.** Antes de tocar `tl/`, hacer:
```powershell
& "C:\renpy-8.2\renpy-8.2.3-sdk\renpy.exe" ".\proyects Game TL\<juego>" compile 2>&1 | Select-String "Error|line \d+" | Select-Object -First 30
```
Detecta typos de indentación o bloques vacíos en `game/*.rpy` (ej. BD tenía
`scene X with fade :` sin contenido + `show grain_overlay_3:` sin propiedad).
Fix antes de Fase 1 — si no, la compilación final fallará con errores no
relacionados con la traducción y dará impresión de que el MT está roto.

**Caso masivo `show/scene/hide ... at <transform>:` con bloque vacío** —
artefacto típico de unrpyc decompilando Ren'Py 8.x: añade `:` espurio cuando
el original era inline (`show X at Y` sin bloque). Si compile devuelve
miles de errores `expects a non-empty block` con este patrón, NO editar a
mano. Usar [tools/tl/fix_empty_blocks.py](../tools/tl/fix_empty_blocks.py):
```powershell
python tools\tl\fix_empty_blocks.py "<juego>\game" --dry   # preview
python tools\tl\fix_empty_blocks.py "<juego>\game"          # apply
```
Quita `:` final cuando la siguiente línea no-vacía no está más indentada.
Caso real: Maeves Academy → 7645 líneas en 52 archivos, compile limpio tras fix.

**0.4.2 Detectar `.rpa` con `tl/<lang>/` embebido (TRAMPA CRÍTICA).** Algunos
juegos comerciales empacan una traducción oficial dentro del .rpa (incluso
si también está descomprimida en disco). Ren'Py la carga **junto a** la del
filesystem → `Exception: A translation for "..." already exists`.
```powershell
python -c "import pickle, zlib; f=open(r'<juego>\game\<archivo>.rpa','rb'); h=f.readline().decode(); off=int(h.split()[1],16); f.seek(off); idx=pickle.loads(zlib.decompress(f.read())); print([k for k in idx if k.startswith('tl/')])"
```
Si devuelve entradas `tl/<lang>/`: usar `tools/tl/strip_rpa_entries.py` para
reescribir el índice del .rpa quitándolas (operación in-place, deja backup
`.prestrip.bak`):
```powershell
python tools\tl\strip_rpa_entries.py "<juego>\game\content.rpa" "tl/Spanish/"
```
No hacerlo provoca que la compilación falle en Fase 7 con duplicados que
no aparecen al inspeccionar los `.rpy` en disco (caso BD: 34 entradas duplicadas).

**0.5 Detectar traducción Spanish preexistente.**
```powershell
Test-Path "proyects Game TL/<NombreJuego>/game/tl/Spanish"
Test-Path "proyects Game TL/<NombreJuego>/game/tl/spanish"
```
Algunos juegos vienen con traducción humana parcial (caso **Broken Dreams**:
2670 líneas humanas de 2022 dentro de `tl/Spanish/`). Hay que **preservarlas**.
La fase 1 las respeta automáticamente; el riesgo es regenerarlas después con MT.

> **Atención al case del idioma**: Ren'Py distingue `spanish` vs `Spanish` —
> el header del archivo (`translate Spanish foo:`) debe coincidir con el valor
> pasado a `Language("Spanish")` en `screens.rpy`. Si el juego ya traía
> traducción con `Spanish` (capital), usar `Spanish` en todo el flujo. Los
> scripts del pipeline son case-insensitive desde 2026-04-25.

### Fase 1 — Generar plantilla de traducción

```powershell
cd "proyects Game TL/<NombreJuego>"
& "C:\renpy-8.2\renpy-8.2.3-sdk\renpy.exe" . translate spanish    # o "Spanish"
```

**Importante**: si ya existía `tl/<lang>/`, Ren'Py **solo añade entradas
faltantes** y no toca las existentes. Los nuevos targets se rellenan con copia
del source.

### Fase 1.1 — Vaciar mirrors (target == source)

`renpy.exe . translate <lang>` rellena los nuevos targets con **copia del
source**, no con string vacío. `translate.py` por diseño solo procesa targets
vacíos (para no sobrescribir trabajo humano). Hay que vaciar los mirrors
antes del MT para que entren en pipeline:

```powershell
python tools\tl\clear_mirror_targets.py --all `
    "proyects Game TL\<NombreJuego>\game\tl\spanish"
```

Crea backup `.mirror-bak` por archivo. Idempotente: re-ejecutar es seguro.
Solo vacía bloques con `target == source`; preserva traducciones humanas.

### Fase 1.5 — Análisis y override de fuentes

**Crítico hacerlo ANTES de traducir.** Si una fuente no soporta tildes/ñ/¿¡,
los strings traducidos saldrán como tofu (□□□) o se substituirán inline,
degradando la estética.

**1.5.1 Inventario de fuentes**: revisar `game/fonts/` y `gui.rpy` para
encontrar todas las `.ttf/.otf` que el juego usa. Identificar para qué
personaje o contexto cada una.

**1.5.2 Escaneo de cobertura** con `tools/tl/check_fonts.py`:
```powershell
python tools\tl\check_fonts.py "proyects Game TL\<juego>\game\fonts"
```
Reporta para cada fuente si los caracteres ES (`á é í ó ú ñ ¿ ¡ Á É Í Ó Ú Ñ`)
están en su cmap.

**1.5.3 Validación visual** con `render_textbox_v2.py`: renderiza muestras
EN vs ES a tamaño exacto del textbox del juego (consultar `gui.rpy` para
`text_size`, `dialogue_width`, `textbox_height`, `dialogue_ypos`). Comparar
5 longitudes (corta, media, larga, 2 líneas, 3 líneas).

**1.5.4 Reemplazo selectivo**: solo reemplazar las fuentes que fallan.
Ren'Py soporta override por idioma colocando la fuente con el mismo nombre
en `game/fonts/tl/<lang>/`:

```powershell
# Si "MyFont.ttf" falla, descargar reemplazo (preferir Google Fonts OFL)
Copy-Item tools\font_candidates\Replacement.ttf `
          "proyects Game TL\<juego>\game\fonts\tl\spanish\MyFont.ttf"
```

Criterios para escoger reemplazo: (1) cobertura ES completa, (2) estética
similar al original, (3) licencia libre (OFL/Apache).

### Fase 2 — Habilitar selector de idioma

En `game/screens.rpy`, buscar el `vbox` con `Language(...)` actions. Si está
comentado, descomentar o añadir uno activo:

```python
vbox:
    style_prefix "radio"
    label _("Language")
    textbutton "English" action Language(None)
    textbutton "Español" action Language("spanish")
    # añadir el resto de idiomas existentes en tl/
```

### Fase 3 — Construir glosario (opcional pero recomendado)

`tools/tl/tl-es-glossary.json` — solo términos invariables:
- Nombres propios de personajes, lugares, razas, organizaciones.
- Sustantivos de género fijo en español (la magia, el catalizador).
- Imperativos cortos, interjecciones específicas, siglas.
- **Compuestos completos** con su determinante incluido (ej. `Third Precept` →
  `Tercer Precepto`). Evita que el MT traduzca palabra por palabra.
- **Onomatopeyas locked** con `target == source` (ej. `Sigh`→`Sigh`,
  `Gasp`→`Gasp`). Pasan tal cual al output sin que el MT las "traduzca".

**Regla anti-error:** NUNCA poner `THE→LA`, `HIGH→ALTO`, sustantivos comunes
sueltos dependientes de artículo. El MT con contexto resuelve mejor género/número.

**Construcción asistida**: `tools/tl/build_glossary.py` escanea los .rpy
fuente y propone candidatos (palabras con mayúscula, frecuencia ≥N).
`tools/tl/apply_canon.py` carga una lista de canon (de wikia/traducciones
oficiales a otros idiomas) y vacía términos ambiguos para que vayan al MT.

Si hay traducción oficial italiana/rusa de referencia, extraer pares
nombre-EN → nombre-ES con `apply_canon.py` antes de cualquier MT call.

### Fase 4 — Traducción automática

```powershell
cd <workspace>
$env:DEEPL_API_KEY = "<key>:fx"

# Traducir archivos cortos primero (UI/system) en serie
$files = @(
  "definitions.rpy", "scene_trackers.rpy", "special_labels.rpy",
  "achievements.rpy", "screens.rpy", "common.rpy"
)
foreach ($f in $files) {
  python tools\tl\translate.py "proyects Game TL\<NombreJuego>\game\tl\spanish\$f"
}

# Después el script principal (puede tomar 5-15 min según tamaño)
python tools\tl\translate.py "proyects Game TL\<NombreJuego>\game\tl\spanish\script.rpy"
```

`translate.py` automáticamente:
- Detecta formato dialogue vs strings vs mixto.
- Crea backup `.bak` la primera vez.
- Cachea cada traducción (`.cache/deepl.json`, `.cache/gemini.json`, etc.) — re-runs son gratis.
- Reintenta con backoff y aborta limpio si fallan 8 seguidas.
- Sanitiza `\n` reales a `\\n` literal (Ren'Py necesita strings de una línea).

#### Fallback principal: OpenAI (cuando DeepL no alcanza)

Política: **OpenAI es el fallback por defecto**, no Gemini. Validado en
Maeves Academy (2026-04-26): `gpt-4.1-nano` produce traducciones con mejor
manejo de tono, género, registro y contexto narrativo que MT puro, a costo
controlado (~$0.10/1M input + $0.40/1M output → un VN largo cabe en ~$0.50–1.00).

```powershell
# .env debe contener OPENAI_API_KEY=sk-...
# Pase 1 — todos los archivos, batch 25 (default)
python -u tools\tl\_run_openai_all.py "<juego>\game\tl\spanish" *>&1 | Tee-Object logs\<juego>-openai-pass1.log

# Pase 2 — recupera fallos del pase 1 con batches más pequeños (8)
python -u tools\tl\_run_openai_small_batch.py "<juego>\game\tl\spanish" *>&1 | Tee-Object logs\<juego>-openai-pass2.log

# Pase 3 — último resort, batch 3, para strings problemáticos
python -u tools\tl\_run_openai_tiny_batch.py "<juego>\game\tl\spanish" *>&1 | Tee-Object logs\<juego>-openai-pass3.log
```

Notas:
- Budget control: `$env:OPENAI_BUDGET_USD = "1.00"` antes de empezar (default 0.50).
- Tracker en `tools/tl/.cache/openai_usage.json` (acumulativo entre runs).
- Cache por bloque en `tools/tl/.cache/openai.json` — re-runs son gratis.
- Si el budget se queda corto, los runners abortan limpiamente y se pueden
  reanudar tras subir el límite.

#### Alternativa: Gemini batch (solo si el usuario lo pide explícitamente)

Si el juego excede los ~1M chars/mes de DeepL Free (caso típico: novelas
visuales largas, p.ej. Maeves Academy con ~1M chars), usar Gemini en modo
batch:

```powershell
# .env debe contener GEMINI_API_KEY=AIzaSy...
# Default lite (15 RPM / 1000 RPD), batch de 25 strings:
python tools\tl\translate.py "<juego>\game\tl\spanish\<file>.rpy" --provider gemini

# Para diálogo delicado o calidad superior, usar 2.5-flash (250 RPD):
python tools\tl\translate.py "..." --provider gemini --gemini-model gemini-2.5-flash --batch-size 15
```

Notas:
- Si tienes `DEEPL_API_KEY` también seteada, Gemini hace fallback automático
  a DeepL cuando bloquea por contenido (`PROHIBITED_CONTENT`/`SAFETY`).
- El modelo lite es perfectamente suficiente para VN: tono natural, tildes,
  tags Ren'Py preservadas. Verificado en Maeves (2026-04-26).
- Postprocess sigue siendo necesario: Gemini deja a veces "Something"/"I"
  residuales igual que DeepL.

### Fase 5 — Post-proceso determinista

Corrige errores sistemáticos del MT (ej. `Don't` → "Don no" en español):

```powershell
python tools\tl\postprocess.py --all
```

**Cómo añadir reglas nuevas** cuando descubras patrones erróneos repetidos:
abrir `tools/tl/postprocess.py`, añadir tupla `(regex, replacement, descripcion)`
a la lista `FIXES`. Probar primero con `--dry`.

### Fase 6 — Detectar inglés residual

```powershell
python tools\tl\find_untranslated.py --all --by-word --out reporte.txt
# Revisa reporte.txt; identifica nombres propios para añadir a ALLOWLIST.
# Cuando esté limpio:
python tools\tl\find_untranslated.py --all --add-markers
```

`--add-markers` inserta `# TODO[en]: revisar palabras inglesas` después de
cada línea sospechosa. Idempotente: re-ejecutar limpia y reaplica.

**Workflow de revisión humana:** en VS Code, `Ctrl+Shift+F` con query
`TODO[en]` y scope `<game>/game/tl/spanish/`. Saltar de match en match,
arreglar, re-ejecutar `find_untranslated.py --all --add-markers` para limpiar.

### Fase 6.5 — Lint estructural

`tools/tl/lint.py` valida problemas que romperían el juego o la presentación:

| Code | Detecta |
|---|---|
| TAG | Tags `{...}` desbalanceados o desaparecidos en target |
| VAR | Variables `[...]` perdidas/extras (rompen `[Zell]`, `[mc!t]`) |
| PLACE | Placeholders `\|...\|` perdidos/extras (`\|emote_X\|`, `\|msg_Y\|`) |
| NL | Conteo de `\n` no coincide entre source y target |
| EMPTY | Target vacío con source no vacío (revisar manualmente o re-traducir) |
| UNCHANGED | Target idéntico al source (≥3 letras) — posible no-traducción |
| EXPAND | Target >150% del source (riesgo overflow en textbox) |
| TOFU | Caracteres no-ASCII sin glifo en la fuente del personaje |
| SENTINEL | Marcadores `ZT###Z`/`ZG###Z` no resueltos (bug del pipeline) |

```powershell
# Lint general
python tools\tl\lint.py "proyects Game TL\<juego>\game\tl\spanish\script.rpy"

# Con check de fuente (para detectar tofu en strings que usa pcu o similar)
python tools\tl\lint.py "<archivo>" --font "proyects Game TL\<juego>\game\fonts\tl\spanish\Stray Robotalk Regular.ttf"
```

Errores **bloqueantes** (TAG/VAR/PLACE/SENTINEL): arreglar antes de compilar.
Errores **advertencia** (EXPAND/UNCHANGED/TOFU): revisar en QA.

### Fase 7 — Compilar y validar

```powershell
cd "proyects Game TL/<NombreJuego>"
# Borrar .rpyc viejos para forzar recompile completo
Get-ChildItem "game\tl\spanish\*.rpyc" -ErrorAction SilentlyContinue | Remove-Item
& "C:\renpy-8.2\renpy-8.2.3-sdk\renpy.exe" . compile
```

Si hay errores de sintaxis, el compilador los reporta con archivo:línea. La
mayoría son por `\n` reales en strings (no debería pasar gracias al sanitizer)
o por comillas no escapadas.

```powershell
# Lanzar para probar
& "C:\renpy-8.2\renpy-8.2.3-sdk\renpy.exe" "proyects Game TL/<NombreJuego>"
```

Cambiar idioma desde Preferences → Language → Español.

---

## 3. Iteración: cuando algo falla

| Síntoma | Causa probable | Fix |
|---|---|---|
| Crash al lanzar diálogo | bug decompilado en `screen say` | Añadir defaults perdidos a parámetros |
| Strings con `\r\n` rompen compile | Sanitizer no aplicado | Re-correr `translate.py` (sanitizer integrado) |
| "Don no..." en español | DeepL malinterpreta `Don't` | `python tools\tl\postprocess.py --all` |
| Cuota DeepL agotada | 1M chars/mes (verificar en dashboard, no en API) | Cambiar a `--provider openai` (default `gpt-4.1-nano`, ver fase 4 fallback). Gemini solo si el usuario lo pide. |
| Cuota MyMemory agotada | ~10k palabras/día | Esperar 24h o pasar a DeepL/Gemini |
| Cuota Gemini agotada | 1000 RPD lite / 250 RPD flash | Esperar al reset diario (medianoche Pacífico) o cambiar de modelo. |
| Strings sin traducir tras run | bloque ya tenía contenido (skip por diseño) | Borrar el target con script y re-correr |
| Nombre propio aparece marcado como TODO | falta en ALLOWLIST de `find_untranslated.py` | Añadirlo a la lista (lowercase) |

---

## 4. Estado del arte y limitaciones conocidas

**Lo que está automatizado:**
- Extracción rpa, decompilación rpyc.
- Generación de plantillas, traducción MT, sanitización, retry, cache.
- Post-proceso de errores sistemáticos.
- Detección y marcado de inglés residual.
- Compilación.

**Lo que requiere humano (por diseño):**
- Bugs de decompilado del juego concreto (parche manual, una vez).
- Construcción inicial del glosario (canon names del juego).
- Revisión final de marcadores `TODO[en]` para nombres propios y matices.
- Casos donde DeepL no entiende contexto (raros, ~1-2% de strings).

**Trade-offs conscientes:**
- Cache es por texto exacto: cambios menores en el source = nueva consulta.
- Glosario no es contextual: un término ambiguo va al MT con la oración entera.
- `--add-markers` no edita el target, solo señala (la edición es decisión humana).

---

## 5. Para el siguiente juego: checklist mínima

```
[ ] Pre-flight: python, unrpa, fonttools, SDK Ren'Py, DEEPL_API_KEY
[ ] Backup completo del juego original
[ ] Verificar versión Ren'Py (script_version.txt) — usar SDK misma rama
[ ] Extraer .rpa si los hay (unrpa)
[ ] Detectar si faltan .rpy (decompilar SOLO si hace falta)
[ ] Lanzar juego en inglés — anotar bugs decompilado
[ ] **Compile dry-run del source EN** (renpy.exe . compile) — fix bloques vacíos / indents
[ ] **Inspeccionar .rpa: si contiene tl/<lang>/, strip_rpa_entries.py**
[ ] **Detectar tl/<lang>/ preexistente** (preservar trabajo humano)
[ ] Confirmar capitalización del idioma (spanish vs Spanish)
[ ] Generar tl/<lang> (renpy.exe . translate <lang>)
[ ] **clear_mirror_targets.py --all** (vaciar target==source)
[ ] **Análisis de fuentes** (check_fonts.py)
[ ] **Override de fuentes que fallen** (game/fonts/tl/<lang>/)
[ ] Habilitar selector idioma en screens.rpy
[ ] (Opcional) Construir glosario base con canon names + onomatopeyas + compuestos
[ ] $env:DEEPL_API_KEY = "<key>:fx"
[ ] python tools\tl\translate.py <cada .rpy de tl/<lang>>
[ ] python tools\tl\postprocess.py --all
[ ] **python tools\tl\_fix_multiline_strings.py <tl_dir>** (corrige `\n` reales)
[ ] **python tools\tl\fix_zt_sentinels.py <tl_dir>** (restaura sentinels ZT/ZG huérfanos)
[ ] python tools\tl\find_untranslated.py --all --add-markers
[ ] python tools\tl\lint.py <archivos> --font <fuente-personaje>
[ ] Revisión manual de TODO[en] y errores TAG/VAR/PLACE
[ ] Compilar (renpy.exe . compile)
[ ] Smoke test: arrancar y cambiar idioma
[ ] **QA: jugar 30-60 min, anotar overflow textbox / tofu / contexto roto**
[ ] Actualizar memory/repo/tl-project.md con quirks del juego
```

---

## 5.bis Trampas conocidas y soluciones

| Trampa | Síntoma | Solución |
|---|---|---|
| Decompilado pierde defaults de parámetros en `screen` | Crash al primer diálogo (`NameError: name 'emote' is not defined`) | Parche manual: añadir `=""` o valor por defecto. Revisar `screens.rpy` antes de traducir. |
| Selector de idioma comentado | Imposible cambiar a spanish in-game | Activar bloque `vbox` con `Language(...)` en `screens.rpy`. Respetar capitalización del idioma. |
| Strings con `\r\n` reales rompen compile | Ren'Py parser falla en strings multi-linea | `translate.py` ya sanitiza, pero si editas a mano: usar `\\n` literal. |
| Cuota agotada DeepL mitad pipeline | Run aborta con HTTP 456 | `translate.py` aborta limpio (estado guardado), reanudar con `--provider mymemory --email <e>` o esperar al mes siguiente. |
| Glosario sustantivo común rompe concordancia | "the water" → "la agua" | Quitar entrada del glosario, dejarlo al MT con contexto. |
| Fuente custom sin tildes | Tofu en pantalla solo para ese personaje | Override en `game/fonts/tl/<lang>/<mismo-nombre>.ttf` con fuente compatible. |
| `.rpyc` viejos no se actualizan | Cambios en `.rpy` no se ven en juego | Borrar `.rpyc` antes de `compile`. |
| Capitalización del idioma | Pipeline ignora archivos `translate Spanish ...` | Scripts case-insensitive desde 2026-04-25; verificar con `lib_rpy.py`. |
| Targets pre-rellenados con copia del source | `translate.py` no detecta nada que traducir | `python tools\tl\clear_mirror_targets.py --all <tl_dir>` antes del MT. |
| Traducción humana preexistente | Riesgo de sobrescribir trabajo del autor | Fase 0.5 detecta `tl/<lang>/`. `clear_mirror_targets.py` solo vacía mirrors, no traducciones reales. |
| Archivos mixtos dialogue+strings | translate.py procesaba uno solo (sniff de 4KB) | Desde 2026-04-25 detecta ambos con regex `^translate\s+spanish\s+(?!strings:)\S+:` y `^translate\s+spanish\s+strings:` independientes. |
| `{i}I texto` (pronombre I residual) | DeepL deja "I" sin traducir tras tag o al inicio | postprocess.py regla "I residual" elimina `I ` antes de minúscula española. |
| `{i}AY texto` (And mal capitalizado) | DeepL traduce "And" → "AY" en mayúsculas tras tag | Casos raros (~3 en BD), revisar manualmente con find_untranslated. |
| Concordancia de género del speaker | DeepL no sabe que `asa` es femenino → "me siento solo" | No automatizable sin context-aware MT. Revisión manual o glosario por personaje (TODO). |
| Stutter perdido (Y-You, I-i) | DeepL elimina tartamudeo al traducir | Aceptado como pérdida menor o restaurar manualmente en QA. |
| Tags namespaced traducidos `{#month}`→`{#mes}` | DeepL traduce el identificador del tag Ren'Py | Lint detecta como TAG mismatch. Fix con regex post-MT: `{#mes}`→`{#month}`, `{#mes_corto}`→`{#month_short}`, etc. (caso BD common.rpy: 27 tags). Idealmente añadir al tokenizer STAY de translate.py. |
| `[var]`→`[var` (placeholder roto) | DeepL elimina `]` final de variables Ren'Py | Lint VAR detecta. Fix manual o regex `\[(\w+)(?=[^\]\w])` → `[$1]`. |
| `.rpa` contiene `tl/<lang>/` duplicado del de disco | Compile falla con `A translation for "X" already exists` | Preflight 0.4.2: `strip_rpa_entries.py <archivo>.rpa tl/<lang>/`. |
| `tl/<lang>` contiene bloques `old` duplicados exactos | Compile falla con `A translation for "X" already exists at ...` aun sin `.rpa` duplicado | `python tools\tl\fix_duplicate_string_translations.py <tl_dir>` para dry-run y repetir con `--apply`. Conserva la primera aparicion case-sensitive y elimina bloques duplicados posteriores. Tambien quita `old ""/new ""` si aparecen duplicados. |
| Bloques `scene/show/with` con `:` pero sin contenido en source | Compile falla con `expects a non-empty block` | Preflight 0.4.1 (compile dry-run del source). Fix: quitar `:` o añadir propiedad ATL indentada (`alpha .5`). |
| Sentinels `ZT###`/`ZG###` huérfanos en target (sin Z final, ej. `ZT002Si...`, `ZG000¡No...`) | Crash ingame `'/b' closes a text tag that isn't open` o texto literal `ZT001Preferencias`. MT pegó el sentinel al token siguiente perdiendo el cierre. | **Correr siempre `tools/tl/fix_zt_sentinels.py <tl_dir>` después de postprocess.** Re-tokeniza el `# "source"` adyacente y restaura el token original. Casos donde el MT alucina un sentinel sobre source sin tokens (ej. "Something" → "ZT000Z homemade") requieren fix manual — buscar `ZT\d+\|ZG\d+` con Select-String tras el script. |
| Multi-line strings con `\n` real (LF físico dentro del string) | Compile error `Could not parse string. Perhaps you left out a " at the end of the first line.` | `tools/tl/_fix_multiline_strings.py <tl_dir>` une líneas con `\n` literal. MT a veces produce esto cuando el source contenía `\n` literal y respondió con salto de línea real. |
| Variable `[var]` perdida dentro de `{i}...{/i}` | Lint VAR detecta. En juego sale `{i} bla{/i}` o `{i}{/i}` vacío. | Fix manual línea por línea (caso típico: `[player_name]` se pierde al traducir). |
| `archive.rpa` con fuentes empaquetadas | `check_fonts.py` no encuentra `.ttf/.otf` en `game/fonts/` | `tools/tl/extract_fonts_from_rpa.py <archive.rpa>` extrae .ttf/.otf usando el índice pickle. Probado con Tropicali (4.14 GB rpa, 3 fuentes recuperadas). |

---

## 6. Archivos clave del repositorio

| Archivo | Descripción |
|---|---|
| [tools/tl/translate.py](../tools/tl/translate.py) | Orquestador MT (DeepL + MyMemory) |
| [tools/tl/lib_rpy.py](../tools/tl/lib_rpy.py) | Parser .rpy (dialogue + strings, case-insensitive lang) |
| [tools/tl/clear_mirror_targets.py](../tools/tl/clear_mirror_targets.py) | Vacía targets que son copia del source |
| [tools/tl/check_fonts.py](../tools/tl/check_fonts.py) | Audita cobertura de glifos ES en .ttf/.otf |
| [tools/tl/postprocess.py](../tools/tl/postprocess.py) | Reglas correctivas determinísticas |
| [tools/tl/_fix_multiline_strings.py](../tools/tl/_fix_multiline_strings.py) | Une líneas con `\n` real → `\n` literal |
| [tools/tl/fix_zt_sentinels.py](../tools/tl/fix_zt_sentinels.py) | Restaura sentinels `ZT###`/`ZG###` huérfanos re-tokenizando el source |
| [tools/tl/extract_fonts_from_rpa.py](../tools/tl/extract_fonts_from_rpa.py) | Extrae fuentes .ttf/.otf de un archive.rpa |
| [tools/tl/find_untranslated.py](../tools/tl/find_untranslated.py) | Detector de inglés residual |
| [tools/tl/lint.py](../tools/tl/lint.py) | Validador de tags/vars/expansión |
| [tools/tl/apply_canon.py](../tools/tl/apply_canon.py) | Pre-llenado glosario desde canon |
| [tools/tl/strip_rpa_entries.py](../tools/tl/strip_rpa_entries.py) | Reescribe índice .rpa quitando entradas por prefijo (in-place, con backup) |
| [tools/tl/tl-es-glossary.json](../tools/tl/tl-es-glossary.json) | Glosario base (extender por juego) |
| [memory/tl-es-style.md](tl-es-style.md) | Guía de estilo ES |
