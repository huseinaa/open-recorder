"""`open-recorder --shortcut`: a Desktop shortcut that opens the recorder with no console window."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from . import APP_NAME
from .ffmpeg import NO_WINDOW


def _ps(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def create_shortcut() -> Path | None:
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    target = pythonw if pythonw.exists() else exe
    icon = Path(__file__).resolve().parent / "assets" / "icon.ico"
    script = "; ".join([
        "$desktop = [Environment]::GetFolderPath('Desktop')",
        f"$path = Join-Path $desktop {_ps(APP_NAME + '.lnk')}",
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($path)",
        f"$s.TargetPath = {_ps(target)}",
        "$s.Arguments = '-m open_recorder'",
        "$s.WorkingDirectory = $env:USERPROFILE",
        f"$s.IconLocation = {_ps(str(icon) + ',0')}",
        "$s.Description = 'Screen + webcam recorder'",
        "$s.Save()",
        "$path",
    ])
    r = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True,
                       creationflags=NO_WINDOW)
    out = r.stdout.strip()
    return Path(out) if r.returncode == 0 and out else None
