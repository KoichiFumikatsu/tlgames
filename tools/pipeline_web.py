"""Autenticación y transferencia de juegos; solo biblioteca estándar."""

import base64
import binascii
import hashlib
import hmac
import html
import os
import re
import shutil
import stat
import tempfile
import threading
import time
import zipfile
import zlib
from email.message import Message
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

CHUNK_SIZE = 1024 * 1024
SESSION_AGE = 12 * 60 * 60
FILES_LOCK = threading.RLock()


def _base():
    value = os.environ.get("TLGAMES_BASE", "").strip().rstrip("/")
    if value and not re.fullmatch(r"(?:/[A-Za-z0-9_-]+)+", value):
        raise ValueError("TLGAMES_BASE debe ser vacío o un prefijo como /tlgames")
    return value


def validate_auth_config():
    _base()
    missing = [key for key in ("DASH_USER", "DASH_PASS", "SESSION_SECRET")
               if not os.environ.get(key)]
    if missing:
        raise ValueError("Faltan variables obligatorias: " + ", ".join(missing))


def _equal(a, b):
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _credentials_ok(user, password):
    expected_user = os.environ.get("DASH_USER", "")
    expected_pass = os.environ.get("DASH_PASS", "")
    return bool(expected_user and expected_pass) and (
        _equal(user, expected_user) & _equal(password, expected_pass))


def _make_cookie(user):
    payload = base64.urlsafe_b64encode(
        f"{user}:{int(time.time()) + SESSION_AGE}".encode()).decode()
    signature = hmac.new(os.environ["SESSION_SECRET"].encode(),
                         payload.encode(), hashlib.sha256).hexdigest()
    return payload + "." + signature


def _check_cookie(token):
    secret = os.environ.get("SESSION_SECRET", "")
    if not secret or not os.environ.get("DASH_USER") or not os.environ.get("DASH_PASS"):
        return False
    try:
        payload, signature = token.split(".")
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not _equal(signature, expected):
            return False
        user, expiry = base64.urlsafe_b64decode(payload).decode().rsplit(":", 1)
        return _equal(user, os.environ["DASH_USER"]) and time.time() < int(expiry)
    except (ValueError, UnicodeError, binascii.Error):
        return False


def entrada_dir():
    return Path(os.environ.get("TLGAMES_ENTRADA", "~/Documents/games-tl/entrada")).expanduser().resolve()


def safe_child(root, name):
    if (not isinstance(name, str) or not name or name in (".", "..")
            or any(c in name for c in '/\\:\x00') or name.endswith((" ", "."))):
        raise ValueError("Nombre inválido")
    root = root.resolve()
    target = root / name
    if target.is_symlink() or target.is_junction() or target.resolve().parent != root:
        raise ValueError("Ruta fuera de la carpeta permitida")
    return target


def _game_name(name):
    name = re.sub(r"[^\w .()-]", "_", name, flags=re.UNICODE).strip(" .")[:120].rstrip(" .")
    if not name:
        raise ValueError("Nombre de juego vacío")
    if name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        name = "_" + name
    return name


def copy_upload(source, destination, length):
    remaining = length
    while remaining:
        chunk = source.read(min(CHUNK_SIZE, remaining))
        if not chunk:
            raise ValueError("Subida incompleta")
        destination.write(chunk)
        remaining -= len(chunk)


