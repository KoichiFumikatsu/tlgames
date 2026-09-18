#!/usr/bin/env python3
"""
Pipeline Server para TL Games — Puerto 8766.
n8n (o cualquier cliente HTTP) envía la ruta de un juego y recibe el resultado
de la pipeline completa: detección de engine → traducción → postprocess → lint → QA semántico.

Endpoints:
  GET  /health               → {"status":"ok", "jobs":<n>}
  POST /detect               {"path":"/ruta/juego"}  → engine info
  POST /pipeline             {"path":"/ruta/juego", "name":"opt", "provider":"deepl",
                              "lang":"Spanish", "ntfy_topic":""}
                             → {"job_id":"abc12345", "status":"running"}
  GET  /pipeline/<job_id>    → {"status":"running|done|error|unsupported", "progress":[...], ...}
  GET  /jobs                 → lista de todos los jobs (últimos 50)
"""

import argparse
import json
import os
import re
import sys
import threading
import time
import uuid
import urllib.request
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from pipeline_web import PublicHandlerMixin, FILES_LOCK, _base, validate_auth_config

# Regex para parsear las líneas de progreso de translate_unity_json.py
# Ejemplo: "[42/117] YuriDialogue.json | 1523/9358 strings | 35%"
_PROG_RE = re.compile(r'\[(\d+)/(\d+)\]\s+(\S+)\s*\|\s*(\d+)/(\d+)\s+strings\s*\|\s*(\d+)%')
# Ejemplo: "  [openai] batch 25 strings | gastado $0.0423 | resta $1.4577"
_OAPI_SPENT_RE = re.compile(r'gastado \$([0-9.]+)')
# Detección de cambio a OpenAI
_TO_OPENAI_RE = re.compile(r'\[openai\]|cambiando a OpenAI')

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
TL_TOOLS = TOOLS / "tl"
LOGS = ROOT / "logs"
LOGS.mkdir(exist_ok=True)

# Cargar .env igual que los scripts de traducción
sys.path.insert(0, str(TL_TOOLS))
try:
    from _env import load_env as _load_env
    _load_env(ROOT)
except Exception:
    pass

try:
    import _settings as _s
except Exception:
    _s = None  # endpoints /settings devolveran 503; el resto sigue funcionando

try:
    import _deepl as _dl
except Exception:
    _dl = None

GAMES_TL_DIR = Path.home() / "Documents" / "games tl"

MAX_JOBS = 50
JOBS_HISTORY_FILE = LOGS / "pipeline_jobs_history.jsonl"

NTFY_URL = "https://ntfy.sh"

STAGE_ORDER = ["analyze", "setup", "translate", "lint_qa", "package"]
_DEFAULT_STAGE_WEIGHTS = {
    "renpy":    {"analyze": 5, "setup": 10, "translate": 65, "lint_qa": 15, "package": 5},
    "unity":    {"analyze": 5, "setup": 5,  "translate": 80, "lint_qa": 0,  "package": 10},
    "rpgmaker": {"analyze": 5, "setup": 5,  "translate": 75, "lint_qa": 5,  "package": 10},
}

