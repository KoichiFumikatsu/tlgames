# Brief — Traducción Personal de Juegos
> Uso personal. No distribución pública (por ahora).  
> OS: Windows. Python: pendiente de instalar.

---

## Objetivo

Traducir al español dos juegos para consumo propio:
- Un juego hecho en **Ren'Py**
- Un juego hecho en **Unity**

El proceso es exploratorio: se evalúa la viabilidad técnica y se establece un flujo replicable para futuros juegos.

---

## Track 1 — Ren'Py

### Cómo funciona
Ren'Py tiene soporte nativo de i18n. Los strings se extraen a una carpeta `game/tl/<idioma>/` sin tocar el script original. Cada bloque tiene el original comentado y el campo a traducir.

### Flujo
1. Verificar si el juego trae archivos `.rpy` (fuente) o solo `.rpyc` (compilado)
2. Si solo hay `.rpyc` → decompilar con **unrpyc**
3. Si los assets están empaquetados en `.rpa` → extraer con **rpaextract**
4. Desde el Ren'Py SDK launcher → `Generate Translations → spanish`
5. Editar los bloques en `game/tl/spanish/*.rpy`
6. Probar en el Ren'Py SDK con idioma seteado a `spanish`
7. QA: line breaks, nombres de personajes, texto que se desborde de cajas

### Posibles bloqueantes
- Assets con texto quemado en imágenes → edición manual en Photoshop/GIMP
- Strings hardcodeados fuera del sistema `tl/` → localizar manualmente en el script

---

## Track 2 — Unity

### Cómo funciona
Unity no tiene un estándar único. Hay que identificar primero dónde están los strings antes de intentar cualquier extracción.

### Árbol de decisión
```
¿Hay archivos en <juego>_Data/StreamingAssets/?
├─ Sí → revisar si son JSON/CSV/XML con texto → editar directo
└─ No → usar AssetStudio para inspeccionar qué TextAssets hay
         ├─ Accesibles → UABE para editar y reimportar
         └─ Build IL2CPP → territorio avanzado, evaluar si vale el esfuerzo
```

### Flujo
1. Inspeccionar `<juego>_Data/StreamingAssets/` — si hay JSON/CSV/XML, editar directo
2. Si no → abrir el build con **AssetStudio** y filtrar por tipo `TextAsset`
3. Exportar los TextAssets encontrados (suelen ser JSON o XML internamente)
4. Editar la traducción
5. Reimportar con **UABE** al archivo `.assets` o bundle original
6. Verificar si el build es Mono o IL2CPP (afecta si los strings están en código)
   - Mono → se puede inspeccionar con **dnSpy** si hace falta
   - IL2CPP → mucho más difícil, descartar o evaluar caso a caso

### Posibles bloqueantes
- Texto quemado en texturas UI → extraer textura, editar en Photoshop, reimportar
- Build IL2CPP con strings en código → fuera de scope inicial
- Assets protegidos o encriptados → evaluar caso a caso

---

## Setup — Instalaciones requeridas (Windows)

### Paso 0 — Python (requerido para scripts de extracción)
Descargar desde: https://www.python.org/downloads/  
Durante la instalación: **marcar "Add Python to PATH"**  
Verificar después: `python --version` en CMD

---

### Herramientas — Ren'Py Track

| Herramienta | URL | Para qué |
|---|---|---|
| Ren'Py SDK | https://renpy.org/latest.html | Launcher + generate translations + testing |
| unrpyc | https://github.com/CensoredUsername/unrpyc | Decompilar `.rpyc` si no hay `.rpy` |
| rpatool (rpaextract) | https://github.com/Shizmob/rpatool | Desempaquetar archivos `.rpa` |

### Herramientas — Unity Track

| Herramienta | URL | Para qué |
|---|---|---|
| AssetStudio | https://github.com/Perfare/AssetStudio | Inspección del build (solo lectura) |
| UABE (UABEA) | https://github.com/nesrak1/UABEA | Editar y reimportar assets |
| dnSpy | https://github.com/dnSpyEx/dnSpy | Inspeccionar código Mono si hace falta |

### Editor de texto

| Herramienta | URL | Para qué |
|---|---|---|
| VS Code | https://code.visualstudio.com | Editar `.rpy`, JSON, XML con syntax highlighting |

Extensión recomendada para VS Code: buscar `Ren'Py Language` en el marketplace.

---

## Orden de instalación sugerido

```
1. Python 3.x          → base para scripts
2. Ren'Py SDK          → necesario antes de trabajar cualquier juego Ren'Py
3. VS Code             → editor universal
4. unrpyc / rpatool    → solo si el juego Ren'Py lo requiere (verificar primero)
5. AssetStudio         → primer paso en cualquier juego Unity
6. UABE                → cuando ya se sabe qué assets hay que editar
7. dnSpy               → solo si hace falta inspeccionar código Mono
```

---

## Notas de calidad

- No usar traducción automática sin revisión — usarla como borrador, reescribir
- Mantener tono y registro por personaje de forma consistente
- Probar en el juego después de cada bloque significativo, no al final
- Documentar qué archivos se editaron y cuáles son los originales (backup siempre)

---

## Estado actual

- [ ] Python instalado
- [ ] Ren'Py SDK instalado
- [ ] VS Code instalado
- [ ] Juego Ren'Py identificado y archivos inspeccionados
- [ ] Juego Unity identificado y archivos inspeccionados
- [ ] unrpyc / rpatool (según necesidad)
- [ ] AssetStudio instalado
- [ ] UABE instalado
