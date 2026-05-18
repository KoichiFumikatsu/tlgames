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
