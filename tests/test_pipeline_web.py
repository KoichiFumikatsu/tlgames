import base64
import io
import json
import socket
import stat
import time
import zipfile
from http.client import HTTPConnection
from urllib.parse import quote, urlencode

import pytest


def make_zip(entries):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_STORED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return data.getvalue()


def upload(server, entries, name="Example.zip", **kwargs):
    return server.call("POST", "/upload", make_zip(entries),
                       {"Content-Type": "application/zip", "X-Nombre": quote(name)}, **kwargs)


@pytest.mark.parametrize("method,path", [
    ("GET", "/"), ("GET", "/dashboard"), ("GET", "/jobs"), ("GET", "/settings"),
    ("GET", "/entrada"), ("GET", "/salida"), ("GET", "/salida/game.zip"),
    ("GET", "/pipeline/123"), ("GET", "/pipeline/123/events"),
    ("GET", "/pipeline/123/diagnostico"), ("POST", "/pipeline"), ("POST", "/detect"),
    ("POST", "/settings"), ("POST", "/entrada/borrar"), ("POST", "/upload"),
])
def test_auth_required_even_on_loopback(server, method, path):
    response = server.call(method, path, auth=False)
    assert response.status == 401
    if path not in ("/", "/dashboard"):
        assert response.headers["WWW-Authenticate"].startswith("Basic ")


def test_prefix_and_public_routes(server):
    for path in ("/health", "/login"):
        assert server.call("GET", path, auth=False).status == 200
    health = server.call("GET", "/health", auth=False).json()
    assert health["deepl"]["available"] == 50000
    assert health["qa"]["backend"] == "groq"
    assert health["openai"]["available_usd"] == 1.5
    assert server.call("GET", "/jobs", prefix=False).status == 200
    page = server.call("GET", "/").body.decode("utf-8-sig")
    assert "{B}" not in page
    assert f"const B = '{server.base}';" in page
    assert f'href="{server.base}/#subir"' in page
    login = server.call("GET", "/login", auth=False).body.decode()
    assert f'action="{server.base}/login"' in login
    if server.base:
        assert server.call("GET", server.base, prefix=False).status == 200
        assert server.call("GET", server.base + "x/jobs", prefix=False).status == 404


def test_basic_and_internal_auth(server):
    assert server.call("GET", "/jobs").status == 200
    assert server.call("GET", "/jobs", auth=False,
                       headers={"X-Internal-Token": "test-internal-token"}).status == 200
    for headers in ({"X-Internal-Token": "wrong"}, {"Authorization": "Basic !!"},
                    {"Authorization": "Basic " + base64.b64encode(b"tester:wrong").decode()},
                    {"Cookie": "tlgames_sid=invalid"}):
        assert server.call("GET", "/jobs", auth=False, headers=headers).status == 401


def test_login_cookie_and_expiration(server, monkeypatch):
    response = server.call("POST", "/login", urlencode({"user": "tester", "password": "test-password"}),
                           {"Content-Type": "application/x-www-form-urlencoded"}, auth=False)
    assert response.status == 303
    assert response.headers["Location"] == server.base + "/"
    cookie = response.headers["Set-Cookie"]
    assert f"Path={server.base or '/'};" in cookie
    assert all(flag in cookie for flag in ("HttpOnly", "Secure", "SameSite=Strict"))
    cookie = cookie.split(";")[0]
    assert server.call("GET", "/jobs", headers={"Cookie": cookie}, auth=False).status == 200
    assert server.call("GET", "/jobs", headers={"Cookie": cookie + "0"}, auth=False).status == 401
    now = time.time()
    monkeypatch.setattr(server.web.time, "time", lambda: now + server.web.SESSION_AGE + 1)
    assert server.call("GET", "/jobs", headers={"Cookie": cookie}, auth=False).status == 401


