# Setup — Entorno de Traducción de Juegos

Instrucciones para replicar el entorno completo en una máquina nueva (Windows).

---

## 1. Clonar el repo

```powershell
git clone https://github.com/KoichiFumikatsu/tlgames.git C:\xampp\htdocs\tl
cd C:\xampp\htdocs\tl
```

---

## 2. Python

Instalar Python 3.12 desde https://www.python.org/downloads/  
Durante la instalación: marcar **"Add Python to PATH"**.

Verificar:
```powershell
python --version   # 3.12.x
pip --version
```

### Paquetes pip requeridos

```powershell
pip install openai python-dotenv openpyxl unrpa UnityPy rubymarshal
```

| Paquete | Para qué |
|---|---|
| `openai` | MT con gpt-4.1-nano en todos los pipelines |
| `python-dotenv` | Cargar `.env.local` / `.env` en scripts |
| `openpyxl` | Leer XLSX (SystemText.dat Unity/EPPlus, extracción) |
| `unrpa` | Desempaquetar archivos `.rpa` de Ren'Py |
| `UnityPy` | Inspección de assets Unity (level files, bundles) |
| `rubymarshal` | Leer/escribir archivos `.rxdata` de RPG Maker XP |

---

## 3. Variables de entorno — `.env.local`

Copiar `.env.local` a `.env` (o usar directamente `.env.local`):

```powershell
Copy-Item .env.local .env
```

Contenido esperado:
```
DEEPL_API_KEY=<tu clave DeepL>
GEMINI_API_KEY=<tu clave Gemini>
OPENAI_API_KEY=<tu clave OpenAI>
OPENAI_BUDGET_USD=1.50
```

---

## 4. Ren'Py SDK