def ntfy_send(topic: str, msg: str, title: str = "TL Games", priority: str = "default"):
    if not topic:
        return
    try:
        req = urllib.request.Request(
            f"{NTFY_URL}/{topic}",
            data=msg.encode("utf-8"),
            headers={"Title": title, "Priority": priority,
                     "Content-Type": "text/plain; charset=utf-8"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=8)
    except Exception:
        pass

_jobs: dict[str, dict] = {}
_jobs_order: list[str] = []
_jobs_lock = threading.Lock()


# ── Stage tracking ────────────────────────────────────────────────────────────

def _empty_stage() -> dict:
    return {
        "status": "pending",
        "started_at": None,
        "finished_at": None,
        "pct": 0,
        "details": {},
    }


def _empty_stages() -> dict:
    return {name: _empty_stage() for name in STAGE_ORDER}


def _stage_weights_for(engine: str) -> dict:
    if _s is not None:
        try:
            w = _s.get(f"stage_weights.{engine}", None)
            if isinstance(w, dict):
                return w
        except Exception:
            pass
    return _DEFAULT_STAGE_WEIGHTS.get(engine, _DEFAULT_STAGE_WEIGHTS["renpy"])


def _settings_get_safe(path: str, default=None):
    if _s is None:
        return default
    try:
        return _s.get(path, default)
    except Exception:
        return default


def _ntfy_topic_for(job: dict) -> str:
    # body explícito gana sobre settings
    t = (job or {}).get("ntfy_topic")
    if t:
        return t
    return _settings_get_safe("ntfy_topic", os.environ.get("NTFY_TOPIC", ""))


class StageTracker:
    """Maneja stages, current_stage y overall_pct ponderado en job.
    Pesos por engine desde settings; etapas skipped reasignan puntos a translate."""

    def __init__(self, job: dict, engine: str):
        self.job = job
        self.engine = engine
        if not isinstance(job.get("stages"), dict):
            job["stages"] = _empty_stages()
        if not isinstance(job.get("events"), list):
            job["events"] = []
        if "current_stage" not in job:
            job["current_stage"] = None
        if "overall_pct" not in job:
            job["overall_pct"] = 0

    def _effective_weights(self) -> dict:
        base = dict(_stage_weights_for(self.engine))
        stages = self.job["stages"]
        skipped_total = 0
        for name in STAGE_ORDER:
            if stages.get(name, {}).get("status") == "skipped":
                skipped_total += base.get(name, 0)
                base[name] = 0
        if skipped_total > 0 and base.get("translate", 0) > 0:
            base["translate"] += skipped_total
        return base

    def _recalc_overall(self):
        weights = self._effective_weights()
        total_w = sum(weights.values()) or 1
        acc = 0.0
        stages = self.job["stages"]
        for name, w in weights.items():
            if w <= 0:
                continue
            st = stages.get(name, {})
            status = st.get("status", "pending")
            if status in ("done", "skipped"):
                pct = 100
            elif status in ("running", "error"):
                pct = int(st.get("pct", 0))
            else:
                pct = 0
            acc += (w * pct) / total_w
        self.job["overall_pct"] = int(round(acc))

    def start(self, name: str, details: dict | None = None):
        st = self.job["stages"].setdefault(name, _empty_stage())
        st["status"] = "running"
        st["started_at"] = time.time()
        if details:
            st["details"].update(details)
        self.job["current_stage"] = name
        self._recalc_overall()
        emit_event(self.job, name, "start", details=details or {})

    def set_pct(self, name: str, pct: int, **extra):
        st = self.job["stages"].setdefault(name, _empty_stage())
        new_pct = max(0, min(100, int(pct)))
        prev_overall = self.job.get("overall_pct", 0)
        st["pct"] = new_pct
        if extra:
            st["details"].update(extra)
        self._recalc_overall()
        cur_overall = self.job.get("overall_pct", 0)
        # ntfy cada N% de cambio en overall (segun setting)
        step = int(_settings_get_safe("ntfy.progress_every_pct", 10) or 0)
        if step > 0 and (cur_overall // step) > (prev_overall // step):
            emit_event(self.job, name, "progress", overall_pct=cur_overall, stage_pct=new_pct)

    def end(self, name: str, status: str = "done", details: dict | None = None):
        st = self.job["stages"].setdefault(name, _empty_stage())
        st["status"] = status
        st["finished_at"] = time.time()
        if status in ("done", "skipped"):
            st["pct"] = 100
        if details:
            st["details"].update(details)
        self._recalc_overall()
        emit_event(self.job, name, "end", status=status, details=details or {})

    def skip(self, name: str, reason: str):
        st = self.job["stages"].setdefault(name, _empty_stage())
        st["status"] = "skipped"
        st["started_at"] = st["started_at"] or time.time()
        st["finished_at"] = time.time()
        st["pct"] = 100
        st["details"]["skipped_reason"] = reason
        self._recalc_overall()
        emit_event(self.job, name, "skip", reason=reason)


def emit_event(job: dict, stage: str, event: str, **extra):
    """Persiste evento estructurado en job['events'] y dispara ntfy segun settings.
    Mantiene log humano en job['progress'] para backward compat con dashboard viejo."""
    ts = time.time()
    rec = {"ts": ts, "stage": stage, "event": event}
    rec.update(extra)
    job.setdefault("events", []).append(rec)

    # Linea humana en progress[]
    label = {
        "start":    f"[STAGE] {stage} START",
        "end":      f"[STAGE] {stage} END ({extra.get('status', 'done')})",
        "skip":     f"[STAGE] {stage} SKIP ({extra.get('reason', '')})",
        "progress": f"[STAGE] {stage} {extra.get('overall_pct', 0)}%",
        "error":    f"[STAGE] {stage} ERROR: {extra.get('message', '')}",
        "warn":     f"[STAGE] {stage} WARN: {extra.get('message', '')}",
        "provider_switch": f"[PROVIDER] {extra.get('from', '?')} -> {extra.get('to', '?')} ({extra.get('reason', '')})",
    }.get(event, f"[STAGE] {stage} {event}")
    job.setdefault("progress", []).append(label)

    # Decidir ntfy
    if not _settings_get_safe("ntfy.stage_events", True) and event in ("start", "end", "skip"):
        return
    topic = _ntfy_topic_for(job)
    if not topic:
        return
    game_name = job.get("game_name", "")
    title = f"TL {game_name} - {stage} {event}"
    priority = "default"

    if event == "start" and _settings_get_safe("ntfy.stage_events", True):
        ntfy_send(topic, f"Etapa: {stage}", title=title, priority=priority)
    elif event == "end" and _settings_get_safe("ntfy.stage_events", True):
        st = extra.get("status", "done")
        det = extra.get("details") or {}
        body_lines = [f"Etapa: {stage} ({st})"]
        for k, v in (det.items() if isinstance(det, dict) else []):
            body_lines.append(f"{k}: {v}")
        prio = "high" if st in ("error",) else priority
        ntfy_send(topic, "\n".join(body_lines), title=title, priority=prio)
    elif event == "skip" and _settings_get_safe("ntfy.stage_events", True):
        ntfy_send(topic, f"Etapa {stage} omitida: {extra.get('reason', '')}", title=title)
    elif event == "progress":
        ntfy_send(topic, f"Progreso global: {extra.get('overall_pct', 0)}%  |  {stage}: {extra.get('stage_pct', 0)}%",
                  title=f"TL {game_name} - {extra.get('overall_pct', 0)}%")
    elif event == "provider_switch" and _settings_get_safe("ntfy.provider_switch", True):
        ntfy_send(topic,
                  f"Provider cambia: {extra.get('from', '?')} -> {extra.get('to', '?')}\nRazon: {extra.get('reason', '')}",
                  title=f"TL {game_name} - Provider switch", priority="high")
    elif event == "error" and _settings_get_safe("ntfy.errors", True):
        ntfy_send(topic, extra.get("message", "Error"), title=f"TL {game_name} - ERROR", priority="high")
    elif event == "warn" and _settings_get_safe("ntfy.errors", True):
        ntfy_send(topic, extra.get("message", "Warning"), title=f"TL {game_name} - WARN")


def _persist_job(job: dict):
    """Append/update job in the JSONL history file (one JSON per line, keyed by job_id)."""
    try:
        # Rewrite only if the job is final (done/error/unsupported), to avoid constant IO
        if job.get("status") in ("done", "error", "unsupported"):
            with open(JOBS_HISTORY_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(job, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _load_history() -> list[dict]:
    """Load last 20 finished jobs from JSONL history, deduped by job_id (last wins)."""
    if not JOBS_HISTORY_FILE.exists():
        return []
    seen: dict[str, dict] = {}
    try:
        for line in JOBS_HISTORY_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                j = json.loads(line)
                seen[j["job_id"]] = j
            except Exception:
                pass
    except Exception:
        pass
    return list(seen.values())[-20:]

# ── Dashboard HTML ─────────────────────────────────────────────────────────────

DASHBOARD_HTML = open(Path(__file__).parent / "dashboard.html", encoding="utf-8").read()



# ── Engine detection ──────────────────────────────────────────────────────────

def detect_engine(path: Path) -> dict:
    if not path.exists():
        return {"engine": "unknown", "confidence": 0, "details": "ruta no encontrada"}

    # Ren'Py: directorio game/ con archivos .rpy, .rpyc o .rpa
    game_dir = path / "game"
    if game_dir.is_dir():
        # IMPORTANTE: excluir tl/ del conteo — un juego puede tener tl/english/*.rpy
        # del autor pero el contenido real estar empaquetado en .rpyc/.rpa.
        # Solo cuenta .rpy fuera de tl/ y fuera de _force_*.rpy generado por nosotros.
        all_rpy = list(game_dir.rglob("*.rpy"))
        rpy_files = [
            p for p in all_rpy
            if "tl" not in p.relative_to(game_dir).parts[:1]
            and not p.name.startswith("_force_")
        ]
        all_rpyc = [
            p for p in game_dir.rglob("*.rpyc")
            if "tl" not in p.relative_to(game_dir).parts[:1]
        ]
        # rpyc sin su .rpy compañero (orphan) = juego packed parcial
        rpy_set = {p.with_suffix("").as_posix() for p in rpy_files}
        orphan_rpyc = [p for p in all_rpyc if p.with_suffix("").as_posix() not in rpy_set]
        rpa_files = list(game_dir.glob("*.rpa"))

        # Si hay rpy de juego completos y NO hay muchos orphan rpyc ni .rpa: translated
        if rpy_files and len(orphan_rpyc) <= 3 and not rpa_files:
            tl_path = game_dir / "tl" / "spanish"
            state = "translated" if tl_path.exists() else "untranslated"
            return {
                "engine": "renpy",
                "confidence": 0.95,
                "details": f"{len(rpy_files)} archivos .rpy encontrados (game/, sin tl/)",
                "state": state,
                "tl_path": str(tl_path),
            }
        # Si hay .rpa, .rpyc huerfanos (>3) o script_version.txt sin .rpy: packed
        rpyc_files = all_rpyc  # backward compat con bloque siguiente
        script_version = (game_dir / "script_version.txt").exists()
        if rpa_files or rpyc_files or script_version:
            tl_path = game_dir / "tl" / "spanish"
            state = "packed"  # requiere unpack/decompile previo
            details_parts = []
            if rpa_files:
                details_parts.append(f"{len(rpa_files)} .rpa")
            if rpyc_files:
                details_parts.append(f"{len(rpyc_files)} .rpyc")
            if script_version:
                details_parts.append("script_version.txt")
            return {
                "engine": "renpy",
                "confidence": 0.9,
                "details": "Ren'Py empaquetado: " + ", ".join(details_parts),
                "state": state,
                "tl_path": str(tl_path),
                "needs_unpack": bool(rpa_files),
                "needs_decompile": bool(rpyc_files) or bool(rpa_files),
            }

    # Unity: directorio *_Data/
    unity_data = list(path.glob("*_Data"))
    if unity_data:
        streaming = unity_data[0] / "StreamingAssets"
        return {
            "engine": "unity",
            "confidence": 0.9,
            "details": f"Unity data dir: {unity_data[0].name}",
            "state": "manual",
        }

    # Electron: resources/app o resources/app.asar
    if (path / "resources" / "app").is_dir() or (path / "resources" / "app.asar").exists():
        return {
            "engine": "electron",
            "confidence": 0.9,
            "details": "Electron app resources encontrado",
            "state": "manual",
        }

    # RPG Maker: www/data/ o data/ con JSONs
    for data_candidate in [path / "www" / "data", path / "data"]:
        if data_candidate.is_dir() and list(data_candidate.glob("*.json")):
            return {
                "engine": "rpgmaker",
                "confidence": 0.85,
                "details": f"JSON data dir: {data_candidate}",
                "state": "manual",
            }

    return {"engine": "unknown", "confidence": 0, "details": "estructura no reconocida"}


# ── Game info detection (version, OS, runtime) ────────────────────────────────

_VER_RE = re.compile(r'[._\-]([vV]?(\d+\.\d+(?:\.\d+)*[a-zA-Z\d]*))')
_VER_BARE = re.compile(r'(\d+\.\d+(?:\.\d+)*[a-zA-Z\d]*)')


def detect_game_info(path: Path, engine: str) -> dict:
    info: dict = {
        "version": None,
        "version_source": None,
        "os": [],
        "arch": None,
        "runtime": None,
        "company": None,
        "product_name": None,
    }

    # ── Versión (orden de prioridad) ──────────────────────────────────────────

    # 1. .itch.toml
    for toml in [path / ".itch.toml", path / "itch.toml"]:
        if toml.exists():
            m = re.search(r'version\s*=\s*["\']?([0-9][^\s"\']+)',
                          toml.read_text(errors="ignore"))
            if m:
                info["version"] = m.group(1)
                info["version_source"] = ".itch.toml"
                break

    # 2. Archivo de versión explícito en raíz (pequeño)
    if not info["version"]:
        for fname in ["version.txt", "VERSION", "ver.txt", "version"]:
            f = path / fname
            if f.exists() and f.stat().st_size < 512:
                txt = f.read_text(errors="ignore").strip().splitlines()
                if txt:
                    m = _VER_BARE.search(txt[0])
                    if m:
                        info["version"] = m.group(1)
                        info["version_source"] = fname
                        break

    # 3. Unity app.info (empresa / producto / versión)
    if engine == "unity":
        for data_dir in list(path.glob("*_Data"))[:1]:
            app_info = data_dir / "app.info"
            if app_info.exists():
                lines = [l.strip() for l in
                         app_info.read_text(errors="ignore").splitlines() if l.strip()]
                if len(lines) >= 1:
                    info["company"] = lines[0]
                if len(lines) >= 2:
                    info["product_name"] = lines[1]
                if len(lines) >= 3 and not info["version"]:
                    info["version"] = lines[2]
                    info["version_source"] = "app.info"

    # 4. Nombre del ejecutable raíz (con separador, luego sin separador)
    if not info["version"]:
        for exe in (list(path.glob("*.x86_64")) + list(path.glob("*.exe"))
                    + list(path.glob("*.sh")) + list(path.glob("*.app"))):
            m = _VER_RE.search(exe.stem) or _VER_BARE.search(exe.stem)
            if m:
                info["version"] = m.group(2) if m.lastindex and m.lastindex >= 2 else m.group(1)
                info["version_source"] = "executable"
                break

    # 5. Nombre de la carpeta (con separador, luego sin separador)
    if not info["version"]:
        m = _VER_RE.search(path.name) or _VER_BARE.search(path.name)
        if m:
            info["version"] = m.group(2) if m.lastindex and m.lastindex >= 2 else m.group(1)
            info["version_source"] = "folder"

    # ── Sistema operativo ─────────────────────────────────────────────────────

    os_set: set[str] = set()

    # Ejecutables en raíz
    for exe in path.glob("*.x86_64"):
        os_set.add("linux")
        info["arch"] = "x86_64"
    for _ in path.glob("*.x86"):
        os_set.add("linux")
        if not info["arch"]:
            info["arch"] = "x86"
    for exe in path.glob("*.exe"):
        os_set.add("windows")
    for _ in path.glob("*.app"):
        os_set.add("macos")

    # Nombre del ejecutable con hints ("linux", "win", "mac") — Demon Lord's Lover style
    for exe in (list(path.glob("*.x86_64")) + list(path.glob("*.exe"))
                + list(path.glob("*.sh"))):
        n = exe.name.lower()
        if "linux" in n:
            os_set.add("linux")
        if "win" in n:
            os_set.add("windows")
        if "mac" in n or "osx" in n:
            os_set.add("macos")

    # Ren'Py lib/ subdirs — "py3-linux-x86_64", "py3-windows-x86_64"
    for lib in [path / "lib", path / "game" / "lib"]:
        if lib.is_dir():
            for d in lib.iterdir():
                n = d.name.lower()
                if "linux" in n:
                    os_set.add("linux")
                    if "x86_64" in n:
                        info["arch"] = "x86_64"
                if "windows" in n or "win" in n:
                    os_set.add("windows")
                if "mac" in n or "darwin" in n:
                    os_set.add("macos")

    info["os"] = sorted(os_set)

    # ── Runtime ──────────────────────────────────────────────────────────────

    if engine == "unity":
        for data_dir in list(path.glob("*_Data"))[:1]:
            if (data_dir / "il2cpp_data").is_dir():
                info["runtime"] = "IL2CPP"
            elif (data_dir / "Managed").is_dir():
                info["runtime"] = "Mono"

    elif engine == "renpy":
        for ver_file in list(path.rglob("renpy/version.txt"))[:1]:
            v = ver_file.read_text(errors="ignore").strip()
            if v:
                info["runtime"] = f"Ren'Py {v}"
                break
        if not info["runtime"]:
            for init in list(path.rglob("renpy/common/00init.rpy"))[:1]:
                m = re.search(r'version_tuple\s*=\s*\(([^)]+)\)',
                              init.read_text(errors="ignore"))
                if m:
                    info["runtime"] = f"Ren'Py {m.group(1).replace(', ','.')}"
                    break

    return info


def detect_unity_json_tl(path: Path) -> dict | None:
    """Detecta si un juego Unity tiene sistema nativo de traducción JSON.
    Retorna metadatos o None si no aplica."""
    for data_dir in list(path.glob("*_Data")) or [path]:
        tl_dir = data_dir / "StreamingAssets" / "Translations"
        if not tl_dir.is_dir():
            continue
        eng_dir = tl_dir / "English"
        if not eng_dir.is_dir():
            continue
        jsons = list(eng_dir.glob("*.json"))
        if not jsons:
            continue
        lang_file = tl_dir / "languages.json"
        langs = []
        if lang_file.exists():
            try:
                langs = json.loads(lang_file.read_text(encoding="utf-8-sig")).get("languages", [])
            except Exception:
                pass
        return {
            "tl_dir": str(tl_dir),
            "json_count": len(jsons),
            "languages": langs,
        }
    return None


# ── Ren'Py SDK ───────────────────────────────────────────────────────────────

def find_renpy_sdk() -> Path | None:
    """Busca renpy.sh en: RENPY_SDK env var, luego ubicaciones comunes."""
    sdk_env = os.environ.get("RENPY_SDK", "")
    if sdk_env:
        p = Path(sdk_env)
        # Puede ser la carpeta raíz del SDK o la ruta directa al ejecutable
        if p.is_file() and p.suffix == ".sh":
            return p
        if (p / "renpy.sh").exists():
            return p / "renpy.sh"

    home = Path.home()
    candidates: list[Path] = []
    for base in [home, home / "Downloads", home / "opt", Path("/opt")]:
        if base.is_dir():
            for d in base.iterdir():
                if d.is_dir() and "renpy" in d.name.lower():
                    sh = d / "renpy.sh"
                    if sh.exists():
                        candidates.append(sh)
    candidates += [
        home / "renpy-sdk" / "renpy.sh",
        home / "renpy" / "renpy.sh",
        home / "Ren'Py" / "renpy.sh",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


# ── Copia a Documents/games tl/ ──────────────────────────────────────────────

def _fix_executable_perms(path: Path, job: dict | None = None) -> list[str]:
    """Aplica +x a binarios ejecutables conocidos del juego.
    Bug habitual: archivos descargados/descomprimidos sin bits ejecutables;
    rsync los copia tal cual y el juego no arranca.

    Detecta y arregla:
    - <path>/<name>.sh (launcher Ren'Py)
    - <path>/lib/py3-linux-*/<name> (binario Python Ren'Py)
    - <path>/lib/linux-*/<name> (binario Ren'Py viejo)
    - <path>/<name>.x86_64 (binario Unity Linux)
    - <path>/<name> (binario sin extension, RPGM/algunos)

    Retorna lista de paths que recibieron +x.
    """
    fixed: list[str] = []
    try:
        # 1. .sh launcher Ren'Py
        for sh in path.glob("*.sh"):
            if sh.is_file() and not os.access(sh, os.X_OK):
                sh.chmod(sh.stat().st_mode | 0o111)
                fixed.append(str(sh.relative_to(path)))

        # 2. Binarios Ren'Py en lib/py3-linux-* y lib/linux-*
        for lib_dir in list((path / "lib").glob("py3-linux-*")) + list((path / "lib").glob("linux-*")):
            if not lib_dir.is_dir():
                continue
            for bin_file in lib_dir.iterdir():
                # Es binario si no tiene extension o termina en formato ejecutable
                if bin_file.is_file() and not bin_file.suffix and not os.access(bin_file, os.X_OK):
                    bin_file.chmod(bin_file.stat().st_mode | 0o111)
                    fixed.append(str(bin_file.relative_to(path)))

        # 3. Binarios Unity Linux (*.x86_64, *.x86)
        for ext in ("*.x86_64", "*.x86"):
            for binf in path.glob(ext):
                if binf.is_file() and not os.access(binf, os.X_OK):
                    binf.chmod(binf.stat().st_mode | 0o111)
                    fixed.append(str(binf.relative_to(path)))
    except Exception as e:
        if job is not None:
            job.setdefault("progress", []).append(f"  WARN fix perms: {e}")
    return fixed


def copy_to_games_tl(game_path: Path, game_name: str, job: dict):
    """Copia el juego completo a ~/Documents/games tl/<game_name>/ con rsync.
    Tras la copia, arregla permisos +x de binarios conocidos (bug comun de zips Linux)."""
    dest = GAMES_TL_DIR / game_name
    job["copy_status"] = "copying"
    job["copy_path"] = str(dest)
    job["progress"].append(f"  Copiando a {dest} ...")
    try:
        GAMES_TL_DIR.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["rsync", "-a", "--update", "--delete",
             str(game_path) + "/", str(dest) + "/"],
            capture_output=True, text=True, timeout=3600,
        )
        if result.returncode == 0:
            job["copy_status"] = "done"
            job["progress"].append(f"  Copia completada → {dest}")
        else:
            job["copy_status"] = "error"
            job["progress"].append(f"  WARN copia rsync: {result.stderr[:200]}")
    except FileNotFoundError:
        # rsync no disponible, fallback a shutil
        try:
            import shutil
            shutil.copytree(str(game_path), str(dest), dirs_exist_ok=True)
            job["copy_status"] = "done"
            job["progress"].append(f"  Copia completada → {dest}")
        except Exception as e:
            job["copy_status"] = "error"
            job["progress"].append(f"  WARN copia: {e}")
    except Exception as e:
        job["copy_status"] = "error"
        job["progress"].append(f"  WARN copia: {e}")

    # Fix permisos en destino. Tambien fix en origen para que el .sh local del usuario funcione.
    if job["copy_status"] == "done":
        fixed_dest = _fix_executable_perms(dest, job)
        fixed_src = _fix_executable_perms(game_path, job)
        all_fixed = sorted(set(fixed_dest + fixed_src))
        if all_fixed:
            job["progress"].append(f"  chmod +x aplicado a {len(all_fixed)} binario(s): {', '.join(all_fixed[:5])}{' ...' if len(all_fixed)>5 else ''}")


# ── Ren'Py pipeline ───────────────────────────────────────────────────────────

def run_renpy_pipeline(job: dict, game_path: Path, provider: str = "deepl", ntfy_topic: str = ""):
    game_name = game_path.name
    def log(msg: str):
        job["progress"].append(msg)
    def notify(msg: str, title: str = "", priority: str = "default"):
        ntfy_send(ntfy_topic, msg, title=title or f"TL {game_name}", priority=priority)

    tl_path = game_path / "game" / "tl" / "spanish"

    # ── Paso 0: generar tl/spanish/ con el SDK si no existe ──────────────────
    if not tl_path.exists():
        sdk = find_renpy_sdk()
        if not sdk:
            log("ERROR: No existe game/tl/spanish/ y no se encontró el SDK de Ren'Py.")
            log("  Opciones:")
            log("  1. Instala el SDK y pon la ruta en RENPY_SDK del .env")
            log("     ej: RENPY_SDK=/home/kelsie/renpy-sdk/renpy.sh")
            log("  2. O corre manualmente: renpy.sh <carpeta_juego> translate spanish")
            job["status"] = "error"
            job["error"] = "SDK Ren'Py no encontrado — define RENPY_SDK en .env"
            return
        log(f"[0/5] Generando tl/spanish/ con SDK ({sdk.name})...")
        r = subprocess.run(
            [str(sdk), str(game_path), "translate", "spanish"],
            capture_output=True, text=True, cwd=str(game_path.parent), timeout=300,
        )
        if r.returncode != 0:
            err = (r.stderr or r.stdout)[:300]
            log(f"ERROR: SDK falló (código {r.returncode}): {err}")
            job["status"] = "error"
            job["error"] = f"renpy.sh translate spanish falló: {err[:200]}"
            return
        if not tl_path.exists():
            log("ERROR: SDK corrió sin error pero tl/spanish/ no se creó.")
            job["status"] = "error"
            job["error"] = "tl/spanish/ no generado tras correr SDK"
            return
        log(f"  tl/spanish/ generado correctamente")

    rpy_files = sorted(tl_path.rglob("*.rpy"))
    if not rpy_files:
        log("ERROR: Sin archivos .rpy en tl/spanish/")
        job["status"] = "error"
        job["error"] = "No hay archivos .rpy en tl/spanish/"
        return

    try:
        _tl_display = tl_path.relative_to(ROOT)
    except ValueError:
        _tl_display = tl_path
    log(f"[1/5] Detectados {len(rpy_files)} archivos .rpy en {_tl_display}")

    # ── Step 2: contar pendientes ─────────────────────────────────────────────
    log("[2/5] Contando strings pendientes...")
    pending = _count_pending(tl_path)
    log(f"  → {pending if pending >= 0 else '?'} strings sin traducir")

    # ── Step 3: traducir ──────────────────────────────────────────────────────
    gi = job.get("game_info") or {}
    meta_parts = []
    if gi.get("version"): meta_parts.append(f"v{gi['version']}")
    if gi.get("os"): meta_parts.extend(gi["os"])
    if gi.get("runtime"): meta_parts.append(gi["runtime"])
    meta_line = f"[{' | '.join(meta_parts)}]\n" if meta_parts else ""

    if pending != 0:
        active_provider = provider
        log(f"[3/5] Traduciendo con provider={active_provider}...")
        notify(
            f"{meta_line}{pending} strings | {len(rpy_files)} archivos | EN -> Spanish\nProvider: {active_provider}",
            title=f"TL {game_name} - Iniciando"
        )
        errors = []
        deepl_exhausted = False
        files_done = 0
        for i, rpy in enumerate(rpy_files, 1):
            log(f"  [{i}/{len(rpy_files)}] {rpy.name}")
            notify(
                f"{meta_line}Archivo [{i}/{len(rpy_files)}]: {rpy.name}\nProvider: {active_provider}",
                title=f"TL {game_name} - {int((i-1)/len(rpy_files)*100)}%"
            )
            r = subprocess.run(
                [sys.executable, str(TL_TOOLS / "translate.py"), str(rpy),
                 "--provider", active_provider],
                capture_output=True, text=True, cwd=str(ROOT), timeout=1800,
            )
            out = r.stdout + r.stderr
            failed = r.returncode != 0 or "[ABORT]" in out
            if failed:
                deepl_fail = active_provider == "deepl" and ("456" in out or "agotadas" in out or "[ABORT]" in out)
                if deepl_fail and not deepl_exhausted:
                    deepl_exhausted = True
                    active_provider = "openai"
                    log(f"  DeepL cuota agotada — cambiando a OpenAI para {rpy.name}")
                    notify(f"{meta_line}DeepL cuota agotada — cambiando a OpenAI\nArchivo: {rpy.name}",
                           title=f"TL {game_name} - Cambiando provider", priority="high")
                    r2 = subprocess.run(
                        [sys.executable, str(TL_TOOLS / "translate.py"), str(rpy),
                         "--provider", "openai"],
                        capture_output=True, text=True, cwd=str(ROOT), timeout=1800,
                    )
                    out2 = r2.stdout + r2.stderr
                    if r2.returncode != 0 or "[ABORT]" in out2:
                        err = out2[:200]
                        log(f"  WARN: {rpy.name} (openai) → {err}")
                        errors.append(rpy.name)
                    else:
                        files_done += 1
                else:
                    err = out[:200]
                    log(f"  WARN: {rpy.name} → {err}")
                    errors.append(rpy.name)
            else:
                files_done += 1
        if errors:
            log(f"  {len(errors)} archivo(s) con errores de traducción")
        else:
            log("  Traducción completada sin errores")
    else:
        log("[3/5] No hay strings pendientes — saltando traducción")

    # ── Step 4: postprocess + lint ────────────────────────────────────────────
    log("[4/5] Postprocess + lint...")
    pp_errors, lint_warnings = 0, 0

    for rpy in rpy_files:
        # postprocess
        r = subprocess.run(
            [sys.executable, str(TL_TOOLS / "postprocess.py"), str(rpy)],
            capture_output=True, text=True, cwd=str(ROOT), timeout=60,
        )
        if r.returncode != 0:
            pp_errors += 1

        # lint
        r = subprocess.run(
            [sys.executable, str(TL_TOOLS / "lint.py"), str(rpy)],
            capture_output=True, text=True, cwd=str(ROOT), timeout=60,
        )
        if r.returncode != 0:
            lint_warnings += 1

    log(f"  Postprocess: {pp_errors} error(es)  |  Lint: {lint_warnings} advertencia(s)")

    # ── Step 5: QA semántico via qa_server ────────────────────────────────────
    log("[5/5] QA semántico vía Ollama (puede tardar)...")
    try:
        payload = json.dumps({"dir": str(tl_path)}).encode()
        req = urllib.request.Request(
            "http://localhost:8765/qa",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            qa_data = json.loads(resp.read())
        issues = qa_data.get("issues_total", 0)
        log(f"  QA: {issues} posibles problemas encontrados")
        job["qa_report"] = qa_data.get("report", "")
        job["qa_issues"] = issues
    except Exception as e:
        log(f"  WARN: qa_server no disponible ({e}) — saltando QA semántico")

    job["status"] = "done"
    job["tl_path"] = str(tl_path)
    log("Pipeline completado.")
    qa_issues = job.get("qa_issues") or 0
    copy_to_games_tl(game_path, game_path.name, job)
    copy_path = job.get("copy_path", "")
    notify(
        f"{meta_line}Archivos: {len(rpy_files)} | QA: {qa_issues} avisos\n"
        f"Copia: {copy_path or 'no realizada'}",
        title=f"TL {game_name} - Listo", priority="high"
    )


def run_rpgmaker_pipeline(job: dict, game_path: Path, provider: str = "deepl",
                          ntfy_topic: str = ""):
    def log(msg: str):
        job["progress"].append(msg)

    log("[1/3] Iniciando traducción RPG Maker MV/MZ...")
    ginfo = job.get("game_info") or {}
    ver = ginfo.get("version") or ""
    gos = "/".join(ginfo.get("os") or [])
    rt = ginfo.get("runtime") or ""

    cmd = [
        sys.executable, str(TL_TOOLS / "translate_rpgmaker.py"),
        str(game_path),
        "--provider", provider,
        "--ntfy", ntfy_topic,
    ]
    if ver: cmd += ["--game-version", ver]
    if gos: cmd += ["--game-os", gos]
    if rt: cmd += ["--game-runtime", rt]

    log(f"  Ejecutando: provider={provider}")

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, cwd=str(ROOT))
    try:
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                log(line)
        proc.wait(timeout=3600)
    except subprocess.TimeoutExpired:
        proc.kill()
        log("  ERROR: timeout (3600s) — proceso terminado")

    if proc.returncode not in (0, 1, None):
        log(f"  WARN: script terminó con código {proc.returncode}")

    log("[2/3] Traducción completada.")

    job["status"] = "done"
    job["tl_path"] = str(game_path)
    log("[3/3] Pipeline completado.")
    copy_to_games_tl(game_path, game_path.name, job)


def run_unity_json_pipeline(job: dict, game_path: Path, lang: str = "Spanish",
                            ntfy_topic: str = ""):
    def log(msg: str):
        job["progress"].append(msg)

    unity_info = detect_unity_json_tl(game_path)
    if not unity_info:
        log("ERROR: no se encontró sistema de traducción JSON en este juego Unity")
        job["status"] = "error"
        job["error"] = "Unity JSON translation system no detectado"
        return

    log(f"[1/3] Unity JSON nativo detectado: {unity_info['json_count']} archivos, idiomas actuales: {unity_info['languages']}")
    log(f"[2/3] Iniciando traducción EN→{lang} (DeepL→OpenAI). Notificaciones vía ntfy...")

    script = TOOLS / "tl" / "translate_unity_json.py"
    ginfo = job.get("game_info") or {}
    cmd = [
        sys.executable, str(script),
        str(game_path),
        "--lang", lang,
        "--ntfy", ntfy_topic,
    ]
    if ginfo.get("version"):
        cmd += ["--game-version", ginfo["version"]]
    if ginfo.get("os"):
        cmd += ["--game-os", "/".join(ginfo["os"])]
    if ginfo.get("runtime"):
        cmd += ["--game-runtime", ginfo["runtime"]]

    log(f"  Ejecutando: {' '.join(cmd[-4:])}")

    # Stats en tiempo real, visibles desde /dashboard
    job["stats"] = {
        "files_done": 0,
        "total_files": unity_info["json_count"],
        "strings_done": 0,
        "total_strings": 0,
        "pct": 0,
        "current_file": "",
        "provider": "DeepL",
        "openai_spent": 0.0,
    }

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(ROOT),
        )

        # Killer por timeout (2h)
        def _kill():
            try:
                proc.kill()
            except Exception:
                pass

        _timer = threading.Timer(7200, _kill)
        _timer.start()

        try:
            for raw in proc.stdout:
                line = raw.rstrip()
                if not line:
                    continue
                log(f"  {line}")

                # Parsear progreso: "[42/117] file.json | 1523/9358 strings | 35%"
                m = _PROG_RE.search(line)
                if m:
                    fd, tf, fn, sd, ts, pct = m.groups()
                    job["stats"].update({
                        "files_done": int(fd),
                        "total_files": int(tf),
                        "strings_done": int(sd),
                        "total_strings": int(ts),
                        "pct": int(pct),
                        "current_file": fn,
                    })

                # Gasto OpenAI: "gastado $0.0423"
                m2 = _OAPI_SPENT_RE.search(line)
                if m2:
                    job["stats"]["openai_spent"] = float(m2.group(1))

                # Cambio de provider
                if _TO_OPENAI_RE.search(line):
                    job["stats"]["provider"] = "OpenAI"
        finally:
            _timer.cancel()

        proc.wait()
        rc = proc.returncode

        if rc == 0:
            log("[3/3] Traducción completada sin errores.")
            job["status"] = "done"
            job["stats"]["pct"] = 100
            copy_to_games_tl(game_path, game_path.name, job)
        elif rc == 2:
            log("[3/3] Traducción detenida: presupuesto OpenAI alcanzado.")
            job["status"] = "done"
            job["warning"] = "budget_exceeded"
            copy_to_games_tl(game_path, game_path.name, job)
        elif rc == -9:
            log("ERROR: timeout (>2h)")
            job["status"] = "error"
            job["error"] = "Timeout en traducción Unity JSON (>2h)"
        else:
            log(f"[3/3] ERROR (código {rc})")
            job["status"] = "error"
            job["error"] = f"translate_unity_json salió con código {rc}"

    except Exception as e:
        log(f"ERROR inesperado: {e}")
        job["status"] = "error"
        job["error"] = str(e)


def _count_pending(tl_path: Path) -> int:
    """Retorna número de strings pendientes, o -1 si no se puede determinar."""
    script = TL_TOOLS / "_count_pending.py"
    if not script.exists():
        return -1
    r = subprocess.run(
        [sys.executable, str(script), str(tl_path)],
        capture_output=True, text=True, cwd=str(ROOT), timeout=30,
    )
    if r.returncode != 0:
        return -1
    try:
        for line in r.stdout.splitlines():
            if line.startswith("bloques pendientes:"):
                return int(line.split(":")[1].strip())
        return -1
    except (ValueError, IndexError):
        return -1


# ── Auto-diagnose post-job ────────────────────────────────────────────────────

def _run_diagnose(job: dict):
    """Ejecuta diagnose.sh tras finalizar el job. Guarda output en job['diagnose_report']
    y un resumen en progress[]. Best-effort: si falla, no rompe nada."""
    if not _settings_get_safe("diagnose.run_after_job", True):
        return
    diag_script = TOOLS / "diagnose.sh"
    if not diag_script.exists():
        return
    timeout = int(_settings_get_safe("diagnose.timeout_sec", 60))
    job_id = job.get("job_id", "")
    try:
        r = subprocess.run(
            [str(diag_script), job_id, "--no-color"],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(ROOT),
        )
        report = r.stdout or "(diagnose vacio)"
        job["diagnose_report"] = report
        job.setdefault("progress", []).append("")
        job["progress"].append("[DIAGNOSE] Reporte generado (ver job.diagnose_report)")
        if r.returncode != 0 and r.stderr:
            job["progress"].append(f"[DIAGNOSE] stderr: {r.stderr[:200]}")
    except subprocess.TimeoutExpired:
        job.setdefault("progress", []).append(f"[DIAGNOSE] timeout (>{timeout}s)")
        job["diagnose_report"] = f"diagnose.sh timeout despues de {timeout}s"
    except Exception as e:
        job.setdefault("progress", []).append(f"[DIAGNOSE] error: {e}")
        job["diagnose_report"] = f"diagnose.sh fallo: {e}"


# ── Pipeline v2: orquestador 5-etapas ────────────────────────────────────────

_PKG_PROG_RE = re.compile(r'\[PROGRESS\]\s+file=(\S+)\s+done=(\d+)\s+total=(\d+)\s+pct=(\d+)')


def _maybe_clear_deepl_exhausted():
    """Limpia exhausted_today si la pool reporta >50K chars disponibles via API.
    Mitiga el flag stale del bug: una key 456 marcaba TODO el pool como agotado."""
    if _dl is None:
        return
    try:
        if not _dl.is_exhausted_today():
            return
        quota = _dl.check_quota_pool()
        if quota.get("source") == "api" and quota.get("available", 0) > 50_000:
            state = _dl.get_state()
            state.pop("exhausted_date", None)
            _dl.QUOTA_STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
    except Exception:
        pass


def _du_bytes(path: Path) -> int:
    total = 0
    try:
        for r, _, fs in os.walk(path):
            for f in fs:
                try:
                    total += os.path.getsize(os.path.join(r, f))
                except OSError:
                    pass
    except Exception:
        pass
    return total


def _count_chars_for(engine: str, game_path: Path) -> tuple[int, int]:
    """Returns (chars_aprox, file_count). Best-effort para preflight."""
    if engine == "renpy":
        tl = game_path / "game" / "tl" / "spanish"
        if not tl.exists():
            return 0, 0
        rpys = list(tl.rglob("*.rpy"))
        chars = 0
        for r in rpys[:500]:
            try:
                txt = r.read_text(encoding="utf-8", errors="ignore")
                for line in txt.splitlines():
                    s = line.strip()
                    if s.startswith('# "') or s.startswith('# old '):
                        chars += max(0, len(s) - 4)
            except Exception:
                pass
        return chars, len(rpys)
    elif engine == "unity":
        info = detect_unity_json_tl(game_path)
        if not info:
            return 0, 0
        eng_dir = Path(info["tl_dir"]) / "English"
        files = list(eng_dir.glob("*.json")) if eng_dir.exists() else []
        try:
            chars = sum(f.stat().st_size for f in files)
        except Exception:
            chars = 0
        return chars, len(files)
    elif engine == "rpgmaker":
        data = game_path / "www" / "data"
        if not data.exists():
            data = game_path / "data"
        if not data.exists():
            return 0, 0
        files = list(data.glob("*.json"))
        try:
            chars = sum(f.stat().st_size for f in files)
        except Exception:
            chars = 0
        return chars, len(files)
    return 0, 0


def run_pipeline_v2(job: dict, game_path: Path, lang: str = "Spanish",
                    ntfy_topic: str = "", force_provider: str | None = None):
    """Orquesta 5 etapas: analyze -> setup -> translate -> lint_qa -> package."""
    settings = _s.get_all() if _s else {}

    engine_info = detect_engine(game_path)
    engine = engine_info["engine"]
    job["engine"] = engine_info
    job["progress"].append(
        f"Engine: {engine} (confianza {engine_info['confidence']:.0%}) — {engine_info['details']}"
    )

    if engine not in ("renpy", "unity", "rpgmaker"):
        job["progress"].append(f"Engine '{engine}' no soportado por pipeline v2.")
        job["status"] = "unsupported"
        return

    tracker = StageTracker(job, engine)

    try:
        _v2_analyze(job, game_path, engine, settings, tracker, force_provider)
        if job["status"] in ("error", "unsupported"):
            return

        _v2_setup(job, game_path, engine, settings, tracker)
        if job["status"] == "error":
            return

        _v2_translate(job, game_path, lang, engine, settings, tracker)
        # warning="budget_exceeded" no es fatal — sigue a lint/package

        _v2_lint_qa(job, game_path, engine, settings, tracker)

        _v2_package(job, game_path, settings, tracker)

        if job["status"] != "error":
            job["status"] = "done"
    except subprocess.TimeoutExpired as e:
        job["status"] = "error"
        job["error"] = f"Timeout en subproceso: {e}"
        emit_event(job, job.get("current_stage") or "pipeline", "error",
                   message=f"Timeout: {e}")
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        emit_event(job, job.get("current_stage") or "pipeline", "error", message=str(e))


def _renpy_unpack_and_decompile(game_path: Path, job: dict, settings: dict) -> tuple[bool, str]:
    """Si game/ tiene .rpa o solo .rpyc, ejecuta unrpa + unrpyc para dejar .rpy editables.
    Retorna (ok, mensaje). Idempotente: si ya hay .rpy, no hace nada."""
    game_dir = game_path / "game"
    if not game_dir.is_dir():
        return False, "game/ no existe"

    # Si ya hay .rpy, asumir que esta listo
    existing_rpy = list(game_dir.rglob("*.rpy"))
    if existing_rpy:
        return True, f"ya hay {len(existing_rpy)} .rpy"

    rs = _settings_get_safe("renpy", {}) or {}
    auto = rs.get("auto_unpack", True)
    if not auto:
        return False, "auto_unpack desactivado en settings"

    unrpa_bin = rs.get("unrpa_bin") or "/home/kelsie/.local/bin/unrpa"
    unrpyc_script = rs.get("unrpyc_script") or "/home/kelsie/.local/share/unrpyc/unrpyc-master/unrpyc.py"

    # 1. Extraer .rpa
    rpa_files = list(game_dir.glob("*.rpa"))
    if rpa_files:
        if not Path(unrpa_bin).exists():
            return False, f"unrpa no encontrado en {unrpa_bin}"
        for rpa in rpa_files:
            # Solo extraer scripts.rpa y similares — los grandes audio/images skip
            if rpa.name.startswith(("audio", "images", "movie", "video")):
                continue
            r = subprocess.run([unrpa_bin, str(rpa)], capture_output=True, text=True,
                               cwd=str(game_dir), timeout=120)
            if r.returncode != 0:
                return False, f"unrpa fallo en {rpa.name}: {(r.stderr or r.stdout)[:200]}"
            # Renombrar el rpa procesado a .unpacked_bak
            try:
                rpa.rename(rpa.with_suffix(rpa.suffix + ".unpacked_bak"))
            except Exception:
                pass
        emit_event(job, "analyze", "unpack_done", rpa_count=len(rpa_files))

    # 2. Decompilar .rpyc
    rpyc_files = list(game_dir.rglob("*.rpyc"))
    if rpyc_files:
        if not Path(unrpyc_script).exists():
            return False, f"unrpyc no encontrado en {unrpyc_script}"
        r = subprocess.run(["python3", unrpyc_script, "-c", str(game_dir)],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            return False, f"unrpyc fallo: {(r.stderr or r.stdout)[:200]}"
        emit_event(job, "analyze", "decompile_done", rpyc_count=len(rpyc_files))

    # Verificar resultado
    new_rpy = list(game_dir.rglob("*.rpy"))
    if not new_rpy:
        return False, "tras unpack+decompile no quedaron .rpy"
    return True, f"generados {len(new_rpy)} .rpy"


def _v2_analyze(job, game_path: Path, engine: str, settings: dict,
                tracker: StageTracker, force_provider: str | None):
    tracker.start("analyze")

    ginfo = detect_game_info(game_path, engine)
    job["game_info"] = ginfo
    tracker.set_pct("analyze", 20)

    # Unity: sistema JSON nativo si existe; si no, XUnity.AutoTranslator (builds Mono)
    if engine == "unity":
        unity_json = detect_unity_json_tl(game_path)
        if unity_json:
            job["unity_json"] = unity_json
            job["unity_mode"] = "json"
        else:
            sys.path.insert(0, str(TL_TOOLS))
            import unity_xunity
            build = unity_xunity.detectar_build(game_path)
            if "error" in build or build["runtime"] != "mono":
                motivo = build.get("error") or f"build {build['runtime']} (XUnity automático sólo cubre Mono; IL2CPP necesita BepInEx 6, manual)"
                tracker.end("analyze", status="error", details={"reason": "unity_no_soportado", "build": build})
                job["status"] = "unsupported"
                job["error"] = f"Unity sin sistema JSON nativo y {motivo}"
                return
            job["unity_mode"] = "xunity"
            job["unity_build"] = build
            job["progress"].append(f"  Unity sin JSON nativo → XUnity.AutoTranslator (build {build['runtime']} {build['arch']}, {Path(build['data_dir']).name})")

    # Ren'Py: si script empaquetado, unpack + decompile primero
    if engine == "renpy":
        ginfo_state = (job.get("engine") or {}).get("state") or ""
        engine_meta = job.get("engine") or {}
        if engine_meta.get("needs_unpack") or engine_meta.get("needs_decompile"):
            tracker.set_pct("analyze", 25, current="unpack+decompile rpa/rpyc")
            unpack_ok, unpack_msg = _renpy_unpack_and_decompile(game_path, job, settings)
            if not unpack_ok:
                tracker.end("analyze", status="error", details={"reason": unpack_msg})
                job["status"] = "error"
                job["error"] = unpack_msg
                return

    # Ren'Py: generar tl/spanish/ aqui (prerequisito de count chars)
    if engine == "renpy":
        tl_path = game_path / "game" / "tl" / "spanish"
        if not tl_path.exists():
            sdk = find_renpy_sdk()
            if not sdk:
                tracker.end("analyze", status="error",
                            details={"reason": "renpy_sdk_no_encontrado"})
                job["status"] = "error"
                job["error"] = "SDK Ren'Py no encontrado — define RENPY_SDK"
                return
            tracker.set_pct("analyze", 35, current="generando tl/spanish/")
            r = subprocess.run(
                [str(sdk), str(game_path), "translate", "spanish"],
                capture_output=True, text=True, cwd=str(game_path.parent), timeout=300,
            )
            if r.returncode != 0 or not tl_path.exists():
                err = ((r.stderr or r.stdout) or "")[:200]
                tracker.end("analyze", status="error",
                            details={"reason": f"renpy_sdk_fallo: {err}"})
                job["status"] = "error"
                job["error"] = f"renpy.sh translate spanish fallo: {err}"
                return
        job["tl_path"] = str(tl_path)

    # Conteo chars + size
    tracker.set_pct("analyze", 60, current="contando chars traducibles")
    chars, file_count = _count_chars_for(engine, game_path)
    size_bytes = _du_bytes(game_path)

    # Preflight provider
    tracker.set_pct("analyze", 80, current="preflight provider")
    _maybe_clear_deepl_exhausted()
    deepl_quota = _dl.check_quota_pool() if _dl else {}

    if force_provider:
        provider, reason = force_provider, "forced_by_request"
    else:
        try:
            import _preflight
            provider, reason = _preflight.decide_provider(chars, settings, deepl_quota)
        except Exception as e:
            provider, reason = "deepl", f"preflight_error:{e}"

    # OpenAI budget restante
    openai_avail = 0.0
    usage_file = TL_TOOLS / ".cache" / "openai_usage.json"
    if usage_file.exists():
        try:
            u = json.loads(usage_file.read_text())
            budget = float(_settings_get_safe("openai.budget_usd", 1.50))
            openai_avail = max(0.0, budget - u.get("total_cost_usd", 0))
        except Exception:
            pass

    job["analysis"] = {
        "engine": engine,
        "version": ginfo.get("version"),
        "os": ginfo.get("os"),
        "runtime": ginfo.get("runtime"),
        "files_count": file_count,
        "chars_count": chars,
        "size_bytes": size_bytes,
        "size_gb": round(size_bytes / (1024 ** 3), 2),
        "chosen_provider": provider,
        "provider_reason": reason,
        "deepl_quota_avail": deepl_quota.get("available", 0),
        "openai_budget_avail": round(openai_avail, 4),
    }
    job["provider"] = provider  # backward compat con dashboard viejo
    tracker.end("analyze", details=job["analysis"])


def _translate_env(job: dict) -> dict:
    """Entorno para translate.py: glosario del juego (nombres protegidos) si se generó en setup."""
    env = dict(os.environ)
    if job.get("glossary"):
        env["TL_GLOSSARY"] = job["glossary"]
    return env


def _renpy_game_glossary(job: dict, game_path: Path) -> int:
    """Genera <juego>/tl-es-glossary.json con los Character() del juego. Devuelve cuántos nombres."""
    sys.path.insert(0, str(TL_TOOLS))
    import game_glossary
    out = game_path / "tl-es-glossary.json"
    data = game_glossary.generar(game_path / "game", out)
    job["glossary"] = str(out)
    job["glossary_names"] = sorted(data["characters"])
    return len(data["characters"])


def _v2_setup(job, game_path: Path, engine: str, settings: dict, tracker: StageTracker):
    tracker.start("setup")
    if engine == "renpy" and _settings_get_safe("renpy.game_glossary", True):
        try:
            n = _renpy_game_glossary(job, game_path)
            job["progress"].append(f"  Glosario del juego: {n} nombres protegidos" + (f" ({', '.join(job['glossary_names'][:8])}{'…' if n > 8 else ''})" if n else ""))
        except Exception as e:
            emit_event(job, "setup", "warn", message=f"glosario del juego no generado: {e}")
    tracker.set_pct("setup", 100)
    tracker.end("setup", details={"glossary_names": len(job.get("glossary_names") or [])})


def _v2_translate(job, game_path: Path, lang: str, engine: str,
                  settings: dict, tracker: StageTracker):
    tracker.start("translate")
    provider = job.get("provider") or "deepl"
    ntfy_topic = _ntfy_topic_for(job)

    if engine == "renpy":
        _v2_renpy_translate(job, game_path, provider, tracker)
    elif engine == "unity":
        _v2_unity_translate(job, game_path, lang, ntfy_topic, tracker)
    elif engine == "rpgmaker":
        _v2_rpgm_translate(job, game_path, provider, ntfy_topic, tracker)

    if job["status"] != "error":
        st = job.get("stats", {})
        tracker.end("translate", details={
            "files_done": st.get("files_done"),
            "strings_done": st.get("strings_done"),
            "openai_spent": st.get("openai_spent"),
            "provider_final": st.get("provider"),
        })


def _renpy_has_language_selector(game_path: Path) -> bool:
    """Detecta si el juego ya expone un selector de idioma en su UI.
    Busca llamadas a change_language o referencias a _preferences.language en game/*.rpy (excluyendo tl/)."""
    game_dir = game_path / "game"
    if not game_dir.is_dir():
        return False
    try:
        for rpy in game_dir.rglob("*.rpy"):
            # Saltar archivos en tl/ (las traducciones generadas)
            if "tl/" in str(rpy.relative_to(game_dir)).replace(os.sep, "/"):
                continue
            try:
                content = rpy.read_text(encoding="utf-8", errors="ignore")
                if "change_language" in content or "_preferences.language" in content:
                    return True
            except Exception:
                pass
    except Exception:
        pass
    return False


def _renpy_inject_language_force(game_path: Path, lang_code: str = "spanish") -> Path | None:
    """Crea game/_force_<lang>.rpy con config.default_language Y renpy.change_language
    en init 1500 (para sobrescribir persistent existente con language=None).
    Retorna la ruta del archivo creado, o None si ya existia."""
    target = game_path / "game" / f"_force_{lang_code}.rpy"
    if target.exists():
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f"""# Forzado de idioma {lang_code} post-traduccion.
# Generado por TL Games pipeline porque el juego no tiene selector de idioma en UI.
# Para volver a EN: borrar este archivo, su .rpyc, y ~/.renpy/<game>/persistent.

init -100 python:
    config.default_language = "{lang_code}"

init 1500 python:
    # Corre DESPUES de cargar persistent. Si el usuario abrio el juego antes
    # del fix y persistent guardo language=None, forzamos el cambio aqui.
    try:
        if _preferences.language != "{lang_code}":
            renpy.change_language("{lang_code}")
    except Exception:
        pass
""",
        encoding="utf-8",
    )
    return target


def _renpy_backup_user_persistent(game_path: Path) -> str | None:
    """Si existe ~/.renpy/<game_basename>_NN/persistent, lo mueve a .bak.<ts>.
    Necesario porque config.default_language NO aplica si persistent ya guardo
    language=None de un arranque previo. Retorna path del backup o None."""
    renpy_dir = Path.home() / ".renpy"
    if not renpy_dir.is_dir():
        return None
    # Ren'Py crea carpetas tipo <game_name>_NN con NN incremental.
    basename = game_path.name.lower().replace(" ", "_").replace("-", "_")
    for sub in renpy_dir.iterdir():
        if not sub.is_dir():
            continue
        # Match flexible: basename está incluido en el dir name (case insensitive)
        if basename.replace("_", "") in sub.name.lower().replace("_", "").replace("-", ""):
            persistent = sub / "persistent"
            if persistent.is_file():
                bak = sub / f"persistent.bak.{int(time.time())}"
                try:
                    persistent.rename(bak)
                    return str(bak)
                except Exception:
                    pass
    return None


_PROVIDER_LABEL = {"deepl": "DeepL", "groq": "Groq", "openai": "OpenAI"}
_ORDEN_PROVIDERS = ["deepl", "groq", "openai"]


def _provider_disponible(p: str) -> bool:
    return bool({"deepl": os.environ.get("DEEPL_API_KEY"), "groq": os.environ.get("GROQ_API_KEY"),
                 "openai": os.environ.get("OPENAI_API_KEY")}.get(p))


def _cadena_providers(provider: str) -> list[str]:
    """Orden automático DeepL → Groq (gratis, 8k tokens/min) → OpenAI, empezando por el provider elegido.
    Si el preflight eligió OpenAI (DeepL sin cupo), Groq va antes por ser gratis."""
    inicio = _ORDEN_PROVIDERS.index(provider) if provider in _ORDEN_PROVIDERS else 0
    cadena = [p for p in _ORDEN_PROVIDERS[inicio:] if _provider_disponible(p)]
    if provider == "openai" and _provider_disponible("groq") and "groq" not in cadena:
        cadena.insert(0, "groq")
    return cadena or [provider]


def _run_translate_file(job: dict, rpy: Path, provider: str) -> tuple[bool, bool]:
    """Corre translate.py sobre un .rpy. Devuelve (ok, cuota_agotada)."""
    proc = subprocess.Popen(
        [sys.executable, str(TL_TOOLS / "translate.py"), str(rpy), "--provider", provider],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=str(ROOT), env=_translate_env(job),
    )
    out_lines = []
    try:
        for line in proc.stdout:
            line = line.rstrip()
            if not line: continue
            out_lines.append(line)
            job["progress"].append(f"  {line}")
            m = _OAPI_SPENT_RE.search(line)
            if m:
                job["stats"]["openai_spent"] = float(m.group(1))
    finally:
        proc.wait(timeout=1800)
    out = "\n".join(out_lines)
    failed = proc.returncode != 0 or "[ABORT]" in out
    if not failed:
        return True, False
    agotado = ("456" in out or "agotad" in out or "[ABORT]" in out or "Groq 429" in out or "BUDGET" in out)
    return False, agotado


def _v2_renpy_translate(job, game_path: Path, provider: str, tracker: StageTracker):
    tl_path = Path(job["tl_path"])
    rpy_files = sorted(tl_path.rglob("*.rpy"))
    if not rpy_files:
        tracker.skip("translate", "no_rpy_files")
        return

    pending = _count_pending(tl_path)
    if pending == 0:
        tracker.skip("translate", "no_pending_strings")
        return

    job.setdefault("stats", {})
    job["stats"].update({
        "total_files": len(rpy_files), "files_done": 0,
        "current_file": "", "provider": provider.title(),
        "openai_spent": 0.0,
    })

    cadena = _cadena_providers(provider)
    idx = 0
    job["stats"]["provider"] = _PROVIDER_LABEL.get(cadena[idx], cadena[idx].title())
    job["stats"]["provider_chain"] = cadena
    files_done = 0

    for i, rpy in enumerate(rpy_files, 1):
        pct = int((i - 1) / len(rpy_files) * 100)
        job["stats"]["current_file"] = rpy.name
        job["stats"]["files_done"] = i - 1
        tracker.set_pct("translate", pct, current_file=rpy.name)

        while True:
            ok, agotado = _run_translate_file(job, rpy, cadena[idx])
            if ok:
                files_done += 1
                break
            if agotado and idx + 1 < len(cadena):
                emit_event(job, "translate", "provider_switch",
                           **{"from": cadena[idx], "to": cadena[idx + 1], "reason": "quota_exhausted"})
                idx += 1
                job["stats"]["provider"] = _PROVIDER_LABEL.get(cadena[idx], cadena[idx].title())
                continue
            emit_event(job, "translate", "warn", message=f"{rpy.name} fallo ({cadena[idx]})")
            break

    job["stats"]["files_done"] = files_done

    # Forzar idioma si el juego NO tiene selector propio
    if _settings_get_safe("renpy.force_language_if_no_selector", True):
        if not _renpy_has_language_selector(game_path):
            lang_code = (job.get("lang") or "Spanish").lower()
            created = _renpy_inject_language_force(game_path, lang_code)
            if created:
                job["progress"].append(
                    f"  Sin selector de idioma en UI; inyectado {created.relative_to(game_path)} "
                    f"(config.default_language='{lang_code}' + renpy.change_language en init 1500)."
                )
                # Tambien backup del persistent del usuario si abrio el juego antes (gana sobre default)
                bak = _renpy_backup_user_persistent(game_path)
                if bak:
                    job["progress"].append(
                        f"  Backup persistent usuario: {bak} (necesario para que el force aplique)"
                    )
                emit_event(job, "translate", "warn",
                           message=f"Juego sin selector de idioma — forzado a {lang_code}. Persistent backed up si existia.")

    tracker.set_pct("translate", 100)


_XU_PROG_RE = re.compile(r"\[PROGRESS\] strings=(\d+)/(\d+) pct=(\d+)")
_XU_RES_RE = re.compile(r"\[XUNITY\] estaticos=(\d+) traducidos=(\d+) exportados=(\d+) archivo=(\S+)")


def _v2_unity_xunity_translate(job, game_path: Path, provider: str, tracker: StageTracker):
    """Unity genérico: instala BepInEx + XUnity y pre-traduce los textos estáticos (tools/tl/unity_xunity.py)."""
    job.setdefault("stats", {})
    job["stats"].update({"total_files": 1, "files_done": 0, "strings_done": 0, "total_strings": 0,
                         "current_file": "XUnity", "provider": provider.title(), "openai_spent": 0.0})
    cmd = [sys.executable, str(TL_TOOLS / "unity_xunity.py"), str(game_path), "--provider", provider,
           "--lang", str(_settings_get_safe("unity.xunity_lang", "es")),
           "--endpoint", str(_settings_get_safe("unity.xunity_endpoint", "GoogleTranslateV2")),
           "--cache-dir", str(_settings_get_safe("unity.xunity_cache_dir", str(Path.home() / "apps" / "unity-tl")))]
    if not _settings_get_safe("unity.xunity_pretranslate", True):
        cmd.append("--no-pretranslate")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=str(ROOT))
    _timer = threading.Timer(7200, lambda: proc.kill())
    _timer.start()
    try:
        for raw in proc.stdout:
            line = raw.rstrip()
            if not line: continue
            job["progress"].append(f"  {line}")
            m = _XU_PROG_RE.search(line)
            if m:
                sd, ts, pct = (int(x) for x in m.groups())
                job["stats"].update({"strings_done": sd, "total_strings": ts, "pct": pct})
                tracker.set_pct("translate", pct, current_file="XUnity estáticos")
            m2 = _XU_RES_RE.search(line)
            if m2:
                job["xunity"] = {"estaticos": int(m2.group(1)), "traducidos": int(m2.group(2)),
                                 "exportados": int(m2.group(3)), "archivo": m2.group(4)}
                job["stats"].update({"strings_done": int(m2.group(2)), "total_strings": int(m2.group(1))})
            m3 = _OAPI_SPENT_RE.search(line)
            if m3:
                job["stats"]["openai_spent"] = float(m3.group(1))
    finally:
        _timer.cancel()
    proc.wait()
    rc = proc.returncode
    if rc == -9:
        job["status"] = "error"
        job["error"] = "Timeout en XUnity (>2h)"
    elif rc != 0:
        job["status"] = "error"
        job["error"] = f"unity_xunity salio con codigo {rc}: " + next((l for l in reversed(job["progress"]) if "[ABORT]" in l), "").strip()
    else:
        job["stats"]["files_done"] = 1
    tracker.set_pct("translate", 100)


def _v2_unity_translate(job, game_path: Path, lang: str, ntfy_topic: str,
                        tracker: StageTracker):
    if job.get("unity_mode") == "xunity":
        _v2_unity_xunity_translate(job, game_path, job.get("provider") or "auto", tracker)
        return
    info = job.get("unity_json") or {}
    job.setdefault("stats", {})
    job["stats"].update({
        "total_files": info.get("json_count", 0), "files_done": 0,
        "strings_done": 0, "total_strings": 0,
        "current_file": "", "provider": "DeepL", "openai_spent": 0.0,
    })

    ginfo = job.get("game_info") or {}
    cmd = [
        sys.executable, str(TL_TOOLS / "translate_unity_json.py"),
        str(game_path), "--lang", lang, "--ntfy", ntfy_topic,
    ]
    if ginfo.get("version"): cmd += ["--game-version", ginfo["version"]]
    if ginfo.get("os"): cmd += ["--game-os", "/".join(ginfo["os"])]
    if ginfo.get("runtime"): cmd += ["--game-runtime", ginfo["runtime"]]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, cwd=str(ROOT))
    _timer = threading.Timer(7200, lambda: proc.kill())
    _timer.start()
    try:
        for raw in proc.stdout:
            line = raw.rstrip()
            if not line: continue
            job["progress"].append(f"  {line}")
            m = _PROG_RE.search(line)
            if m:
                fd, tf, fn, sd, ts, pct = m.groups()
                job["stats"].update({
                    "files_done": int(fd), "total_files": int(tf),
                    "strings_done": int(sd), "total_strings": int(ts),
                    "pct": int(pct), "current_file": fn,
                })
                tracker.set_pct("translate", int(pct), current_file=fn)
            m2 = _OAPI_SPENT_RE.search(line)
            if m2:
                job["stats"]["openai_spent"] = float(m2.group(1))
            if _TO_OPENAI_RE.search(line) and job["stats"]["provider"] != "OpenAI":
                job["stats"]["provider"] = "OpenAI"
                emit_event(job, "translate", "provider_switch",
                           **{"from": "deepl", "to": "openai", "reason": "stdout_signal"})
    finally:
        _timer.cancel()
    proc.wait()
    rc = proc.returncode
    if rc == 2:
        job["warning"] = "budget_exceeded"
        emit_event(job, "translate", "warn", message="OpenAI budget alcanzado")
    elif rc == -9:
        job["status"] = "error"
        job["error"] = "Timeout en traduccion Unity JSON (>2h)"
    elif rc not in (0, 2):
        job["status"] = "error"
        job["error"] = f"translate_unity_json salio con codigo {rc}"
    tracker.set_pct("translate", 100)


def _v2_rpgm_translate(job, game_path: Path, provider: str, ntfy_topic: str,
                       tracker: StageTracker):
    job.setdefault("stats", {})
    job["stats"].setdefault("provider", provider.title())
    job["stats"].setdefault("openai_spent", 0.0)

    ginfo = job.get("game_info") or {}
    cmd = [
        sys.executable, str(TL_TOOLS / "translate_rpgmaker.py"), str(game_path),
        "--provider", provider, "--ntfy", ntfy_topic,
    ]
    if ginfo.get("version"): cmd += ["--game-version", ginfo["version"]]
    if ginfo.get("os"): cmd += ["--game-os", "/".join(ginfo["os"])]
    if ginfo.get("runtime"): cmd += ["--game-runtime", ginfo["runtime"]]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, cwd=str(ROOT))
    try:
        for line in proc.stdout:
            line = line.rstrip()
            if not line: continue
            job["progress"].append(f"  {line}")
            m = _PROG_RE.search(line)
            if m:
                fd, tf, fn, sd, ts, pct = m.groups()
                job["stats"].update({
                    "files_done": int(fd), "total_files": int(tf),
                    "strings_done": int(sd), "total_strings": int(ts),
                    "pct": int(pct), "current_file": fn,
                })
                tracker.set_pct("translate", int(pct), current_file=fn)
            m2 = _OAPI_SPENT_RE.search(line)
            if m2:
                job["stats"]["openai_spent"] = float(m2.group(1))
            if _TO_OPENAI_RE.search(line) and job["stats"]["provider"] != "OpenAI":
                job["stats"]["provider"] = "OpenAI"
                emit_event(job, "translate", "provider_switch",
                           **{"from": "deepl", "to": "openai", "reason": "stdout_signal"})
        proc.wait(timeout=3600)
    except subprocess.TimeoutExpired:
        proc.kill()
        job["status"] = "error"
        job["error"] = "Timeout RPG Maker (>1h)"
        return
    if proc.returncode not in (0, 1, None):
        emit_event(job, "translate", "warn",
                   message=f"rpgmaker salio con codigo {proc.returncode}")
    tracker.set_pct("translate", 100)


