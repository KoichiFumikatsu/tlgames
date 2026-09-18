"""
Catálogo de fallas del pipeline: firma (regex sobre el log) → causa en español, acción automática segura (si la
hay) y qué hacer tú. Las incidencias quedan en logs/incidencias.jsonl (firma → causa → acción → resultado) para que
la memoria del sistema sea el catálogo, no una persona. El catálogo del usuario (catalogo_usuario.json, recetas
aprobadas desde el dashboard) se suma al de fábrica.

Acciones seguras (idempotentes, acotadas al venv/juego): pip_install (solo paquetes de la lista), chmod_exec (solo
rutas dentro del juego o del repo), reiniciar_qa (systemctl --user), reintentar (el pipeline vuelve a correr una vez).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
LOGS = ROOT / "logs"
INCIDENCIAS = LOGS / "incidencias.jsonl"
CATALOGO_USUARIO = Path(__file__).resolve().parent / "catalogo_usuario.json"

# Paquetes que se pueden instalar solos (módulo importado → paquete pip). Nada fuera de esta lista.
PAQUETES = {"UnityPy": "UnityPy", "rubymarshal": "rubymarshal", "openpyxl": "openpyxl", "dotenv": "python-dotenv",
            "PIL": "Pillow", "openai": "openai", "unrpa": "unrpa", "requests": "requests", "yaml": "PyYAML"}

CATALOGO: list[dict] = [
    {"id": "modulo_faltante", "patron": r"No module named '?([\w\.]+)'?", "accion": "pip_install", "reintentar": True,
     "causa": "Falta un paquete de Python en el entorno del pipeline (.venv).",
     "que_hacer": "Se instala solo si está en la lista permitida; si no, `.venv/bin/pip install <paquete>` en koilinux y relanzar."},
    {"id": "permiso", "patron": r"Permission denied:? '?([^'\n]+)", "accion": "chmod_exec", "reintentar": True,
     "causa": "Un archivo del juego o del repo no tiene permiso de ejecución/escritura.",
     "que_hacer": "Se corrige con chmod si la ruta está dentro del juego o del repo; si no, revisar dueño/permisos a mano."},
    {"id": "qa_caido", "patron": r"qa_server no (respondio|disponible)|Connection refused.*8765|8765.*Connection refused", "accion": "reiniciar_qa", "reintentar": False,
     "causa": "El servicio de QA semántico (tlgames-qa, puerto 8765) no respondió; la traducción y el paquete no dependen de él.",
     "que_hacer": "Se reinicia el servicio. Si sigue caído: `systemctl --user status tlgames-qa` y `journalctl --user -u tlgames-qa -n 50`."},
    {"id": "timeout", "patron": r"Timeout|TimeoutExpired|timed out", "accion": "reintentar", "reintentar": True,
     "causa": "Un paso tardó más del límite (red lenta, proveedor saturado o juego enorme).",
     "que_hacer": "Se reintenta una vez. Si repite, subir el timeout de esa etapa en pipeline_settings.json o partir el juego."},
    {"id": "deepl_agotado", "patron": r"\b456\b|DeepL.*agotad|Quota|cuota agotada", "accion": None, "reintentar": False,
     "causa": "Se agotaron los caracteres del mes de DeepL.",
     "que_hacer": "El pipeline sigue con Groq y luego OpenAI. Si aun así falló, revisar saldos en Briefing › Credenciales › APIs en uso."},
    {"id": "groq_diario", "patron": r"Groq 429|per day|cupo diario de Groq", "accion": None, "reintentar": False,
     "causa": "Se acabó el cupo diario de Groq (200K tokens/día por modelo, compartido con el briefing).",
     "que_hacer": "Se pasa a OpenAI automáticamente; el cupo vuelve a las 19:00 hora Colombia (00:00 UTC)."},
    {"id": "openai_presupuesto", "patron": r"Presupuesto OpenAI|\[BUDGET\]|budget_exceeded|OpenAIBudgetExceeded", "accion": None, "reintentar": False,
     "causa": "Se alcanzó el tope de gasto de OpenAI del pipeline.",
     "que_hacer": "Subir `openai.budget_usd` en tools/pipeline_settings.json (o OPENAI_BUDGET_USD) y relanzar: lo ya traducido está en caché y no se vuelve a pagar."},
    {"id": "openai_auth", "patron": r"OpenAI HTTP 40[13]|Incorrect API key|invalid_api_key", "accion": None, "reintentar": False,
     "causa": "La key de OpenAI es inválida o no tiene permisos.",
     "que_hacer": "Regenerar la key en platform.openai.com y actualizar OPENAI_API_KEY en el .env de tlgames."},
    {"id": "parse_tl", "patron": r'File "game/tl/[^"]+", line \d+', "accion": None, "reintentar": False,
     "causa": "Una línea traducida rompe la sintaxis de Ren'Py (comilla o tag sin cerrar).",
     "que_hacer": "La puerta de lint la revierte al inglés sola; si sigue fallando, la línea exacta está en el detalle de Revisión y QA."},
    {"id": "sdk_renpy", "patron": r"renpy_sdk_fallo|renpy\.sh.*(no encontrado|not found)|SDK de Ren'Py", "accion": None, "reintentar": False,
     "causa": "El SDK de Ren'Py no está o no responde.",
     "que_hacer": "Verificar RENPY_SDK en el .env (hoy ~/apps/renpy-8.3.7-sdk) y que `renpy.sh` sea ejecutable."},
    {"id": "unrpyc", "patron": r"unrpyc|decompil", "accion": None, "reintentar": False,
     "causa": "Falló la decompilación de .rpyc (versión de Ren'Py más nueva que unrpyc, o archivos protegidos).",
     "que_hacer": "Actualizar unrpyc en ~/.local/share/unrpyc; si el juego trae .rpy fuera de tl/, se puede traducir sin decompilar."},
    {"id": "disco_lleno", "patron": r"No space left on device|Errno 28", "accion": None, "reintentar": False,
     "causa": "koilinux se quedó sin espacio en disco.",
     "que_hacer": "Ver Briefing › Proyectos › Almacenamiento; borrar paquetes viejos de salida/ o backups."},
    {"id": "zip_grande", "patron": r"too_large|max_size_gb", "accion": None, "reintentar": False,
     "causa": "El juego traducido supera el tamaño máximo de paquete.",
     "que_hacer": "Subir `package.max_size_gb` o usar `package.mode=rsync_only` (queda la carpeta sin zip)."},
    {"id": "unity_il2cpp", "patron": r"IL2CPP|il2cpp", "accion": None, "reintentar": False,
     "causa": "Build Unity IL2CPP: XUnity automático solo cubre builds Mono.",
     "que_hacer": "Instalar BepInEx 6 + XUnity IL2CPP a mano (playbook Unity) o descartar el juego."},
    {"id": "estructura", "patron": r"sin carpeta \*_Data|estructura no reconocida|no soportado por pipeline", "accion": None, "reintentar": False,
     "causa": "El zip no trae el juego en la raíz (carpeta anidada) o el motor no es Ren'Py/Unity/RPG Maker.",
     "que_hacer": "Revisar que en la carpeta subida estén `game/` (Ren'Py), `*_Data/` (Unity) o `www/data` (RPG Maker) directamente."},
    {"id": "codificacion", "patron": r"UnicodeDecodeError|codec can't decode", "accion": None, "reintentar": False,
     "causa": "Un archivo del juego no está en UTF-8.",
     "que_hacer": "Convertir el archivo a UTF-8 (`iconv -f cp1252 -t utf-8`) y relanzar."},
]


def catalogo() -> list[dict]:
    extra = []
    try:
        extra = json.loads(CATALOGO_USUARIO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return CATALOGO + [e for e in extra if e.get("id") and e.get("patron")]


def analizar(texto: str) -> dict | None:
    """Primera receta cuya firma aparece en el texto (con el grupo capturado, si lo hay)."""
    for receta in catalogo():
        try:
            m = re.search(receta["patron"], texto or "", re.IGNORECASE)
        except re.error:
            continue
        if m:
            return {**receta, "captura": m.group(1) if m.groups() else "", "fragmento": m.group(0)[:160]}
    return None


# ── acciones seguras ──────────────────────────────────────────────────────────

def _pip_install(captura: str, **_) -> tuple[bool, str]:
    modulo = (captura or "").split(".")[0]
    paquete = PAQUETES.get(modulo)
    if not paquete:
        return False, f"'{modulo}' no está en la lista de paquetes instalables"
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", paquete], capture_output=True, text=True, timeout=600)
    return r.returncode == 0, (f"instalado {paquete}" if r.returncode == 0 else (r.stderr or r.stdout)[-300:])


def _chmod_exec(captura: str, game_path: Path | None = None, **_) -> tuple[bool, str]:
    ruta = Path((captura or "").strip().strip("'\""))
    permitidas = [p.resolve() for p in (game_path, ROOT) if p]
    try:
        real = ruta.resolve()
    except OSError:
        return False, "ruta inválida"
    if not ruta.exists() or not any(real == b or b in real.parents for b in permitidas):
        return False, f"{ruta} fuera del juego/repo o no existe"
    os.chmod(ruta, os.stat(ruta).st_mode | 0o755)
    return True, f"chmod 755 {ruta.name}"


def _reiniciar_qa(**_) -> tuple[bool, str]:
    r = subprocess.run(["systemctl", "--user", "restart", "tlgames-qa"], capture_output=True, text=True, timeout=60)
    return r.returncode == 0, ("tlgames-qa reiniciado" if r.returncode == 0 else (r.stderr or "")[-200:])


def _reintentar(**_) -> tuple[bool, str]:
    return True, "se reintenta el pipeline una vez"


ACCIONES = {"pip_install": _pip_install, "chmod_exec": _chmod_exec, "reiniciar_qa": _reiniciar_qa, "reintentar": _reintentar}


def aplicar(receta: dict, game_path: Path | None = None) -> tuple[bool, str]:
    fn = ACCIONES.get(receta.get("accion") or "")
    if not fn:
        return False, "sin acción automática"
    try:
        return fn(captura=receta.get("captura", ""), game_path=game_path)
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:160]}"


def registrar(job_id: str, etapa: str, receta_id: str | None, causa: str, accion: str | None, resultado: str, origen: str, fragmento: str = ""):
    LOGS.mkdir(parents=True, exist_ok=True)
    fila = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "job_id": job_id, "etapa": etapa, "receta": receta_id, "causa": causa,
            "accion": accion, "resultado": resultado, "origen": origen, "fragmento": fragmento[:200]}
    with INCIDENCIAS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(fila, ensure_ascii=False) + "\n")
    return fila


def aprobar_receta(receta: dict) -> dict:
    """Guarda en el catálogo del usuario una receta propuesta por el doctor (solo firma + textos; sin acciones nuevas)."""
    limpia = {"id": re.sub(r"[^a-z0-9_]", "_", str(receta.get("id", "")).lower())[:40] or f"receta_{int(time.time())}",
              "patron": str(receta.get("patron", ""))[:300], "causa": str(receta.get("causa", ""))[:400],
              "que_hacer": str(receta.get("que_hacer", ""))[:600], "accion": receta.get("accion") if receta.get("accion") in ACCIONES else None,
              "reintentar": bool(receta.get("reintentar")), "origen": "doctor", "aprobada": time.strftime("%Y-%m-%d")}
    re.compile(limpia["patron"])   # ValueError/re.error si la firma no es válida
    actual = []
    try:
        actual = json.loads(CATALOGO_USUARIO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    actual = [r for r in actual if r.get("id") != limpia["id"]] + [limpia]
    CATALOGO_USUARIO.write_text(json.dumps(actual, ensure_ascii=False, indent=2), encoding="utf-8")
    return limpia


def ultimas(n: int = 50) -> list[dict]:
    try:
        lineas = INCIDENCIAS.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for l in lineas[-n:]:
        try:
            out.append(json.loads(l))
        except ValueError:
            pass
    return out