def extract_game(archive, staging, fallback_name):
    with zipfile.ZipFile(archive) as zf:
        members = zf.infolist()
        if not members or not any(not m.is_dir() for m in members):
            raise ValueError("El ZIP no contiene archivos")
        for member in members:
            name = member.orig_filename
            parts = name.replace("\\", "/").rstrip("/").split("/")
            mode = stat.S_IFMT(member.external_attr >> 16)
            if (name.startswith(("/", "\\")) or "\x00" in name or ":" in name
                    or any(p in ("", ".", "..") or p.endswith((" ", ".")) for p in parts)
                    or mode not in (0, stat.S_IFREG, stat.S_IFDIR)):
                raise ValueError("Entrada insegura en el ZIP")
        # Validar todo el índice antes de escribir cualquier archivo extraído.
        for member in members:
            target = staging.joinpath(*member.filename.replace("\\", "/").split("/"))
            if not target.resolve().is_relative_to(staging.resolve()):
                raise ValueError("Entrada insegura en el ZIP")
            if member.is_dir() or member.filename.endswith("\\"):
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as source, target.open("xb") as dest:
                    shutil.copyfileobj(source, dest, CHUNK_SIZE)
                if member.create_system == 3:
                    target.chmod(0o755 if member.external_attr >> 16 & 0o111 else 0o644)
        children = list(staging.iterdir())
        if len(children) == 1 and children[0].is_dir():
            return children[0], _game_name(children[0].name)
        return staging, _game_name(fallback_name)