def _v2_lint_qa_rpgmaker(job, game_path: Path, tracker: StageTracker):
    tracker.start("lint_qa")
    tracker.set_pct("lint_qa", 10, current="lint_rpgmaker")
    try:
        r = subprocess.run(
            [sys.executable, str(TL_TOOLS / "lint_rpgmaker.py"), str(game_path), "--json"],
            capture_output=True, text=True, cwd=str(ROOT), timeout=300,
        )
        # exit 0 = sin issues; exit 1 = con issues (no fatal). stderr aparte para errores reales.
        if r.returncode not in (0, 1):
            emit_event(job, "lint_qa", "warn",
                       message=f"lint_rpgmaker exit {r.returncode}: {r.stderr[:300]}")
            tracker.end("lint_qa", details={"error": r.stderr[:300]})
            return
        try:
            data = json.loads(r.stdout)
        except Exception as e:
            emit_event(job, "lint_qa", "warn", message=f"lint_rpgmaker JSON parse: {e}")
            tracker.end("lint_qa", details={"error": "json_parse"})
            return
        summary = data.get("summary", {})
        no_bak = data.get("files_no_bak", [])
        job["progress"].append(
            f"  Lint RPGMaker: {data.get('issues_total', 0)} issues  |  "
            f"strings={data.get('strings_compared', 0)}  archivos={data.get('files_checked', 0)}"
        )
        if summary:
            parts = " ".join(f"{k}={v}" for k, v in sorted(summary.items()))
            job["progress"].append(f"    {parts}")
        if no_bak:
            job["progress"].append(f"    sin .bak (no comparados): {len(no_bak)}")
        job["lint_report"] = data
    except subprocess.TimeoutExpired:
        emit_event(job, "lint_qa", "warn", message="lint_rpgmaker timeout (>300s)")
        tracker.end("lint_qa", details={"error": "timeout"})
        return
    tracker.end("lint_qa", details={
        "issues_total": data.get("issues_total", 0),
        "summary": data.get("summary", {}),
        "strings_compared": data.get("strings_compared", 0),
    })