Descargar: https://www.renpy.org/dl/8.2.3/renpy-8.2.3-sdk.zip  
Descomprimir en `C:\renpy-8.2\renpy-8.2.3-sdk\`

```powershell
mkdir C:\renpy-8.2
Invoke-WebRequest https://www.renpy.org/dl/8.2.3/renpy-8.2.3-sdk.zip -OutFile C:\renpy-8.2\renpy-sdk.zip
Expand-Archive C:\renpy-8.2\renpy-sdk.zip -DestinationPath C:\renpy-8.2\
```

---

## 5. Herramientas portables (`tools/`)

Deben descargarse manualmente y colocarse en las rutas indicadas. Los binarios no están en el repo por tamaño.

### UABEA v8
- **Ruta:** `tools/UABEA/` (ejecutable: `UABEAvalonia.exe`)
- **Descarga:** https://github.com/nesrak1/UABEA/releases/tag/v8-dev2
- **Para qué:** editar y reimportar Unity assets (`.assets`, bundles)

### AssetRipper 1.3.12
- **Ruta:** `tools/AssetRipper/` (ejecutable: `AssetRipper.GUI.Free.exe`)
- **Descarga:** https://github.com/AssetRipper/AssetRipper/releases/tag/1.3.12
- **Para qué:** inspección/extracción de builds Unity completos

### dnSpyEx 6.5.1
- **Ruta:** `tools/dnSpyEx/` (ejecutable: `dnSpy.exe`)
- **Descarga:** https://github.com/dnSpyEx/dnSpy/releases/tag/v6.5.1
- **Para qué:** inspeccionar y editar código .NET/Mono (Assembly-CSharp.dll)

### BepInEx 5.4.23.5 (win_x64)
- **Ruta:** `tools/BepInEx/` (payload: `BepInEx/`, `doorstop_config.ini`, `winhttp.dll`)
- **Descarga:** https://github.com/BepInEx/BepInEx/releases/tag/v5.4.23.5
  → Descargar `BepInEx_win_x64_5.4.23.5.zip`
- **Para qué:** mod loader para Unity Mono — base para XUnity.AutoTranslator

### BepInEx 5.4.23.5 (win_x86)
- **Ruta:** `tools/BepInEx-x86/`
- **Descarga:** mismo release → `BepInEx_win_x86_5.4.23.5.zip`
- **Para qué:** idem para juegos Unity de 32 bits

### XUnity.AutoTranslator 5.6.1 (BepInEx variant)
- **Ruta:** `tools/XUnity.AutoTranslator/`
- **Descarga:** https://github.com/bbepis/XUnity.AutoTranslator/releases/tag/v5.6.1
  → Descargar `XUnity.AutoTranslator-BepInEx-5.6.1.zip`
- **Para qué:** traducción automática en runtime para Unity; exporta traducciones estáticas

### unrpyc v2.0.4
- **Ruta:** `tools/unrpyc/` (archivos: `un.rpyc`, `un.rpy`, `bytecode-39.rpyb`)
- **Descarga:** https://github.com/CensoredUsername/unrpyc/releases/tag/v2.0.4
- **Para qué:** decompilar archivos `.rpyc` de Ren'Py a `.rpy`

---

## 6. Claude Code — configuración

El directorio `.claude/` del repo contiene:
- `settings.json` — hook `Stop` que pide revisar memoria al cerrar sesión
- `settings.local.json` — permisos de herramientas aprobados

Están en la raíz del repo (`C:\xampp\htdocs\tl\.claude\`). Claude Code los detecta automáticamente al abrir el proyecto.

---

## 7. VS Code

Extensión recomendada:
```powershell
code --install-extension LuqueDaniel.languague-renpy
```

---

## 8. Estructura de carpetas requeridas (crear si no existen)

```powershell
mkdir "proyects Game TL\Unity"
mkdir "proyects Game TL\RPGMaker"
mkdir "proyects Game TL\GameMaker"
mkdir backups\Unity
mkdir backups\RPGMaker
mkdir backups\GameMaker
mkdir logs\unity
mkdir logs\rpgmaker
mkdir logs\gamemaker
mkdir _tl_work
```

Los juegos van en `proyects Game TL/<Engine>/<NombreJuego>/`.  
Los backups van en `backups/<Engine>/<NombreJuego>-original-<fecha>/`.

---

## 9. Verificación rápida

```powershell
python -c "import openai, dotenv, openpyxl, UnityPy; print('Paquetes OK')"
python --version
git --version
```

## Despliegue en koilinux

El servidor web usa Python 3.12 y solo stdlib. Conserva las dependencias y las
claves que ya utiliza el pipeline de traducción. Ejecutar los comandos siguientes
en koilinux como el usuario `koilinux`, desde `~/projects/tlgames`.

Configurar estas variables en el `.env` del repositorio, conservando las existentes:

```dotenv
TLGAMES_BASE=/tlgames
DASH_USER=<usuario>
DASH_PASS=<contraseña larga y única>
SESSION_SECRET=<secreto aleatorio independiente>
INTERNAL_TOKEN=<token aleatorio para servicios internos>
TLGAMES_ENTRADA=/home/koilinux/Documents/games-tl/entrada
```

`TLGAMES_BASE` es vacío por defecto; acepta `/tlgames` y `/tlgames/`. Funnel
preserva el prefijo y el servidor lo recorta antes de resolver cada ruta. Las rutas
sin prefijo continúan disponibles para los clientes internos, con autenticación.
La salida se toma de `output_dir` en `tools/pipeline_settings.json`; en koilinux
debe seguir siendo `/home/koilinux/Documents/games-tl/salida`.

`DASH_USER`, `DASH_PASS` y `SESSION_SECRET` son obligatorios al arrancar. Generar
`SESSION_SECRET` e `INTERNAL_TOKEN` con al menos 32 bytes aleatorios cada uno y
guardarlos directamente en `.env`, sin incluirlos en comandos, logs ni Git. Los
valores `<...>` del ejemplo son marcadores que deben reemplazarse. Proteger `.env`
con permisos `600`. No se confía en ninguna IP de origen: Funnel llega por localhost.

El formulario `/tlgames/login` crea una cookie HMAC válida durante 12 horas, con
`HttpOnly`, `Secure`, `SameSite=Strict` y alcance `/tlgames`. Usar HTTPS para el
login; para pruebas por HTTP local usar Basic Auth o `X-Internal-Token`.
Cambiar `SESSION_SECRET` invalida las sesiones. Solo `/login` y `/health` son públicos.
El estado de salud publica cuotas agregadas, presupuesto y disponibilidad de QA.

```bash
mkdir -p /home/koilinux/Documents/games-tl/entrada /home/koilinux/Documents/games-tl/salida
chmod 600 .env
systemctl --user restart tlgames-pipeline
systemctl --user status tlgames-pipeline --no-pager
curl --fail http://127.0.0.1:8766/tlgames/health
curl -i http://127.0.0.1:8766/tlgames/jobs
```

La última petición debe responder `401`. El servicio existente debe ejecutar
`tools/pipeline_server.py --host 127.0.0.1 --port 8766` desde el repositorio. El
servidor carga `.env` al iniciar; variables ya presentes en el entorno systemd
tienen prioridad. Si el unit contiene valores antiguos, actualizarlos antes de
reiniciar. Si se modifica el unit, ejecutar también `systemctl --user daemon-reload`.

Actualizar los clientes internos antes de publicar: todas sus llamadas a jobs,
pipeline, detect y settings deben enviar `X-Internal-Token` con el mismo valor
que `INTERNAL_TOKEN`, o Basic Auth. En particular, el cliente `_PipelineHTTP` de
briefing actualmente hace peticiones sin autenticación y requiere ese ajuste en
su propio repositorio. No es necesario cambiar sus URLs sin prefijo.

Tras verificar el servicio y la autenticación, publicar:

```bash
sudo tailscale funnel --bg --set-path=/tlgames 8766
```

Abrir `https://koilinux.tail7024a4.ts.net/tlgames/`: iniciar sesión, subir un ZIP,
elegir **Traducir** en Entrada y descargar el paquete desde Salida cuando termine.
Comprobar desde una sesión privada que `/tlgames/jobs` devuelve `401` y que
`/tlgames/health` sigue accesible. QA escucha en `127.0.0.1:8765` por defecto;
`tools/qa_server.py --host DIRECCION` permite elegir otro bind. No exponer QA ni
el version tracker mediante Funnel.