def test_fail_closed_and_bad_login(server, monkeypatch):
    response = server.call("POST", "/login", urlencode({"user": "tester", "password": "wrong"}), auth=False)
    assert response.status == 401
    assert "Set-Cookie" not in response.headers
    for key in ("DASH_USER", "DASH_PASS", "SESSION_SECRET"):
        with monkeypatch.context() as patch:
            patch.delenv(key)
            with pytest.raises(ValueError, match=key):
                server.web.validate_auth_config()
    monkeypatch.setenv("DASH_USER", "")
    monkeypatch.setenv("DASH_PASS", "")
    empty_basic = "Basic " + base64.b64encode(b":").decode()
    assert server.call("GET", "/jobs", headers={"Authorization": empty_basic}).status == 401


def test_streamed_upload_unwraps_single_root(server):
    payload = b"x" * (server.web.CHUNK_SIZE * 2 + 31)
    result = upload(server, {"My Game/game/script.rpy": payload}, "ignored.zip")
    assert result.status == 201, result.body
    data = result.json()
    assert data["nombre"] == "My Game"
    assert data["size"] == len(payload)
    assert (server.entrada / "My Game/game/script.rpy").read_bytes() == payload
    assert len(server.reads) >= 3
    assert max(server.reads) <= server.web.CHUNK_SIZE
    assert not list(server.entrada.glob(".upload-*"))


def test_flat_zip_name_sanitized_and_conflict(server):
    result = upload(server, {"Game.exe": b"game", "game/script.rpy": b"script"}, "../Juego: prueba.zip")
    assert result.status == 201, result.body
    name = result.json()["nombre"]
    assert all(c not in name for c in "/\\:")
    assert (server.entrada / name / "Game.exe").read_bytes() == b"game"
    assert upload(server, {"Game.exe": b"overwrite"}, name + ".zip").status == 409
    assert (server.entrada / name / "Game.exe").read_bytes() == b"game"


def test_filename_header(server):
    result = server.call("POST", "/upload", make_zip({"script.rpy": b"test"}),
                         {"Content-Type": "application/zip", "Content-Disposition": 'attachment; filename="Title.zip"'})
    assert result.status == 201
    assert result.json()["nombre"] == "Title"


@pytest.mark.parametrize("name", ["../escape", "safe/../../escape", "/absolute", "C:/escape",
                                  "\\absolute", "safe\\..\\escape", "safe/C:escape"])
def test_zip_rejects_unsafe_paths(server, name):
    response = upload(server, {"normal/file.txt": b"ok", name: b"evil"})
    assert response.status == 400
    assert list(server.entrada.iterdir()) == []
    assert not (server.tmp / "escape").exists()


