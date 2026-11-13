"""What the page can call: window.pywebview.api.<name>(...). A thin layer: every method hands off
to the controller or the assistant and turns any error into {"error": "..."} for a toast.

pywebview exposes public attributes too, so everything kept here starts with an underscore."""
from __future__ import annotations

import functools
import webbrowser

import webview

from ..core import OpError
from ..logs import log


def safe(fn):
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            result = fn(self, *args, **kwargs)
            return {"ok": True, **result} if isinstance(result, dict) else {"ok": True, "value": result}
        except (OpError, ValueError, KeyError, FileNotFoundError) as e:
            log.warning(f"API {fn.__name__}: {e}")
            return {"ok": False, "error": str(e)}
        except Exception as e:
            log.exception(f"API {fn.__name__} crashed: {e!r}")
            return {"ok": False, "error": f"Something went wrong: {e}"}
    return wrapper


def _folder_dialog(window, title: str) -> str | None:
    kind = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or webview.FOLDER_DIALOG
    chosen = window.create_file_dialog(kind)
    return chosen[0] if chosen else None


class Api:
    def __init__(self, controller, assistant):
        self._ctl = controller
        self._ai = assistant

    # ---------- start screen ----------
    @safe
    def boot(self):
        return {**self._ctl.boot(), "ai": self._ai.summary()}

    @safe
    def choose_root(self, use_default=False):
        folder = self._ctl.boot()["default_root"] if use_default else _folder_dialog(self._ctl.window, "Root folder")
        if not folder:
            return {"cancelled": True}
        return self._ctl.set_root(folder)

    @safe
    def projects(self):
        return {"projects": self._ctl.projects()}

    @safe
    def create_project(self, name, aspect="16:9"):
        return {"state": self._ctl.create(name, aspect)}

    @safe
    def open_project(self, path):
        return {"state": self._ctl.open(path)}

    @safe
    def rename_project(self, path, name):
        return {"projects": self._ctl.rename_project(path, name)}

    @safe
    def delete_project(self, path):
        return {"projects": self._ctl.delete_project(path)}

    @safe
    def open_quick(self):
        return {"state": self._ctl.open_quick()}

    @safe
    def open_folder_dialog(self):
        folder = _folder_dialog(self._ctl.window, "Open a folder")
        return {"state": self._ctl.open(folder)} if folder else {"cancelled": True}

    @safe
    def close_project(self):
        return self._ctl.close()

    # ---------- editing ----------
    @safe
    def state(self):
        return {"state": self._ctl.state()}

    @safe
    def apply(self, ops, label=""):
        return self._ctl.apply(ops, label)

    @safe
    def undo(self):
        return self._ctl.undo()

    @safe
    def redo(self):
        return self._ctl.redo()

    @safe
    def import_files(self):
        kind = getattr(getattr(webview, "FileDialog", None), "OPEN", None) or webview.OPEN_DIALOG
        chosen = self._ctl.window.create_file_dialog(kind, allow_multiple=True, file_types=(
            "Media (*.mp4;*.mov;*.mkv;*.webm;*.png;*.jpg;*.jpeg;*.webp;*.mp3;*.wav;*.m4a)", "All files (*.*)"))
        return self._ctl.add_paths(list(chosen)) if chosen else {"cancelled": True}

    @safe
    def add_paths(self, paths):
        return self._ctl.add_paths(paths)

    @safe
    def rescan(self):
        return self._ctl.rescan()

    @safe
    def delete_media(self, keys):
        return self._ctl.delete_media(list(keys))

    @safe
    def waveform(self, key):
        return {"wave": self._ctl.waveform(key)}

    # ---------- recording, export, desktop ----------
    @safe
    def record(self):
        return self._ctl.record()

    @safe
    def export_start(self, name, quality="normal"):
        return self._ctl.export_start(name, quality)

    @safe
    def export_cancel(self):
        self._ctl.export_cancel()

    @safe
    def reveal(self, path):
        self._ctl.reveal(path)

    @safe
    def open_path(self, path):
        self._ctl.open_path(path)

    @safe
    def open_url(self, url):
        if isinstance(url, str) and url.startswith("https://"):
            webbrowser.open(url)

    @safe
    def save_prefs(self, prefs):
        self._ctl.cfg.editor = {**self._ctl.cfg.editor, **(prefs or {})}
        self._ctl.cfg.save()

    @safe
    def prefs(self):
        return {"prefs": self._ctl.cfg.editor}

    # ---------- AI ----------
    @safe
    def ai_summary(self):
        return self._ai.summary()

    @safe
    def ai_check(self, name):
        return self._ai.check(name)

    @safe
    def ai_disconnect(self, name):
        return self._ai.disconnect(name)

    @safe
    def ai_options(self, patch):
        return self._ai.set_options(patch)

    @safe
    def use_whisper(self, size="small"):
        return {"transcriber": self._ai.use_whisper(size)}

    @safe
    def use_assemblyai(self, key):
        return self._ai.use_assemblyai(key)

    @safe
    def skip_transcriber(self):
        return {"transcriber": self._ai.skip_transcriber()}

    @safe
    def transcribe(self, keys=None):
        return self._ai.transcribe(keys)

    @safe
    def chat_history(self):
        return {"chat": self._ai.history()}

    @safe
    def chat_clear(self):
        return {"chat": self._ai.clear()}

    @safe
    def chat_send(self, message, playhead=0.0, selection=None):
        return self._ai.send(message, playhead, selection)