def _v2_lint_qa(job, game_path: Path, engine: str, settings: dict, tracker: StageTracker):
    if engine == "rpgmaker":
        _v2_lint_qa_rpgmaker(job, game_path, tracker)
        return
    if engine != "renpy":
        tracker.skip("lint_qa", "engine_unsupported")
        return

    tracker.start("lint_qa")
    tl_path = Path(job.get("tl_path") or "")
    if not tl_path.exists():
        tracker.skip("lint_qa", "tl_path_no_existe")
        return

    rpy_files = sorted(tl_path.rglob("*.rpy"))
    pp_errors = lint_warnings = 0
    total = max(len(rpy_files), 1)

    for i, rpy in enumerate(rpy_files, 1):
        pct = int((i / total) * 80)
        tracker.set_pct("lint_qa", pct, current_file=rpy.name)
        r = subprocess.run(
            [sys.executable, str(TL_TOOLS / "postprocess.py"), str(rpy)],
            capture_output=True, text=True, cwd=str(ROOT), timeout=60,
        )
        if r.returncode != 0: pp_errors += 1
        r = subprocess.run(
            [sys.executable, str(TL_TOOLS / "lint.py"), str(rpy)],
            capture_output=True, text=True, cwd=str(ROOT), timeout=60,
        )
        if r.returncode != 0: lint_warnings += 1

    job["progress"].append(
        f"  Postprocess: {pp_errors} error(es)  |  Lint: {lint_warnings} advertencia(s)"
    )

    tracker.set_pct("lint_qa", 90, current="qa_semantico_ollama")
    qa_issues = 0
    qa_fixed = 0
    qa_timeout = int(_settings_get_safe("qa.timeout_sec", 600))
    try:
        payload = json.dumps({"dir": str(tl_path), "fix": bool(_settings_get_safe("qa.autofix", True))}).encode()
        req = urllib.request.Request(
            "http://localhost:8765/qa", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=qa_timeout) as resp:
            qa_data = json.loads(resp.read())
        qa_issues = qa_data.get("issues_total", 0)
        qa_fixed = qa_data.get("fixed_total", 0)
        job["qa_report"] = qa_data.get("report", "")
        job["qa_issues"] = qa_issues
        job["qa_fixed"] = qa_fixed
        if qa_fixed:
            job["progress"].append(f"  QA: {qa_fixed} de {qa_issues} avisos corregidos automáticamente")
    except Exception as e:
        emit_event(job, "lint_qa", "warn",
                   message=f"qa_server no respondio en {qa_timeout}s: {e} (continuando sin QA semantico)")

    # Puerta final: `renpy lint` carga el juego con la traducción; si una línea traducida lo rompe, se revierte al inglés
    puerta = {}
    if _settings_get_safe("renpy.lint_gate", True):
        sdk = find_renpy_sdk()
        if sdk:
            tracker.set_pct("lint_qa", 95, current="renpy lint")
            try:
                sys.path.insert(0, str(TL_TOOLS))
                import renpy_lint_gate
                lang_code = (job.get("lang") or "Spanish").lower()
                puerta = renpy_lint_gate.puerta(sdk, game_path, lang_code, int(_settings_get_safe("renpy.lint_gate_intentos", 3)),
                                                log=lambda m: job["progress"].append(f"  {m}"))
                if puerta["revertidas"]:
                    emit_event(job, "lint_qa", "warn", message=f"renpy lint: {len(puerta['revertidas'])} línea(s) traducida(s) rompían el juego y volvieron al inglés")
                if not puerta["ok"]:
                    job.setdefault("warnings", []).append("renpy lint sigue fallando tras revertir: ver detalle de Revisión y QA")
                    emit_event(job, "lint_qa", "warn", message="renpy lint falló y el error no está en la traducción: " + puerta["salida"][-300:].strip())
            except Exception as e:
                emit_event(job, "lint_qa", "warn", message=f"renpy lint no se pudo ejecutar: {e}")
        else:
            job["progress"].append("  renpy lint omitido: SDK no encontrado")

    tracker.end("lint_qa", details={
        "postprocess_errors": pp_errors,
        "lint_warnings": lint_warnings,
        "qa_issues": qa_issues,
        "qa_fixed": qa_fixed,
        "renpy_lint": ({"ok": puerta.get("ok"), "intentos": puerta.get("intentos"), "revertidas": puerta.get("revertidas", [])[:20]} if puerta else None),
    })


