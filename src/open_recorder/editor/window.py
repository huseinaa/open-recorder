"""Open the editor window: a pywebview (Edge WebView2) window showing the page from our own local
server, with the Python API attached and file drops from Explorer wired in."""
from __future__ import annotations

from pathlib import Path

import webview

from .. import APP_NAME, ffmpeg
from ..config import Settings
from ..logs import log
from ..win32 import release, single_instance
from .api import Api
from .assistant import Assistant
from .controller import Controller

MIN_SIZE = (1100, 680)
ICON = Path(__file__).resolve().parents[1] / "assets" / "open-recorder.ico"  # the window and taskbar icon


def _on_drop(ctl: Controller):
    def handler(event):
        files = (event.get("dataTransfer") or {}).get("files") or []
        paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
        if paths:
            ctl.events.emit("files-dropped", {"paths": paths, "x": event.get("clientX"), "y": event.get("clientY")})
    return handler


def _wire_drops(window, ctl: Controller) -> None:
    try:
        from webview.dom import DOMEventHandler
        window.dom.document.events.dragover += DOMEventHandler(lambda e: None, True, True)
        window.dom.document.events.drop += DOMEventHandler(_on_drop(ctl), True, True)
    except Exception as e:  # an older pywebview: drops from Explorer just don't work
        log.warning(f"EDITOR file drops are off: {e!r}")


def run_editor(config_path=None, debug: bool = False) -> int:
    if not ffmpeg.available():
        from ..recorder.app import _message
        _message("error", f"{APP_NAME} needs ffmpeg and could not find it.\n\nInstall it with:\n"
                          f"    {ffmpeg.INSTALL_HINT}\nthen open {APP_NAME} again.")
        return 1
    mutex = single_instance("OpenRecorderEditor")
    if mutex is None:
        from ..recorder.app import _message
        _message("info", f"The {APP_NAME} editor is already open.")
        return 1
    try:
        cfg = Settings.load(config_path)
        ctl = Controller(cfg, config_path)
        api = Api(ctl, Assistant(ctl))
        size = cfg.editor.get("window") or {}
        window = webview.create_window(
            APP_NAME, ctl.server.url, js_api=api, width=int(size.get("w", 1440)), height=int(size.get("h", 900)),
            min_size=MIN_SIZE, background_color="#151618", text_select=False)
        ctl.window = window
        ctl.events.attach(window)

        def remember_size():
            try:
                cfg.editor = {**cfg.editor, "window": {"w": window.width, "h": window.height}}
                cfg.save()
            except Exception:
                pass

        window.events.loaded += lambda: _wire_drops(window, ctl)
        window.events.closing += remember_size
        log.info("EDITOR open")
        webview.start(gui="edgechromium", debug=debug, private_mode=False, icon=str(ICON))
        ctl.export_cancel()
        ctl.server.stop()
        return 0
    except Exception as e:
        log.exception(f"EDITOR crashed {e!r}")
        from ..recorder.app import _message
        _message("error", f"{APP_NAME} crashed:\n{e}")
        return 1
    finally:
        release(mutex)
