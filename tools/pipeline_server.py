#!/usr/bin/env python3
"""
Pipeline Server para TL Games — Puerto 8766.
n8n (o cualquier cliente HTTP) envía la ruta de un juego y recibe el resultado
de la pipeline completa: detección de engine → traducción → postprocess → lint → QA semántico.

Endpoints:
  GET  /health               → {"status":"ok", "jobs":<n>}
  POST /detect               {"path":"/ruta/juego"}  → engine info
  POST /pipeline             {"path":"/ruta/juego", "name":"opt", "provider":"deepl",
                              "lang":"Spanish", "ntfy_topic":"koichi_agenda_2026"}
                             → {"job_id":"abc12345", "status":"running"}
  GET  /pipeline/<job_id>    → {"status":"running|done|error|unsupported", "progress":[...], ...}
  GET  /jobs                 → lista de todos los jobs (últimos 50)
"""

import argparse
import json
import os
import sys
import threading
import time
import uuid
import urllib.request
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
TL_TOOLS = TOOLS / "tl"
LOGS = ROOT / "logs"
LOGS.mkdir(exist_ok=True)

MAX_JOBS = 50

_jobs: dict[str, dict] = {}
_jobs_order: list[str] = []
_jobs_lock = threading.Lock()


# ── Engine detection ──────────────────────────────────────────────────────────