def _v2_package(job, game_path: Path, settings: dict, tracker: StageTracker):
    if not _settings_get_safe("package.enabled", True):
        tracker.skip("package", "disabled_by_settings")
        return

    tracker.start("package")
    output_dir = Path(_settings_get_safe("output_dir", str(GAMES_TL_DIR)))

    # 1. Copia con rsync
    tracker.set_pct("package", 20, current="rsync copia")
    copy_to_games_tl(game_path, game_path.name, job)

    # 2. ZIP via _package.py
    if _settings_get_safe("package.mode", "auto") == "rsync_only":
        tracker.end("package", details={"copy_path": job.get("copy_path"), "zip_path": None})
        return

    tracker.set_pct("package", 50, current="empaquetando zip")
    ginfo = job.get("game_info") or {}
    ver = ginfo.get("version") or ""
    safe_name = game_path.name + (f"-v{ver}" if ver else "") + "-spanish.zip"
    zip_path = output_dir / safe_name
    pending_zip = zip_path.with_suffix(".zip.part")

    max_gb = float(_settings_get_safe("package.max_size_gb", 5))
    compress_below = int(_settings_get_safe("package.compress_below_mb", 500))

    cmd = [
        sys.executable, str(TL_TOOLS / "_package.py"),
        str(game_path), str(pending_zip),
        "--max-gb", str(max_gb),
        "--compress-below-mb", str(compress_below),
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, cwd=str(ROOT))
    skipped = False
    try:
        for line in proc.stdout:
            line = line.rstrip()
            if not line: continue
            job["progress"].append(f"  {line}")
            m = _PKG_PROG_RE.search(line)
            if m:
                _, _, _, pct = m.groups()
                stage_pct = 50 + int(int(pct) * 0.45)
                tracker.set_pct("package", stage_pct)
            if "package_skipped_too_large" in line:
                skipped = True
        proc.wait(timeout=3600)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        emit_event(job, "package", "warn", message="Timeout ZIP (>1h)")

    if skipped:
        emit_event(job, "package", "warn", message=f"ZIP omitido: tamano > {max_gb}GB")
        tracker.end("package", details={
            "zip_path": None, "reason": "too_large",
            "copy_path": job.get("copy_path"),
        })
    elif proc.returncode == 0 and pending_zip.exists():
        # Las descargas solo ven paquetes completos, incluso durante una retraducción.
        pending_zip.replace(zip_path)
        size_mb = zip_path.stat().st_size / (1024 ** 2)
        job["zip_path"] = str(zip_path)
        apk = _v2_port_android(job, game_path, output_dir, tracker)
        tracker.end("package", details={
            "zip_path": str(zip_path), "size_mb": round(size_mb, 1),
            "copy_path": job.get("copy_path"), **({"apk": apk} if apk else {}),
        })
    else:
        emit_event(job, "package", "warn", message=f"ZIP fallo (rc={proc.returncode})")
        tracker.end("package", status="error", details={"rc": proc.returncode})
    pending_zip.unlink(missing_ok=True)