La subida usa el ZIP como cuerpo binario (`Content-Type: application/zip`), con
`Content-Length` y `X-Nombre` codificado como URL; también acepta `filename` en
`Content-Disposition`. No usa multipart ni mantiene el cuerpo completo en RAM.
Se requieren espacio para el ZIP y su contenido descomprimido. Se extrae en una
carpeta temporal de Entrada y se mueve al destino únicamente al completar la
validación. Si hay una sola carpeta raíz, se utiliza su nombre saneado y su
contenido como juego; de lo contrario, se usa el nombre de la cabecera sin `.zip`.
Un nombre existente responde `409`, sin sobrescribirlo. Se rechazan rutas
absolutas, componentes `..` y enlaces dentro del ZIP. Borrar exige confirmación
en la interfaz y el servidor rechaza juegos con traducciones en curso.

El empaquetado escribe primero un archivo `.zip.part` y lo renombra al completar
el ZIP. Los temporales no aparecen en Salida ni se pueden descargar. Si una
retraducción falla al empaquetar, se conserva el paquete completo anterior.

| Endpoint autenticado | Resultado |
|---|---|
| `POST /upload` | `201 {nombre, size, zip_size, path}`; tamaños en bytes |
| `GET /entrada` | `{entrada: [{nombre, path, paquete, paquetes, job}]}` |
| `POST /entrada/borrar` | Recibe `{nombre}`; borra solo esa carpeta de Entrada |
| `GET /salida` | `{salida: [{nombre, size, mtime, download}]}`; fecha Unix |
| `GET /salida/<archivo>` | ZIP por streaming, limitado a la carpeta de salida |
| `GET /pipeline/<job_id>/diagnostico` | Informe de diagnóstico como texto |

Las rutas anteriores también aceptan el prefijo `/tlgames`. Se conservan los
endpoints de pipeline, detección, trabajos, eventos y settings.

Pruebas locales sin traducciones reales ni llamadas a proveedores:

```bash
python -m pip install pytest
python -m pytest -q
```

`pytest` es una dependencia exclusiva de pruebas. La suite usa HTTP en localhost,
carpetas temporales y proveedores simulados; no modifica la configuración real.

## Calidad de traducción Ren'Py

Tres piezas, todas encendidas por defecto en `tools/pipeline_settings.json`:

- **Glosario por juego** (`renpy.game_glossary`): en la etapa `setup`,
  `tools/tl/game_glossary.py` escanea los `Character("Nombre")` de los `.rpy` del
  juego (fuera de `tl/`) y escribe `<juego>/tl-es-glossary.json` con los nombres
  protegidos (`target == source`). `translate.py` lo recibe por `TL_GLOSSARY`
  (o `--glossary`); sin esa variable usa el glosario global del repo, como antes.
  Rótulos genéricos (`Mom`, `???`, `Narrator`…) se dejan traducir.
