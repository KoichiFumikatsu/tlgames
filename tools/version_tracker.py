#!/usr/bin/env python3
"""
Version Tracker para TL Games — Puerto 8767.
Monitorea versiones de juegos en itch.io y F95Zone.

Base de datos: tools/.versions.json

Endpoints:
  GET  /health                          → {"status":"ok"}
  GET  /versions                        → lista de todos los juegos trackeados
  POST /versions/add                    {"name":"Juego", "url":"https://...", "current_version":"1.0"}
  DELETE /versions/<name>               → elimina juego del tracker
  GET  /versions/check                  → chequea todos y retorna actualizaciones
  GET  /versions/check/<name>           → chequea un juego específico

Fuentes soportadas:
  - itch.io:  busca versión en el HTML de la página del juego
  - f95zone:  parsea el título del thread (formato: [v1.23] Nombre [Engine])
"""

import argparse
import json
import re
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, quote

DB_PATH = Path(__file__).parent / ".versions.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


# ── Database ──────────────────────────────────────────────────────────────────

def db_load() -> dict:
    if DB_PATH.exists():
        try:
            return json.loads(DB_PATH.read_text())
        except Exception:
            pass
    return {"games": {}}


def db_save(data: dict):
    DB_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))


# ── Scrapers ──────────────────────────────────────────────────────────────────