def _v2_port_android(job: dict, game_path: Path, output_dir: Path, tracker: StageTracker) -> dict | None:
    """Ren'Py con APK oficial en la entrada → APK traducido en salida (inyección + firma). Nunca es fatal."""
    if (job.get("engine") or {}).get("engine") != "renpy" or not _settings_get_safe("android.enabled", True):
        return None
    sys.path.insert(0, str(TL_TOOLS))
    import apk_patch
    apk_in = apk_patch.buscar_apk(game_path)
    if not apk_in:
        return None
    sdk = find_renpy_sdk()
    if not sdk:
        emit_event(job, "package", "warn", message="APK: SDK de Ren'Py no encontrado; no se pudo portar")
        return None
    tracker.set_pct("package", 96, current="apk android")
    ver = (job.get("game_info") or {}).get("version") or ""
    apk_out = output_dir / (game_path.name + (f"-v{ver}" if ver else "") + "-spanish.apk")
    pending = apk_out.with_suffix(".apk.part")
    try:
        res = apk_patch.portar(sdk, game_path, apk_in, pending, (job.get("lang") or "Spanish").lower(), log=lambda m: job["progress"].append(f"  {m}"))
        pending.replace(apk_out)
        res["apk"] = str(apk_out)
        job["apk_path"] = str(apk_out)
        if res.get("aviso"):
            emit_event(job, "package", "warn", message="APK: " + res["aviso"])
        return res
    except Exception as e:
        pending.unlink(missing_ok=True)
        emit_event(job, "package", "warn", message=f"APK Android no generado: {str(e)[:200]}")
        return None


