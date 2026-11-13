"""A small web server on 127.0.0.1 for the editor window: the UI files, and the project's media
with HTTP Range (a <video> needs it to seek).

Media is only served under a per-session token and only for files the editor allowed (the
project's media and its cache folder), so nothing else on the computer can be read through it."""
from __future__ import annotations

import mimetypes
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from ..logs import log

UI_DIR = Path(__file__).resolve().parent / "ui"
CHUNK = 1024 * 512
TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml",
         ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
         ".mkv": "video/x-matroska", ".m4a": "audio/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav",
         ".json": "application/json", ".woff2": "font/woff2"}


class Allowed:
    """The files and folders the server may hand out."""

    def __init__(self):
        self._files: set[str] = set()
        self._dirs: set[str] = set()
        self._lock = threading.Lock()

    @staticmethod
    def _norm(path) -> str:
        return str(Path(path).resolve()).lower()

    def file(self, path) -> None:
        with self._lock:
            self._files.add(self._norm(path))

    def folder(self, path) -> None:
        with self._lock:
            self._dirs.add(self._norm(path))

    def reset(self) -> None:
        with self._lock:
            self._files.clear()
            self._dirs.clear()

    def ok(self, path: Path) -> bool:
        p = self._norm(path)
        with self._lock:
            return p in self._files or any(p.startswith(d.rstrip("\\/") + "\\") for d in self._dirs)


class Server:
    def __init__(self):
        self.token = secrets.token_urlsafe(16)
        self.allowed = Allowed()
        handler = type("Handler", (_Handler,), {"server_ref": self})
        self.httpd = _QuietServer(("127.0.0.1", 0), handler)
        self.httpd.daemon_threads = True

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/"

    def media_url(self, path) -> str:
        """The URL a page uses for a file (it must also be allowed)."""
        return f"{self.url}m/{self.token}/{quote(str(Path(path).resolve()).replace(chr(92), '/'))}"

    def start(self) -> None:
        threading.Thread(target=self.httpd.serve_forever, name="editor-server", daemon=True).start()
        log.info(f"EDITOR server on {self.url}")

    def stop(self) -> None:
        self.httpd.shutdown()


class _QuietServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        import sys
        if not isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            super().handle_error(request, client_address)


class _Handler(BaseHTTPRequestHandler):
    server_ref: Server
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # the log stays quiet: a video makes hundreds of requests
        pass

    def do_GET(self):
        self._serve(head=False)

    def do_HEAD(self):
        self._serve(head=True)

    def _serve(self, head: bool):
        path = unquote(urlsplit(self.path).path)
        srv = self.server_ref
        if path.startswith("/m/"):
            _, _, token, rest = path.split("/", 3) if path.count("/") >= 3 else ("", "", "", "")
            target = Path(rest.replace("/", "\\"))
            if token != srv.token or not srv.allowed.ok(target):
                return self._error(403)
            return self._file(target, head, cache="no-cache")
        rel = path.lstrip("/") or "index.html"
        target = (UI_DIR / rel).resolve()
        if UI_DIR not in target.parents and target != UI_DIR / "index.html":
            return self._error(403)
        return self._file(target, head, cache="no-store")

    def _error(self, code: int):
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _file(self, target: Path, head: bool, cache: str):
        try:
            size = target.stat().st_size
        except OSError:
            return self._error(404)
        ctype = TYPES.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        start, end = 0, size - 1
        ranged = self.headers.get("Range")
        if ranged and ranged.startswith("bytes="):
            a, _, b = ranged[6:].split(",")[0].partition("-")
            try:
                if a:
                    start, end = int(a), int(b) if b else size - 1
                else:
                    start, end = max(0, size - int(b)), size - 1
            except ValueError:
                return self._error(416)
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                return self.end_headers()
            end = min(end, size - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        if head:
            return
        try:
            with open(target, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(CHUNK, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (ConnectionError, OSError):
            pass  # the page moved on (a seek cancels the old request)