class PublicHandlerMixin:
    def route(self):
        path = urlsplit(self.path).path
        base = _base()
        if base and (path == base or path.startswith(base + "/")):
            path = path[len(base):] or "/"
        return path

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        super().end_headers()

    def _authed(self):
        internal = os.environ.get("INTERNAL_TOKEN", "")
        token = self.headers.get("X-Internal-Token", "")
        if internal and token and _equal(internal, token):
            return True
        try:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            if "tlgames_sid" in cookies and _check_cookie(cookies["tlgames_sid"].value):
                return True
        except CookieError:
            pass
        auth = self.headers.get("Authorization", "")
        try:
            scheme, encoded = auth.split(" ", 1)
            if scheme.lower() == "basic":
                user, password = base64.b64decode(encoded, validate=True).decode().split(":", 1)
                return _credentials_ok(user, password)
        except (ValueError, UnicodeError, binascii.Error):
            pass
        return False

    def authorize(self, path):
        if path in ("/login", "/health") or self._authed():
            return True
        self.close_connection = True
        self._discard_small_body()
        if self.command == "GET" and path in ("/", "/dashboard"):
            self._serve_login(401)
        else:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="TL Games", charset="UTF-8"')
            self.send_header("Content-Type", "application/json; charset=utf-8")
            body = b'{"error":"Autenticacion requerida"}'
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        return False

    def _discard_small_body(self):
        # Evita un reset TCP al responder antes de consumir cuerpos pequeños rechazados.
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if 0 < length <= CHUNK_SIZE and not self.headers.get("Transfer-Encoding"):
                self.connection.settimeout(2)
                self.rfile.read(length)
        except (ValueError, OSError):
            pass

    def _serve_login(self, code=200, error=""):
        page = (Path(__file__).parent / "login.html").read_text(encoding="utf-8")
        self.send_html(code, page.replace("{B}", _base()).replace("{ERROR}", html.escape(error)))

    def _read_small_body(self):
        if self.headers.get("Transfer-Encoding"):
            raise ValueError("Se requiere Content-Length")
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 <= length <= CHUNK_SIZE:
            raise ValueError("Cuerpo demasiado grande o tamaño inválido")
        self.connection.settimeout(60)
        data = self.rfile.read(length)
        if len(data) != length:
            raise ValueError("Cuerpo incompleto")
        return data

    def _do_login(self):
        try:
            form = parse_qs(self._read_small_body().decode())
        except (ValueError, OSError):
            self.close_connection = True
            return self._serve_login(400, "Formulario inválido")
        user, password = form.get("user", [""])[0], form.get("password", [""])[0]
        if not _credentials_ok(user, password):
            return self._serve_login(401, "Usuario o contraseña incorrectos")
        if not os.environ.get("SESSION_SECRET"):
            return self._serve_login(503, "Falta configurar SESSION_SECRET")
        self.send_response(303)
        self.send_header("Location", _base() + "/")
        self.send_header("Set-Cookie", f"tlgames_sid={_make_cookie(user)}; Path={_base() or '/'}; "
                         f"HttpOnly; Secure; SameSite=Strict; Max-Age={SESSION_AGE}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def same_origin(self):
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc != self.headers.get("Host"):
            self.close_connection = True
            self._discard_small_body()
            self.send_json(403, {"error": "Origen de la petición no permitido"})
            return False
        return True

    def _upload(self):
        try:
            if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
                raise ValueError("Se requiere un único Content-Length")
            length = int(self.headers["Content-Length"])
            if length <= 0:
                raise ValueError("El ZIP está vacío")
            ctype = self.headers.get_content_type()
            if ctype not in ("application/zip", "application/octet-stream", "application/x-zip-compressed", "application/vnd.android.package-archive"):
                self._discard_small_body()
                raise ValueError("Enviar el ZIP como cuerpo binario, sin multipart")
            disposition = Message()
            disposition["Content-Disposition"] = self.headers.get("Content-Disposition", "")
            crudo = unquote(self.headers.get("X-Nombre") or disposition.get_filename() or "juego.zip")
            root = entrada_dir()
            root.mkdir(parents=True, exist_ok=True)
            self.connection.settimeout(120)
            if ctype == "application/vnd.android.package-archive" or crudo.lower().endswith(".apk"):
                return self._upload_apk(root, _game_name(re.sub(r"(?i)\.apk$", "", crudo)), length)
            name = _game_name(re.sub(r"(?i)\.zip$", "", crudo))
            with tempfile.TemporaryDirectory(prefix=".upload-", dir=root) as temp:
                temp = Path(temp)
                archive = temp / "upload.zip"
                with archive.open("wb") as dest:
                    copy_upload(self.rfile, dest, length)
                staging = temp / "game"
                staging.mkdir()
                source, name = extract_game(archive, staging, name)
                size = sum(p.stat().st_size for p in source.rglob("*") if p.is_file())
                with FILES_LOCK:
                    target = safe_child(root, name)
                    if target.exists():
                        return self.send_json(409, {"error": "Ya existe un juego con ese nombre"})
                    source.rename(target)
            self.send_json(201, {"nombre": name, "size": size, "zip_size": length, "path": str(target)})
        except (ValueError, OSError, zipfile.BadZipFile, zlib.error, EOFError, RuntimeError) as exc:
            self.close_connection = True
            self.send_json(400, {"error": str(exc)})

    def _upload_apk(self, root, name, length):
        """APK oficial del juego (Ren'Py): queda en entrada/<nombre>.apk, sin extraer. Se vincula a un juego después."""
        with tempfile.NamedTemporaryFile(prefix=".upload-", suffix=".apk", dir=root, delete=False) as tmp:
            temp = Path(tmp.name)
            copy_upload(self.rfile, tmp, length)
        try:
            with zipfile.ZipFile(temp) as zf:
                if not any(n.startswith("assets/x-game/") for n in zf.namelist()[:5000]) and "AndroidManifest.xml" not in zf.namelist():
                    raise ValueError("El archivo no parece un APK de Ren'Py")
            with FILES_LOCK:
                target = safe_child(root, name + ".apk")
                temp.replace(target)
        except Exception:
            temp.unlink(missing_ok=True)
            raise
        self.send_json(201, {"nombre": name, "apk": target.name, "size": length, "path": str(target)})

    def _vincular_apk(self, body):
        """Renombra entrada/<apk>.apk a entrada/<juego>.apk para que el pipeline lo encuentre."""
        try:
            root = entrada_dir()
            juego = safe_child(root, body.get("nombre"))
            apk = safe_child(root, body.get("apk"))
            with FILES_LOCK:
                if not juego.is_dir():
                    return self.send_json(404, {"error": "Juego no encontrado"})
                if not apk.is_file() or apk.suffix.lower() != ".apk":
                    return self.send_json(404, {"error": "APK no encontrado"})
                destino = juego.with_suffix(".apk") if juego.suffix != ".apk" else juego.parent / (juego.name + ".apk")
                destino = root / f"{juego.name}.apk"
                if apk != destino:
                    apk.replace(destino)
            self.send_json(200, {"ok": True, "apk": destino.name})
        except (ValueError, OSError) as exc:
            self.send_json(400, {"error": str(exc)})

    def _apks_sueltos(self, root, juegos):
        """APKs en entrada/ que no corresponden a ninguna carpeta de juego (todavía sin vincular)."""
        nombres = {j + ".apk" for j in juegos}
        out = []
        for p in sorted(root.glob("*.apk")) if root.is_dir() else []:
            if p.is_file() and not p.name.startswith(".upload-") and p.name not in nombres:
                out.append({"nombre": p.name, "size": p.stat().st_size})
        return out

    def _list_salida(self):
        root = self.output_dir()
        result = []
        if root.is_dir():
            for path in sorted(root.iterdir()):
                try:
                    path = safe_child(root, path.name)
                except ValueError:
                    continue
                if path.is_file() and path.suffix.lower() in (".zip", ".apk"):
                    info = path.stat()
                    result.append({"nombre": path.name, "size": info.st_size, "mtime": info.st_mtime, "tipo": "android" if path.suffix.lower() == ".apk" else "pc",
                                   "download": _base() + "/salida/" + quote(path.name, safe="")})
        return result

    def _list_entrada(self):
        root = entrada_dir()
        packages = self._list_salida()
        jobs = self.jobs_snapshot()
        result = []
        with FILES_LOCK:
            for path in sorted(root.iterdir()) if root.is_dir() else []:
                try:
                    path = safe_child(root, path.name)
                except ValueError:
                    continue
                if not path.is_dir() or path.name.startswith(".upload-"):
                    continue
                matches = [j for j in jobs if Path(j.get("game_path", "")).resolve() == path.resolve()]
                job = max(matches, key=lambda j: j.get("started_at", 0), default=None)
                names = [p["nombre"] for p in packages if (
                    p["nombre"] in (path.name + "-spanish.zip", path.name + "-spanish.apk")
                    or re.fullmatch(re.escape(path.name) + r"-v.+-spanish\.(zip|apk)", p["nombre"])
                    or any(j.get("zip_path") and Path(j["zip_path"]).name == p["nombre"] for j in matches)
                    or any(j.get("apk_path") and Path(j["apk_path"]).name == p["nombre"] for j in matches))]
                result.append({"nombre": path.name, "path": str(path), "paquete": bool(names),
                               "paquetes": names, "job": job, "apk": (root / f"{path.name}.apk").is_file()})
        self.send_json(200, {"entrada": result, "apks_sueltos": self._apks_sueltos(root, [r["nombre"] for r in result])})

    def _delete_entrada(self, body):
        try:
            target = safe_child(entrada_dir(), body.get("nombre"))
            with FILES_LOCK:
                if not target.is_dir():
                    return self.send_json(404, {"error": "Juego no encontrado"})
                if any(j.get("status") == "running" and
                       Path(j.get("game_path", "")).resolve().is_relative_to(target.resolve())
                       for j in self.jobs_snapshot()):
                    return self.send_json(409, {"error": "El juego tiene una traducción en curso"})
                shutil.rmtree(target)
            self.send_json(200, {"ok": True, "nombre": target.name})
        except (ValueError, OSError) as exc:
            self.send_json(400, {"error": str(exc)})

    def _download(self, name):
        try:
            path = safe_child(self.output_dir(), unquote(name))
            if path.suffix.lower() not in (".zip", ".apk") or not path.is_file():
                return self.send_json(404, {"error": "Paquete no encontrado"})
            source = path.open("rb")
        except (ValueError, OSError):
            return self.send_json(404, {"error": "Paquete no encontrado"})
        with source:
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.android.package-archive" if path.suffix.lower() == ".apk" else "application/zip")
            self.send_header("Content-Length", str(os.fstat(source.fileno()).st_size))
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(path.name, safe=""))
            self.end_headers()
            shutil.copyfileobj(source, self.wfile, CHUNK_SIZE)
