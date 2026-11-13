"""`open-recorder --check`: everything the recorder needs, one line each. OK is fine, MISS stops it
from working and says what to install, NOTE is worth knowing."""
from __future__ import annotations

import platform
import sys

from . import APP_NAME, __version__, ffmpeg
from .config import LOG_DIR, Settings
from .recorder.screens import Screens
from .win32 import windows_build


def _row(state: str, what: str, detail: str = "") -> None:
    print(f"{state:<4}  {what}{':  ' + detail if detail else ''}")


def run_checks(config_path=None) -> int:
    print(f"{APP_NAME} {__version__}\n")
    missing = 0

    def need(ok: bool, what: str, detail: str = "", fix: str = ""):
        nonlocal missing
        missing += 0 if ok else 1
        _row("OK" if ok else "MISS", what, detail if ok else (fix or detail))

    build = windows_build()
    need(build >= 19041, "Windows 10 2004 or newer", f"build {build}", f"build {build}: update Windows")
    need(sys.version_info >= (3, 10), "Python 3.10 or newer", platform.python_version())
    found = ffmpeg.available()
    need(found, "ffmpeg + ffprobe", ffmpeg.FFMPEG, f"not found, install with: {ffmpeg.INSTALL_HINT}")
    if not found:
        print(f"\n{missing} thing(s) missing.")
        return 1
    print(f"      version {ffmpeg.version()}")
    need(ffmpeg.has_filter("ddagrab"), "fast screen capture (ddagrab)", "available",
         "this ffmpeg has no ddagrab, install a recent build with: " + ffmpeg.INSTALL_HINT)

    cfg = Settings.load(config_path)
    enc = ffmpeg.pick_encoder(cfg.encoder)
    _row("OK", "video encoder", enc + ("  (CPU: fine, but a GPU encoder keeps the PC cooler)" if enc == "libx264" else ""))

    cams, mics = ffmpeg.list_devices()
    _row("OK" if cams else "NOTE", "cameras", ", ".join(cams) or "none found (screen-only recording still works)")
    _row("OK" if mics else "NOTE", "microphones", ", ".join(mics) or "none found (no voice will be recorded)")

    screens = Screens()
    screens.refresh()
    screens.probe()
    for m in screens.monitors:
        hit = screens.grab.get(m["key"])
        _row("OK" if hit else "NOTE", f"screen {m['label']}",
             "fast capture (ddagrab, ~30 fps)" if hit else "slower capture (gdigrab, ~18 fps)")

    print()
    _row("", "settings", str(cfg.path))
    _row("", "log", str(LOG_DIR / "recorder.log"))
    _row("", "recordings", cfg.output_dir or "asked the first time it opens")
    print(f"\n{'Everything is ready.' if not missing else f'{missing} thing(s) missing.'}")
    return 1 if missing else 0