- **Guía de estilo** (`tools/tl/style_es.py`): tuteo, nombres intactos,
  onomatopeyas, mayúsculas enfáticas, sin calcos. Se anexa a los system prompts
  de OpenAI/Gemini; DeepL recibe `formality=prefer_less`.
- **Corrección automática post-QA** (`qa.autofix`): el pipeline manda
  `{"dir": ..., "fix": true}` a `qa_server`. Cada aviso `[N] TIPO: malo → bueno`
  del LLM se aplica al `new "..."` del par N sólo si el fragmento aparece una vez
  y el resultado conserva tags `{}`/`[]`/`|x|` y los `\n`. El reporte marca los
  avisos aplicados con `✔ corregido` y el job guarda `qa_fixed`.

## Motores: Unity genérico y RPG Maker

- **Unity sin sistema JSON nativo** ya no queda en `unsupported`: `tools/tl/unity_xunity.py`
  detecta el build (Mono/IL2CPP, x64/x86 por cabecera PE), descarga a `unity.xunity_cache_dir`
  (default `~/apps/unity-tl`) BepInEx 5.4.23.3 y XUnity.AutoTranslator 5.4.5, los extrae en la
  raíz del juego, escribe `BepInEx/config/AutoTranslatorConfig.ini` (`Language=es`,
  `FromLanguage=en`, `Endpoint=` según `unity.xunity_endpoint`, default `GoogleTranslateV2`
  para lo que no se pre-tradujo) y, si `unity.xunity_pretranslate`, extrae los textos
  estáticos de `level*`/`*.assets`/`resources` y los traduce (DeepL → OpenAI) a
  `BepInEx/Translation/es/Text/_static.txt`. Sólo builds Mono; IL2CPP necesita BepInEx 6 y
  queda marcado como no soportado con el motivo. El paquete de salida incluye BepInEx.
- **RPG Maker MV/MZ**: además de base de datos, eventos y mapas, ahora se traducen los
  `terms` de `System.json` (basic/commands/params/messages). Los prompts OpenAI de Unity y
  RPG Maker llevan la misma guía de estilo que Ren'Py (`tools/tl/style_es.py`).

## Groq como tercer proveedor (gratis)

`translate.py --provider groq` usa el endpoint compatible con OpenAI de Groq con
`openai/gpt-oss-120b` (env `GROQ_MODEL_TL`), sin costo. Límites del free tier
(cabeceras `x-ratelimit-*`, 2026-09-17): 1000 requests/día y 8.000 tokens/minuto
por modelo, compartidos con el briefing. El cliente respeta una ventana móvil de
7.000 tokens/min y los `Retry-After`; un 429 diario aborta el archivo (`[ABORT]`)
y el pipeline pasa al siguiente proveedor. Cadena automática del pipeline Ren'Py:
**DeepL → Groq → OpenAI** (si el preflight elige OpenAI por falta de cupo DeepL,
Groq va antes por ser gratis). Un juego de 500k chars por Groq tarda ~25 min como
mínimo por el límite de tokens.

## Port Android (Ren'Py) por inyección en el APK oficial

Si el juego Ren'Py tiene versión Android, se sube su `.apk` oficial al mismo dropzone del taller
(o `POST /upload` con `Content-Type: application/vnd.android.package-archive`), queda en
`entrada/<nombre>.apk` y se vincula a la carpeta del juego con «Vincular APK oficial…»
(`POST /entrada/apk {nombre, apk}` → `entrada/<juego>.apk`). Al empaquetar, `tools/tl/apk_patch.py`:
compila `game/tl/<lang>` con el SDK, copia el APK sin la firma vieja ni traducción previa, agrega
`assets/x-game/x-tl/x-<lang>/…` y `x-_force_<lang>.rpyc` sin comprimir (así los lee `renpy/loader.py`
en Android), alinea con `zipalign` y firma v1+v2+v3 con `apksigner` (build-tools r34 en
`~/apps/android-tl/build-tools`; `uber-apk-signer.jar` como alternativa) usando el keystore propio
`~/apps/android-tl/tlgames.jks` (clave en `keystore.pass`, ambos 600; se crean una sola vez —
**hacerles backup**: con otra llave las actualizaciones no instalan encima). Sale
`salida/<juego>[-vX]-spanish.apk`; el jugador debe desinstalar el original. Ren'Py 7 (Python 2):
se inyectan `.rpy` sin compilar y el job avisa. Settings: `android.enabled`. Nunca es fatal para el job.
