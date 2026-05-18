# Brief — Traduccion de Juegos Unity

Uso personal. Objetivo: localizar, extraer, traducir y reinyectar texto de juegos Unity con el minimo riesgo para el build original.

## Principio base

Unity no tiene un flujo unico como Ren'Py. Antes de traducir hay que identificar donde vive el texto:

- Archivos sueltos en `StreamingAssets/` (`.json`, `.csv`, `.xml`, `.txt`, `.bytes`).
- **Archivos `.dat` o de extension arbitraria que son XLSX disfrazados** — verificar cabecera `PK` (ZIP). Si `Managed/` contiene `EPPlus.dll`, el juego lee Excel en runtime. Ver caso XLSX-como-DAT en playbook.
- TextAssets dentro de `.assets`, `.resource`, bundles o Addressables.
- StringTables del paquete Unity Localization.
- Texto hardcodeado en codigo C# (`Assembly-CSharp.dll`) si el build es Mono.
- **Strings serializados en level files** (`level0`, `level1`, etc.) — frecuente para opciones de UI/selector de idioma. No siempre estan en el DLL; buscar con `grep` binario antes de abrir dnSpy.
- Texto generado por UI/TMP o plugins.
- Texto quemado en imagenes/texturas.

## Prioridad de enfoques

1. **Inspeccion no invasiva**: revisar estructura del juego y hacer backup.
2. **Archivos editables directos**: traducir JSON/CSV/XML/TXT si existen.
3. **XUnity.AutoTranslator**: MVP rapido para validar render de caracteres ES y detectar textos runtime.
4. **Extraccion de assets**: AssetRipper/UABEA para TextAssets, StringTables, TMP fonts o bundles.
5. **Parche de codigo Mono**: dnSpyEx solo si el texto esta hardcodeado y no hay otra via.

## Bloqueantes comunes

- Build IL2CPP: mas dificil que Mono; evitar parche de codigo salvo caso necesario.
- Addressables: los textos pueden estar en bundles bajo `StreamingAssets/aa/`.
- TMP fonts sin glifos ES: acentos, `ñ`, `¿`, `¡` pueden salir como tofu.
- Texto en texturas: requiere editar imagen y reimportar.
- Assets comprimidos/encriptados: evaluar caso por caso.

## Salida esperada por juego

Cada proyecto Unity debe dejar:

- Backup completo en `backups/Unity/<Juego>-original/`.
- Carpeta de trabajo en `proyects Game TL/Unity/<Juego>/`.
- Logs en `logs/unity/<juego>-*.log`.
- Notas tecnicas del juego si aparece una trampa nueva, registradas en `memory/decisions.md` o en este brief si aplica a Unity en general.