def _fetch(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")


def scrape_itch(url: str) -> dict:
    """
    Extrae versión de una página itch.io.
    itch.io muestra la versión en varias partes del HTML:
      - data-user_data JSON con version
      - <span class="version_str"> o similar
    """
    try:
        html = _fetch(url)
    except Exception as e:
        return {"version": None, "error": str(e)}

    # Intento 1: JSON embebido en data-upload_list o similar
    m = re.search(r'"version"\s*:\s*"([^"]+)"', html)
    if m:
        return {"version": m.group(1), "error": None}

    # Intento 2: span con clase version
    m = re.search(r'class="[^"]*version[^"]*"[^>]*>([^<]{1,30})<', html, re.I)
    if m:
        v = m.group(1).strip()
        if v:
            return {"version": v, "error": None}

    # Intento 3: "Version X.Y" en cualquier texto
    m = re.search(r'[Vv]ersion\s*([\d][^\s<"]{0,20})', html)
    if m:
        return {"version": m.group(1).strip(), "error": None}

    return {"version": None, "error": "versión no encontrada en la página"}


def scrape_f95(url: str) -> dict:
    """
    Extrae versión del título del thread en F95Zone.
    Formato estándar: [v1.23] Nombre del Juego [Engine] [Dev]
    """
    try:
        html = _fetch(url, timeout=20)
    except urllib.error.HTTPError as e:
        if e.code in (403, 503):
            return {
                "version": None,
                "error": f"F95Zone bloqueó la petición (HTTP {e.code}). "
                         "Puede requerir cookies de sesión activa.",
            }
        return {"version": None, "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"version": None, "error": str(e)}

    # Título de la página
    m = re.search(r"<title>([^<]+)</title>", html, re.I)
    title = m.group(1) if m else ""

    # Buscar [vX.Y] en el título o en el primer H1
    for pattern in [
        r"\[v?([\d][.\d\w]+)\]",
        r"\bv([\d]+\.[\d\w.]+)\b",
    ]:
        m = re.search(pattern, title, re.I)
        if m:
            return {"version": m.group(1), "error": None}

    # Buscar en el contenido del thread (primer bloque de versión)
    m = re.search(r"Version[:\s]+v?([\d][.\d\w]+)", html, re.I)
    if m:
        return {"version": m.group(1), "error": None}

    return {"version": None, "error": "versión no encontrada en el thread"}


def check_game(game: dict) -> dict:
    """Chequea la versión actual de un juego y retorna el resultado."""
    url = game.get("url", "")
    source = game.get("source", "")

    if not url:
        return {"changed": False, "error": "sin URL configurada"}

    if not source:
        # Auto-detectar fuente por URL
        if "itch.io" in url:
            source = "itch"
        elif "f95zone" in url:
            source = "f95"
        else:
            return {"changed": False, "error": f"fuente no reconocida para {url}"}

    if source == "itch":
        result = scrape_itch(url)
    elif source == "f95":
        result = scrape_f95(url)
    else:
        return {"changed": False, "error": f"fuente desconocida: {source}"}

    new_version = result.get("version")
    old_version = game.get("current_version", "")
    changed = bool(new_version and new_version != old_version)

    return {
        "changed": changed,
        "old_version": old_version,
        "new_version": new_version,
        "error": result.get("error"),
        "checked_at": time.time(),
    }


# ── HTTP handler ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):

    def send_json(self, code: int, data):
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
            self.send_json(200, {"status": "ok", "db": str(DB_PATH)})

        elif path == "/versions":
            db = db_load()
            self.send_json(200, {"games": db["games"]})

        elif path == "/versions/check":
            db = db_load()
            updates = []
            errors = []
            for name, game in db["games"].items():
                r = check_game(game)
                r["name"] = name
                if r["changed"]:
                    # Actualizar versión en la DB
                    game["current_version"] = r["new_version"]
                    game["last_updated"] = time.time()
                    updates.append(r)
                if r.get("error"):
                    errors.append({"name": name, "error": r["error"]})
                game["last_checked"] = time.time()
            db_save(db)
            self.send_json(200, {
                "updates": updates,
                "errors": errors,
                "total_checked": len(db["games"]),
                "checked_at": time.time(),
            })

        elif path.startswith("/versions/check/"):
            name = path[len("/versions/check/"):]
            db = db_load()
            game = db["games"].get(name)
            if not game:
                self.send_json(404, {"error": f"juego '{name}' no encontrado"})
                return
            r = check_game(game)
            if r["changed"]:
                game["current_version"] = r["new_version"]
                game["last_updated"] = time.time()
            game["last_checked"] = time.time()
            db_save(db)
            r["name"] = name
            self.send_json(200, r)

        else:
            self.send_json(404, {"error": "ruta no encontrada"})

    def do_POST(self):
        path = urlparse(self.path).path

        try:
            body = self.read_body()
        except Exception as e:
            self.send_json(400, {"error": f"JSON inválido: {e}"})
            return

        if path == "/versions/add":
            name = body.get("name", "").strip()
            url = body.get("url", "").strip()
            if not name or not url:
                self.send_json(400, {"error": "se requieren 'name' y 'url'"})
                return

            # Auto-detectar fuente
            source = body.get("source", "")
            if not source:
                if "itch.io" in url:
                    source = "itch"
                elif "f95zone" in url:
                    source = "f95"
                else:
                    source = "unknown"

            db = db_load()
            db["games"][name] = {
                "name": name,
                "url": url,
                "source": source,
                "current_version": body.get("current_version", ""),
                "added_at": time.time(),
                "last_checked": None,
                "last_updated": None,
            }
            db_save(db)
            self.send_json(200, {"ok": True, "name": name, "source": source})

        else:
            self.send_json(404, {"error": "ruta no encontrada"})

    def do_DELETE(self):
        path = urlparse(self.path).path

        if path.startswith("/versions/"):
            name = path[len("/versions/"):]
            db = db_load()
            if name not in db["games"]:
                self.send_json(404, {"error": f"'{name}' no encontrado"})
                return
            del db["games"][name]
            db_save(db)
            self.send_json(200, {"ok": True, "deleted": name})
        else:
            self.send_json(404, {"error": "ruta no encontrada"})

    def log_message(self, fmt, *args):
        pass


def main():
    ap = argparse.ArgumentParser(description="TL Games Version Tracker")
    ap.add_argument("--port", type=int, default=8767)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    srv = HTTPServer((args.host, args.port), Handler)
    print(f"Version tracker activo en http://{args.host}:{args.port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
