#!/usr/bin/env python3
"""
Servidor HTTP mínimo para integración con n8n.
Expone el QA de traducciones Ren'Py vía REST.

Endpoints:
    POST /qa   { "file": "/ruta/al/archivo.rpy" }
               { "dir":  "/ruta/al/directorio/" }
    GET  /health

Puerto: 8765 (configurable con --port)
"""

from __future__ import annotations

import json
import sys
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# qa_renpy debe estar en el mismo directorio
sys.path.insert(0, str(Path(__file__).parent))
import qa_renpy


class QAHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[qa_server] {fmt % args}")

    def send_json(self, status: int, body: dict):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {"status": "ok", "model": qa_renpy.MODEL})
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/qa":
            self.send_json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError as e:
            self.send_json(400, {"error": f"JSON inválido: {e}"})
            return

        file_path = body.get("file")
        dir_path = body.get("dir")

        if not file_path and not dir_path:
            self.send_json(400, {"error": "Se requiere 'file' o 'dir' en el body"})
            return

        try:
            if dir_path:
                target = Path(dir_path)
                if not target.is_dir():
                    self.send_json(400, {"error": f"Directorio no encontrado: {dir_path}"})
                    return
                results = qa_renpy.qa_directory(target)
            else:
                target = Path(file_path)
                if not target.exists():
                    self.send_json(400, {"error": f"Archivo no encontrado: {file_path}"})
                    return
                results = [qa_renpy.qa_file(target)]

            report = qa_renpy.render_report(results)
            total_issues = sum(len(r["issues"]) for r in results)

            self.send_json(200, {
                "issues_total": total_issues,
                "files": len(results),
                "report": report,
                "results": results,
            })

        except Exception:
            tb = traceback.format_exc()
            print(tb)
            self.send_json(500, {"error": "Error interno", "detail": tb})


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--model", default=qa_renpy.MODEL)
    args = parser.parse_args()

    qa_renpy.MODEL = args.model
    server = HTTPServer(("0.0.0.0", args.port), QAHandler)
    print(f"[qa_server] escuchando en http://0.0.0.0:{args.port}")
    print(f"[qa_server] modelo: {qa_renpy.MODEL}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[qa_server] detenido")


if __name__ == "__main__":
    main()