# ── Job runner ────────────────────────────────────────────────────────────────

def _texto_falla(job: dict) -> str:
    avisos = [str(e.get("message", "")) for e in job.get("events", []) if e.get("event") in ("warn", "error")]
    return "\n".join([str(job.get("error") or "")] + avisos[-10:] + [str(l) for l in job.get("progress", [])[-60:]])


def _diagnosticar_job(job: dict, game_path: Path) -> bool:
    """Si el job falló (o dejó avisos), busca la causa en el catálogo o pregunta al doctor (Groq), aplica la acción
    segura si la hay y deja job['diagnostico']. Devuelve True si conviene reintentar el pipeline."""
    fallo = job.get("status") in ("error", "unsupported")
    avisos = [e for e in job.get("events", []) if e.get("event") in ("warn", "error")]
    if not fallo and not avisos:
        return False
    sys.path.insert(0, str(TL_TOOLS))
    import incidencias, doctor
    texto = _texto_falla(job)
    etapa = job.get("current_stage") or "pipeline"
    receta = incidencias.analizar(texto)
    diag = {"origen": "catalogo" if receta else "doctor", "fallo": fallo, "etapa": etapa}
    if receta:
        diag.update(receta_id=receta["id"], causa=receta["causa"], que_hacer=receta["que_hacer"], fragmento=receta.get("fragmento", ""))
    else:
        d = doctor.diagnosticar(str(job.get("error") or ""), texto, incidencias.catalogo(), (job.get("engine") or {}).get("engine", ""))
        if d.get("error"):
            diag.update(causa="No está en el catálogo y el doctor no respondió (" + d["error"] + ").",
                        que_hacer="Revisar el log en «Ver diagnóstico»; si se repite, pegar el error al asistente.", doctor_error=d["error"])
        else:
            diag.update(causa=d["causa"], que_hacer=d["que_hacer"], confianza=d["confianza"], receta_propuesta=d.get("receta_propuesta"), modelo=d.get("modelo"))
            if d.get("receta_id"):
                receta = next((r for r in incidencias.catalogo() if r["id"] == d["receta_id"]), None)
                if receta:
                    receta = {**receta, "captura": "", "fragmento": ""}
                    diag["receta_id"] = receta["id"]
    reintentar = False
    if receta and fallo and receta.get("accion"):
        ok, resultado = incidencias.aplicar(receta, game_path)
        diag.update(accion=receta["accion"], accion_ok=ok, resultado=resultado)
        reintentar = ok and bool(receta.get("reintentar"))
    elif receta and not fallo and receta.get("accion") == "reiniciar_qa":
        ok, resultado = incidencias.aplicar(receta, game_path)
        diag.update(accion="reiniciar_qa", accion_ok=ok, resultado=resultado)
    job["diagnostico"] = diag
    incidencias.registrar(job.get("job_id", "?"), etapa, diag.get("receta_id"), diag.get("causa", ""), diag.get("accion"),
                          str(diag.get("resultado", "")), diag["origen"], diag.get("fragmento", ""))
    job["progress"].append(f"[DIAGNÓSTICO] {diag.get('causa', '')[:160]}" + (f" → {diag.get('resultado')}" if diag.get("resultado") else ""))
    return reintentar and not job.get("reintentado", False)