def test_zip_rejects_symlink(server):
    link = zipfile.ZipInfo("link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    response = upload(server, {link: b"../../outside"})
    assert response.status == 400
    assert list(server.entrada.iterdir()) == []


def test_invalid_zip_and_body(server):
    for data in (b"not a zip", make_zip({})):
        assert server.call("POST", "/upload", data, {"Content-Type": "application/zip"}).status == 400
    assert server.call("POST", "/upload", b"bad", {"Content-Type": "multipart/form-data"}).status == 400
    assert server.call("POST", "/pipeline", b"[]").status == 400
    assert server.call("POST", "/settings", headers={"Content-Length": "-1"}).status == 400
    assert list(server.entrada.iterdir()) == []


def test_upload_does_not_block_other_requests(server):
    data = make_zip({"script.rpy": b"sample"})
    conn = HTTPConnection(*server.httpd.server_address, timeout=5)
    conn.putrequest("POST", server.base + "/upload")
    conn.putheader("Content-Type", "application/zip")
    conn.putheader("Content-Length", str(len(data)))
    conn.putheader("X-Internal-Token", "test-internal-token")
    conn.endheaders()
    conn.send(data[:10])
    try:
        assert server.call("GET", "/jobs").status == 200
        conn.send(data[10:])
        response = conn.getresponse()
        assert response.status == 201, response.read()
        response.read()
    finally:
        conn.close()


def test_incomplete_upload_cleans_staging(server):
    conn = HTTPConnection(*server.httpd.server_address, timeout=5)
    conn.request("POST", server.base + "/upload", b"partial",
                 {"Content-Type": "application/zip", "Content-Length": "100",
                  "X-Internal-Token": "test-internal-token"})
    conn.sock.shutdown(socket.SHUT_WR)
    try:
        response = conn.getresponse()
        assert response.status == 400
        response.read()
        assert list(server.entrada.iterdir()) == []
    finally:
        conn.close()


def test_entrada_jobs_packages_delete(server):
    game = server.entrada / "Title"
    game.mkdir()
    (game / "script.rpy").write_text("sample")
    (server.salida / "Title-v1.2-spanish.zip").write_bytes(b"package")
    job = {"job_id": "old-job", "game_path": str(game), "status": "done", "started_at": 1,
           "diagnose_report": "All checks passed"}
    server.pipeline.JOBS_HISTORY_FILE.write_text(json.dumps(job) + "\n")
    entry = server.call("GET", "/entrada").json()["entrada"][0]
    assert entry["nombre"] == "Title"
    assert entry["paquete"] is True
    assert entry["job"]["job_id"] == "old-job"
    assert server.call("GET", "/pipeline/old-job/diagnostico").body == b"All checks passed"
    assert server.call("POST", "/entrada/borrar", {"nombre": "Title"}).status == 200
    assert not game.exists()
    assert (server.salida / "Title-v1.2-spanish.zip").exists()
    assert server.call("GET", "/entrada").json() == {"entrada": [], "apks_sueltos": []}


def test_pipeline_contract_and_delete_running(server):
    game = server.entrada / "Active"
    game.mkdir()
    response = server.call("POST", "/pipeline", {"path": str(game), "name": "Active",
                                                "provider": "auto", "lang": "Spanish"})
    assert response.status == 202
    job_id = response.json()["job_id"]
    assert response.json()["poll"] == f"{server.base}/pipeline/{job_id}"
    job = server.call("GET", f"/pipeline/{job_id}").json()
    assert job["game_name"] == "Active"
    assert job["lang"] == "Spanish"
    assert job["provider"] == "auto"
    assert server.call("GET", f"/pipeline/{job_id}/events").json() == {"events": []}
    assert server.call("POST", "/entrada/borrar", {"nombre": "Active"}).status == 409
    assert server.call("POST", "/pipeline", {"path": str(game / ".")}).status == 409
    assert game.exists()


@pytest.mark.parametrize("name", ["..", "../outside", "/", "C:\\", "Title/../.."])
def test_delete_rejects_escape(server, name):
    assert server.call("POST", "/entrada/borrar", {"nombre": name}).status == 400
    assert server.entrada.is_dir()


def test_salida_list_and_streamed_download(server, monkeypatch):
    data = b"z" * (server.web.CHUNK_SIZE * 2 + 13)
    name = "Juego español.zip"
    (server.salida / name).write_bytes(data)
    (server.salida / "private.txt").write_text("not a package")
    listing = server.call("GET", "/salida").json()["salida"]
    assert len(listing) == 1
    assert listing[0]["nombre"] == name
    assert listing[0]["size"] == len(data)
    assert listing[0]["mtime"] > 0
    assert listing[0]["download"] == server.base + "/salida/" + quote(name)
    original_copy = server.web.shutil.copyfileobj
    chunks = []

    def checked_copy(source, dest, length):
        class Writer:
            def write(self, chunk):
                assert len(chunk) <= server.web.CHUNK_SIZE
                chunks.append(len(chunk))
                return dest.write(chunk)
        return original_copy(source, Writer(), length)

    monkeypatch.setattr(server.web.shutil, "copyfileobj", checked_copy)
    response = server.call("GET", "/salida/" + quote(name))
    assert response.status == 200
    assert response.body == data
    assert len(chunks) == 3
    assert response.headers["Content-Type"] == "application/zip"
    assert response.headers["Content-Disposition"].startswith("attachment;")
    assert server.call("GET", "/salida/private.txt").status == 404


@pytest.mark.parametrize("name", ["../outside.zip", "%2e%2e%2foutside.zip", "%2foutside.zip",
                                  "..%5coutside.zip", "C%3a%5coutside.zip", "%00.zip"])
def test_download_rejects_escape(server, name):
    (server.tmp / "outside.zip").write_bytes(b"secret")
    response = server.call("GET", "/salida/" + name)
    assert response.status == 404
    assert b"secret" not in response.body


def test_filesystem_symlink_escape(server):
    outside = server.tmp / "outside.zip"
    outside.write_bytes(b"secret")
    try:
        (server.salida / "link.zip").symlink_to(outside)
        (server.entrada / "link").symlink_to(server.salida, target_is_directory=True)
    except OSError:
        pytest.skip("El sistema no permite crear symlinks con este usuario")
    assert server.call("GET", "/salida").json()["salida"] == []
    assert server.call("GET", "/salida/link.zip").status == 404
    assert server.call("GET", "/entrada").json()["entrada"] == []
    assert server.call("POST", "/entrada/borrar", {"nombre": "link"}).status == 400
    assert outside.exists()


def test_legacy_detect_settings_health(server):
    game = server.entrada / "Game"
    (game / "game").mkdir(parents=True)
    (game / "game/script.rpy").write_text('label start:\n    "Hello"\n')
    assert server.call("POST", "/detect", {"path": str(game)}).json()["engine"] == "renpy"
    assert server.call("GET", "/settings").json()["output_dir"] == str(server.salida)
    assert server.call("POST", "/settings", {"output_dir": str(server.salida), "default_lang": "Spanish"}).status == 200
    assert server.call("POST", "/health", {}, auth=False).json() == {"status": "ok"}


def test_base_validation(monkeypatch):
    from pipeline_web import _base
    monkeypatch.setenv("TLGAMES_BASE", "/tlgames/")
    assert _base() == "/tlgames"
    for invalid in ("tlgames", "//tlgames", "/../secret", "/x'", "/x?next=1"):
        monkeypatch.setenv("TLGAMES_BASE", invalid)
        with pytest.raises(ValueError):
            _base()


def test_cross_origin_mutations_rejected(server):
    game = server.entrada / "Keep"
    game.mkdir()
    response = server.call("POST", "/entrada/borrar", {"nombre": "Keep"},
                           {"Origin": "https://another-site.example"})
    assert response.status == 403
    assert game.is_dir()
    origin = "http://%s:%s" % server.httpd.server_address
    assert server.call("POST", "/entrada/borrar", {"nombre": "Keep"}, {"Origin": origin}).status == 200


@pytest.mark.parametrize("returncode", [0, 1])
def test_packages_published_only_when_complete(server, monkeypatch, returncode):
    from pathlib import Path
    game = server.entrada / "Game"
    game.mkdir()
    final = server.salida / "Game-spanish.zip"
    final.write_bytes(b"previous complete package")
    monkeypatch.setattr(server.pipeline, "copy_to_games_tl", lambda *args: None)
    new_zip = make_zip({"Game/game/script.rpy": b"translated"})

    class Process:
        def __init__(self, cmd, **kwargs):
            pending = Path(cmd[3])
            assert pending.suffix == ".part"
            pending.write_bytes(new_zip if returncode == 0 else b"incomplete")
            listing = server.call("GET", "/salida").json()["salida"]
            assert [p["nombre"] for p in listing] == [final.name]
            assert server.call("GET", "/salida/" + final.name).body == b"previous complete package"
            self.stdout = iter([])
            self.returncode = returncode

        def wait(self, **kwargs):
            return self.returncode

    monkeypatch.setattr(server.pipeline.subprocess, "Popen", Process)
    job = {"progress": [], "game_name": "Game"}
    tracker = server.pipeline.StageTracker(job, "renpy")
    server.pipeline._v2_package(job, game, {}, tracker)
    assert not list(server.salida.glob("*.part"))
    assert final.read_bytes() == (new_zip if returncode == 0 else b"previous complete package")
    if returncode == 0:
        assert job["zip_path"] == str(final)
