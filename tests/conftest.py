import base64
import io
import json
import sys
import threading
from http.client import HTTPConnection
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))


@pytest.fixture(params=["", "/tlgames"])
def server(tmp_path, monkeypatch, request):
    for key, value in {
        "TLGAMES_BASE": request.param, "DASH_USER": "tester", "DASH_PASS": "test-password",
        "SESSION_SECRET": "test-session-secret", "INTERNAL_TOKEN": "test-internal-token",
        "TLGAMES_ENTRADA": str(tmp_path / "entrada"),
        "DEEPL_API_KEY": "", "OPENAI_API_KEY": "", "GROQ_API_KEY": "", "NTFY_TOPIC": "",
    }.items():
        monkeypatch.setenv(key, value)
    import pipeline_server as pipeline
    import pipeline_web as web

    entrada, salida = tmp_path / "entrada", tmp_path / "salida"
    entrada.mkdir()
    salida.mkdir()
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"output_dir": str(salida), "ntfy_topic": ""}))
    monkeypatch.setattr(pipeline._s, "SETTINGS_FILE", settings_path)
    monkeypatch.setattr(pipeline._s, "_cache", None)
    monkeypatch.setattr(pipeline._s, "_mtime", 0)
    monkeypatch.setattr(pipeline, "_jobs", {})
    monkeypatch.setattr(pipeline, "_jobs_order", [])
    monkeypatch.setattr(pipeline, "JOBS_HISTORY_FILE", tmp_path / "jobs.jsonl")
    monkeypatch.setattr(pipeline, "TL_TOOLS", tmp_path / "tl")
    monkeypatch.setattr(pipeline, "_dl", SimpleNamespace(
        check_quota_pool=lambda: {"available": 50000, "source": "api", "per_key": []},
        is_exhausted_today=lambda: False))

    def local_health_only(url, **kwargs):
        assert url in ("http://localhost:11434/api/tags", "http://127.0.0.1:8765/health")
        result = io.BytesIO(b'{"status":"ok","backend":"groq","model":"test"}')
        result.status = 200
        return result

    monkeypatch.setattr(pipeline.urllib.request, "urlopen", local_health_only)
    launched = []
    monkeypatch.setattr(pipeline, "run_job", lambda **kwargs: launched.append(kwargs))
    reads = []

    class CheckedReader:
        def __init__(self, stream, handler):
            self.stream, self.handler = stream, handler

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def read(self, size=-1):
            if self.handler.route() == "/upload":
                assert 0 < size <= web.CHUNK_SIZE, "El upload debe leerse por bloques acotados"
                reads.append(size)
            return self.stream.read(size)

    class CheckedHandler(pipeline.Handler):
        def setup(self):
            super().setup()
            self.rfile = CheckedReader(self.rfile, self)

    httpd = pipeline.ThreadingHTTPServer(("127.0.0.1", 0), CheckedHandler)
    worker = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    worker.start()
    basic = "Basic " + base64.b64encode(b"tester:test-password").decode()

    def call(method, path, body=None, headers=None, auth=True, prefix=True):
        merged = {"Authorization": basic} if auth else {}
        merged.update(headers or {})
        if isinstance(body, dict):
            body = json.dumps(body).encode()
            merged.setdefault("Content-Type", "application/json")
        conn = HTTPConnection(*httpd.server_address, timeout=5)
        try:
            conn.request(method, (request.param if prefix else "") + path, body, merged)
            response = conn.getresponse()
            data = response.read()
            return SimpleNamespace(status=response.status, headers=dict(response.getheaders()),
                                   body=data, json=lambda: json.loads(data))
        finally:
            conn.close()

    yield SimpleNamespace(call=call, base=request.param, httpd=httpd, entrada=entrada, salida=salida,
                          pipeline=pipeline, web=web, launched=launched, reads=reads, tmp=tmp_path)
    httpd.shutdown()
    httpd.server_close()
    worker.join(timeout=5)