def run_job(job_id: str, game_path_str: str, provider: str,
            lang: str = "Spanish", ntfy_topic: str = "",
            pipeline_version: str = "v2", force_provider: str | None = None):
    with _jobs_lock:
        job = _jobs[job_id]

    game_path = Path(game_path_str)

    if pipeline_version == "v2":
        # force_provider ya viene resuelto: None => preflight decide
        run_pipeline_v2(job, game_path, lang=lang, ntfy_topic=ntfy_topic,
                        force_provider=force_provider)
        # Falla → catálogo/doctor → acción segura → un reintento
        if _diagnosticar_job(job, game_path) and not job.get("reintentado"):
            job["reintentado"] = True
            job["progress"].append("↻ Reintento tras la acción automática")
            job["status"] = "running"; job["error"] = None; job["stages"] = _empty_stages(); job["current_stage"] = None
            run_pipeline_v2(job, game_path, lang=lang, ntfy_topic=ntfy_topic, force_provider=force_provider)
            if job["status"] in ("error", "unsupported"):
                _diagnosticar_job(job, game_path)
        job["finished_at"] = time.time()
        _run_diagnose(job)
        _persist_job(job)
        return

    # ── Legacy v1 (mantener por 1-2 semanas como flag) ───────────────────────
    try:
        info = detect_engine(game_path)
        job["engine"] = info
        job["progress"].append(
            f"Engine: {info['engine']} (confianza {info['confidence']:.0%}) — {info['details']}"
        )

        ginfo = detect_game_info(game_path, info["engine"])
        job["game_info"] = ginfo
        os_str = "/".join(ginfo["os"]) if ginfo["os"] else "?"
        ver_str = f"v{ginfo['version']}" if ginfo["version"] else "versión desconocida"
        rt_str = f" [{ginfo['runtime']}]" if ginfo["runtime"] else ""
        job["progress"].append(f"Info: {ver_str} | OS: {os_str}{rt_str}")

        if info["engine"] == "renpy":
            run_renpy_pipeline(job, game_path, provider, ntfy_topic=ntfy_topic)
        elif info["engine"] == "unity":
            unity_json = detect_unity_json_tl(game_path)
            if unity_json:
                job["progress"].append(
                    f"Unity JSON nativo detectado ({unity_json['json_count']} archivos). "
                    f"Idiomas actuales: {unity_json['languages']}"
                )
                run_unity_json_pipeline(job, game_path, lang=lang, ntfy_topic=ntfy_topic)
            else:
                job["progress"].append("Unity sin sistema JSON nativo. Requiere playbook manual.")
                job["status"] = "unsupported"
        elif info["engine"] == "rpgmaker":
            run_rpgmaker_pipeline(job, game_path, provider, ntfy_topic=ntfy_topic)
        else:
            job["progress"].append(
                f"Pipeline automático no disponible para '{info['engine']}'."
            )
            job["status"] = "unsupported"

    except subprocess.TimeoutExpired as e:
        job["status"] = "error"
        job["error"] = f"Timeout en subproceso: {e}"
        job["progress"].append(f"ERROR: timeout — {e}")
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        job["progress"].append(f"ERROR inesperado: {e}")

    job["finished_at"] = time.time()
    _run_diagnose(job)
    _persist_job(job)


# ── HTTP handler ──────────────────────────────────────────────────────────────

class Handler(PublicHandlerMixin, BaseHTTPRequestHandler):

    def output_dir(self):
        return Path(_settings_get_safe("output_dir", str(GAMES_TL_DIR))).expanduser().resolve()

    def jobs_snapshot(self):
        merged = {j["job_id"]: j for j in _load_history()}
        with _jobs_lock:
            merged.update({jid: dict(_jobs[jid]) for jid in _jobs_order})
        return sorted(merged.values(), key=lambda j: j.get("started_at", 0))

    def send_json(self, code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, code: int, html: str):
        body = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self) -> dict:
        body = json.loads(self._read_small_body() or b"{}")
        if not isinstance(body, dict):
            raise ValueError("Se requiere un objeto JSON")
        return body

    def do_GET(self):
        path = self.route()
        if not self.authorize(path):
            return

        if path == "/login":
            return self._serve_login()
        if path == "/entrada":
            return self._list_entrada()
        if path == "/salida":
            return self.send_json(200, {"salida": self._list_salida()})
        if path.startswith("/salida/"):
            return self._download(path[len("/salida/"):])
        if path.startswith("/pipeline/") and path.endswith("/diagnostico"):
            job_id = path[len("/pipeline/"):-len("/diagnostico")]
            job = next((j for j in self.jobs_snapshot() if j["job_id"] == job_id), None)
            if not job:
                return self.send_json(404, {"error": "job no encontrado"})
            report = job.get("diagnose_report") or "Diagnóstico aún no disponible."
            body = report.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)

        if path in ("/", "/dashboard"):
            # Releer del disco para soportar reload sin reiniciar
            try:
                html = open(Path(__file__).parent / "dashboard.html", encoding="utf-8").read()
            except Exception:
                html = DASHBOARD_HTML
            self.send_html(200, html.replace("{B}", _base()))

        elif path == "/health":
            with _jobs_lock:
                n = len(_jobs)
            health = {"status": "ok", "jobs": n}
            # Estado enriquecido: Ollama + DeepL pool + OpenAI budget
            try:
                with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2) as r:
                    health["ollama"] = "ok" if r.status == 200 else f"http {r.status}"
            except Exception:
                health["ollama"] = "down"
            try:
                with urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=2) as r:
                    health["qa"] = json.load(r)
            except Exception:
                health["qa"] = {"status": "down", "backend": _settings_get_safe("qa.backend", "auto")}
            if _dl is not None:
                try:
                    health["deepl"] = _dl.check_quota_pool()
                    for key in health["deepl"].get("per_key", []):
                        key.pop("key_suffix", None)
                    health["deepl_exhausted_today"] = _dl.is_exhausted_today()
                except Exception as e:
                    health["deepl"] = {"error": str(e)}
            usage_file = TL_TOOLS / ".cache" / "openai_usage.json"
            budget = float(_settings_get_safe("openai.budget_usd", 1.50))
            health["openai"] = {"spent_usd": 0, "budget_usd": budget,
                                "available_usd": budget, "requests": 0}
            if usage_file.exists():
                try:
                    u = json.loads(usage_file.read_text())
                    budget = float(_settings_get_safe("openai.budget_usd", 1.50))
                    health["openai"] = {
                        "spent_usd": u.get("total_cost_usd", 0),
                        "budget_usd": budget,
                        "available_usd": max(0.0, budget - u.get("total_cost_usd", 0)),
                        "requests": u.get("requests", 0),
                    }
                except Exception:
                    pass
            self.send_json(200, health)

        elif path == "/settings":
            if _s is None:
                self.send_json(503, {"error": "_settings module no disponible"})
                return
            self.send_json(200, _s.get_all())

        elif path == "/incidencias":
            sys.path.insert(0, str(TL_TOOLS))
            import incidencias
            self.send_json(200, {"incidencias": incidencias.ultimas(50), "catalogo": [{k: r.get(k) for k in ("id", "causa", "que_hacer", "accion")} for r in incidencias.catalogo()]})

        elif path == "/jobs":
            with _jobs_lock:
                live = {jid: _jobs[jid] for jid in _jobs_order[-50:]}
            # Merge with persisted history (live jobs take precedence)
            merged: dict[str, dict] = {}
            for j in _load_history():
                merged[j["job_id"]] = j
            merged.update(live)
            # Sort by started_at ascending, return last 20
            jobs = sorted(merged.values(), key=lambda j: j.get("started_at", 0))[-20:]
            self.send_json(200, {"jobs": jobs})

        elif path.startswith("/pipeline/") and path.endswith("/events"):
            job_id = path[len("/pipeline/"):-len("/events")]
            with _jobs_lock:
                job = _jobs.get(job_id)
            if job:
                self.send_json(200, {"events": job.get("events", [])})
            else:
                self.send_json(404, {"error": "job no encontrado"})

        elif path.startswith("/pipeline/"):
            job_id = path[len("/pipeline/"):]
            with _jobs_lock:
                job = _jobs.get(job_id)
            if job:
                self.send_json(200, job)
            else:
                self.send_json(404, {"error": "job no encontrado"})

        else:
            self.send_json(404, {"error": "ruta no encontrada"})

    def do_POST(self):
        path = self.route()
        if not self.authorize(path):
            return
        if not self.same_origin():
            return
        if path == "/login":
            return self._do_login()
        if path == "/upload":
            return self._upload()

        try:
            body = self.read_body()
        except Exception as e:
            self.close_connection = True
            self.send_json(400, {"error": f"JSON inválido: {e}"})
            return

        with FILES_LOCK:
            self._post_json(path, body)

    def _post_json(self, path, body):
        if path == "/entrada/borrar":
            return self._delete_entrada(body)

        if path == "/entrada/apk":
            return self._vincular_apk(body)

        if path == "/incidencias/aprobar":
            sys.path.insert(0, str(TL_TOOLS))
            import incidencias
            receta = body.get("receta") if isinstance(body.get("receta"), dict) else None
            if not receta or not receta.get("patron"):
                self.send_json(400, {"error": "falta receta.patron"})
                return
            try:
                self.send_json(200, {"ok": True, "receta": incidencias.aprobar_receta(receta)})
            except Exception as e:
                self.send_json(400, {"error": f"receta inválida: {e}"})
            return

        if path == "/health":
            self.send_json(200, {"status": "ok"})

        elif path == "/settings":
            if _s is None:
                self.send_json(503, {"error": "_settings module no disponible"})
                return
            try:
                merged = _s.write(body)
                self.send_json(200, merged)
            except Exception as e:
                self.send_json(400, {"error": f"settings invalido: {e}"})

        elif path == "/detect":
            p = body.get("path", "")
            if not isinstance(p, str) or not p:
                self.send_json(400, {"error": "falta 'path'"})
                return
            self.send_json(200, detect_engine(Path(p)))

        elif path == "/pipeline":
            p = body.get("path", "")
            if not isinstance(p, str) or not p:
                self.send_json(400, {"error": "falta 'path'"})
                return

            # Defaults desde settings
            lang = body.get("lang") or _settings_get_safe("default_lang", "Spanish")
            ntfy_topic = body.get("ntfy_topic") or _settings_get_safe(
                "ntfy_topic", os.environ.get("NTFY_TOPIC", ""))
            default_prov = _settings_get_safe("default_provider", "auto")
            # provider_request: lo que el body indica explicitamente (puede ser None)
            provider_request = body.get("provider")
            # provider para backward compat con v1 (siempre debe ser deepl/openai)
            provider = provider_request or (
                default_prov if default_prov in ("deepl", "openai") else "deepl")
            # force_provider: solo si vino explicito en el body, sino None → deja preflight
            force_provider = body.get("force_provider") or (
                provider_request if provider_request in ("deepl", "openai") else None)
            pipeline_version = body.get("pipeline_version") or "v2"

            # Rechazar si ya hay un job corriendo para el mismo juego
            with _jobs_lock:
                for jid in _jobs_order:
                    existing = _jobs.get(jid)
                    if (existing and existing.get("status") == "running"
                            and Path(existing["game_path"]).resolve() == Path(p).resolve()):
                        self.send_json(409, {
                            "error": "Ya hay un job corriendo para este juego",
                            "existing_job_id": jid,
                            "poll": f"{_base()}/pipeline/{jid}",
                        })
                        return

            job_id = str(uuid.uuid4())[:8]
            job = {
                "job_id": job_id,
                "game_path": p,
                "game_name": body.get("name") or Path(p).name,
                "provider": provider,
                "lang": lang,
                "ntfy_topic": ntfy_topic,
                "status": "running",
                "progress": [],
                "stats": {},
                "engine": None,
                "qa_report": None,
                "qa_issues": None,
                "tl_path": None,
                "error": None,
                "warning": None,
                "game_info": None,
                "copy_status": None,
                "copy_path": None,
                "started_at": time.time(),
                "finished_at": None,
                # Campos aditivos del refactor 5-etapas (Fase 1)
                "stages": _empty_stages(),
                "current_stage": None,
                "overall_pct": 0,
                "events": [],
                "analysis": {},
                "errors": [],
                "warnings": [],
            }
            with _jobs_lock:
                _jobs[job_id] = job
                _jobs_order.append(job_id)
                if len(_jobs_order) > MAX_JOBS:
                    old = _jobs_order.pop(0)
                    _jobs.pop(old, None)

            threading.Thread(
                target=run_job,
                kwargs={
                    "job_id": job_id, "game_path_str": p, "provider": provider,
                    "lang": lang, "ntfy_topic": ntfy_topic,
                    "pipeline_version": pipeline_version,
                    "force_provider": force_provider,
                },
                daemon=True,
            ).start()

            self.send_json(202, {"job_id": job_id, "status": "running",
                                  "poll": f"{_base()}/pipeline/{job_id}",
                                  "pipeline_version": pipeline_version})

        else:
            self.send_json(404, {"error": "ruta no encontrada"})

    def log_message(self, fmt, *args):
        pass


def main():
    ap = argparse.ArgumentParser(description="TL Games Pipeline Server")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    try:
        validate_auth_config()
    except ValueError as exc:
        ap.error(str(exc))
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Pipeline server activo en http://{args.host}:{args.port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