def detect_engine(path: Path) -> dict:
    if not path.exists():
        return {"engine": "unknown", "confidence": 0, "details": "ruta no encontrada"}

    # Ren'Py: directorio game/ con archivos .rpy
    game_dir = path / "game"
    if game_dir.is_dir():
        rpy_files = list(game_dir.rglob("*.rpy"))
        if rpy_files:
            tl_path = game_dir / "tl" / "spanish"
            state = "translated" if tl_path.exists() else "untranslated"
            return {
                "engine": "renpy",
                "confidence": 0.95,
                "details": f"{len(rpy_files)} archivos .rpy encontrados",
                "state": state,
                "tl_path": str(tl_path),
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


# ── Ren'Py pipeline ───────────────────────────────────────────────────────────

def run_renpy_pipeline(job: dict, game_path: Path, provider: str = "deepl"):
    def log(msg: str):
        job["progress"].append(msg)

    tl_path = game_path / "game" / "tl" / "spanish"

    if not tl_path.exists():
        log("ERROR: No existe game/tl/spanish/")
        log("  Genera la base primero: renpy <carpeta> translate spanish")
        log("  O crea tl/spanish/ manualmente y corre el SDK de Ren'Py.")
        job["status"] = "error"
        job["error"] = "tl/spanish/ no encontrado — genera la plantilla con Ren'Py SDK primero"
        return

    rpy_files = sorted(tl_path.rglob("*.rpy"))
    if not rpy_files:
        log("ERROR: Sin archivos .rpy en tl/spanish/")
        job["status"] = "error"
        job["error"] = "No hay archivos .rpy en tl/spanish/"
        return

    log(f"[1/5] Detectados {len(rpy_files)} archivos .rpy en {tl_path.relative_to(ROOT)}")

    # ── Step 2: contar pendientes ─────────────────────────────────────────────
    log("[2/5] Contando strings pendientes...")
    pending = _count_pending(tl_path)
    log(f"  → {pending if pending >= 0 else '?'} strings sin traducir")

    # ── Step 3: traducir ──────────────────────────────────────────────────────
    if pending != 0:
        log(f"[3/5] Traduciendo con provider={provider}...")
        errors = []
        for i, rpy in enumerate(rpy_files, 1):
            log(f"  [{i}/{len(rpy_files)}] {rpy.name}")
            r = subprocess.run(
                [sys.executable, str(TL_TOOLS / "translate.py"), str(rpy),
                 "--provider", provider],
                capture_output=True, text=True, cwd=str(ROOT), timeout=300,
            )
            if r.returncode != 0:
                err = (r.stderr or r.stdout)[:200]
                log(f"  WARN: {rpy.name} → {err}")
                errors.append(rpy.name)
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
        with urllib.request.urlopen(req, timeout=600) as resp:
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


def run_unity_json_pipeline(job: dict, game_path: Path, lang: str = "Spanish",
                            ntfy_topic: str = "koichi_agenda_2026"):
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
    cmd = [
        sys.executable, str(script),
        str(game_path),
        "--lang", lang,
        "--ntfy", ntfy_topic,
    ]

    log(f"  Ejecutando: {' '.join(cmd[-4:])}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=7200,  # 2 horas máximo
        )
        # Añadir stdout al progreso (líneas relevantes)
        for line in (result.stdout or "").splitlines():
            if line.strip():
                job["progress"].append(f"  {line}")

        if result.returncode == 0:
            log("[3/3] Traducción completada sin errores.")
            job["status"] = "done"
        elif result.returncode == 2:
            log("[3/3] Traducción detenida: presupuesto OpenAI alcanzado.")
            job["status"] = "done"
            job["warning"] = "budget_exceeded"
        else:
            err = (result.stderr or result.stdout or "")[:300]
            log(f"[3/3] ERROR (código {result.returncode}): {err}")
            job["status"] = "error"
            job["error"] = f"translate_unity_json salió con código {result.returncode}: {err[:200]}"
    except subprocess.TimeoutExpired:
        log("ERROR: timeout (>2h)")
        job["status"] = "error"
        job["error"] = "Timeout en traducción Unity JSON (>2h)"
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
        # El script imprime el conteo en la última línea
        return int(r.stdout.strip().split("\n")[-1])
    except (ValueError, IndexError):
        return -1


# ── Job runner ────────────────────────────────────────────────────────────────

def run_job(job_id: str, game_path_str: str, provider: str,
            lang: str = "Spanish", ntfy_topic: str = "koichi_agenda_2026"):
    with _jobs_lock:
        job = _jobs[job_id]

    game_path = Path(game_path_str)

    try:
        info = detect_engine(game_path)
        job["engine"] = info
        job["progress"].append(
            f"Engine: {info['engine']} (confianza {info['confidence']:.0%}) — {info['details']}"
        )

        if info["engine"] == "renpy":
            run_renpy_pipeline(job, game_path, provider)
        elif info["engine"] == "unity":
            # Verificar si tiene sistema nativo JSON antes de marcar unsupported
            unity_json = detect_unity_json_tl(game_path)
            if unity_json:
                job["progress"].append(
                    f"Unity JSON nativo detectado ({unity_json['json_count']} archivos). "
                    f"Idiomas actuales: {unity_json['languages']}"
                )
                run_unity_json_pipeline(job, game_path, lang=lang, ntfy_topic=ntfy_topic)
            else:
                job["progress"].append(
                    "Unity sin sistema JSON nativo. Requiere playbook manual."
                )
                job["status"] = "unsupported"
        else:
            engine = info["engine"]
            job["progress"].append(
                f"Pipeline automático no disponible para '{engine}'. "
                "Ejecuta el playbook manual desde el workspace de TL Games."
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


# ── HTTP handler ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):

    def send_json(self, code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/health":
            with _jobs_lock:
                n = len(_jobs)
            self.send_json(200, {"status": "ok", "jobs": n})

        elif path == "/jobs":
            with _jobs_lock:
                jobs = [_jobs[jid] for jid in _jobs_order[-50:]]
            self.send_json(200, {"jobs": jobs})

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
        path = urlparse(self.path).path

        try:
            body = self.read_body()
        except Exception as e:
            self.send_json(400, {"error": f"JSON inválido: {e}"})
            return

        if path == "/health":
            self.send_json(200, {"status": "ok"})

        elif path == "/detect":
            p = body.get("path", "")
            if not p:
                self.send_json(400, {"error": "falta 'path'"})
                return
            self.send_json(200, detect_engine(Path(p)))

        elif path == "/pipeline":
            p = body.get("path", "")
            if not p:
                self.send_json(400, {"error": "falta 'path'"})
                return

            provider = body.get("provider", "deepl")
            lang = body.get("lang", "Spanish")
            ntfy_topic = body.get("ntfy_topic", os.environ.get("NTFY_TOPIC", "koichi_agenda_2026"))
            job_id = str(uuid.uuid4())[:8]
            job = {
                "job_id": job_id,
                "game_path": p,
                "game_name": body.get("name") or Path(p).name,
                "provider": provider,
                "lang": lang,
                "status": "running",
                "progress": [],
                "engine": None,
                "qa_report": None,
                "qa_issues": None,
                "tl_path": None,
                "error": None,
                "warning": None,
                "started_at": time.time(),
                "finished_at": None,
            }
            with _jobs_lock:
                _jobs[job_id] = job
                _jobs_order.append(job_id)
                if len(_jobs_order) > MAX_JOBS:
                    old = _jobs_order.pop(0)
                    _jobs.pop(old, None)

            threading.Thread(
                target=run_job, args=(job_id, p, provider, lang, ntfy_topic), daemon=True
            ).start()

            self.send_json(202, {"job_id": job_id, "status": "running",
                                  "poll": f"/pipeline/{job_id}"})

        else:
            self.send_json(404, {"error": "ruta no encontrada"})

    def log_message(self, fmt, *args):
        pass


def main():
    ap = argparse.ArgumentParser(description="TL Games Pipeline Server")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    srv = HTTPServer((args.host, args.port), Handler)
    print(f"Pipeline server activo en http://{args.host}:{args.port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
