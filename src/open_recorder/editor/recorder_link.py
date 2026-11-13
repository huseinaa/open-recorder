"""Start the recorder bar for a folder and listen to it. The recorder runs as its own process
(tkinter there, the web window here), and tells us about each take with one JSON line."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

from ..logs import log

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def python_exe() -> str:
    """python.exe rather than pythonw.exe, so the child's stdout reaches us through the pipe."""
    exe = Path(sys.executable)
    console = exe.with_name("python.exe")
    return str(console if exe.name.lower() == "pythonw.exe" and console.exists() else exe)


class RecorderLink:
    def __init__(self, on_event: Callable[[dict], None], config_path: str | None = None):
        self.on_event = on_event
        self.config_path = config_path
        self.proc: subprocess.Popen | None = None
        self.folder: Path | None = None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, folder: Path) -> bool:
        if self.running:
            return False
        self.folder = Path(folder)
        cmd = [python_exe(), "-m", "open_recorder", "--record", "--linked", "--output", str(self.folder)]
        if self.config_path:
            cmd += ["--config", self.config_path]
        log.info(f"RECORDER start for {self.folder}")
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                     text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()
        return True

    def _read(self, proc: subprocess.Popen) -> None:
        for line in proc.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            event.setdefault("folder", str(self.folder))
            self.on_event(event)
        code = proc.wait()
        self.on_event({"event": "exited", "code": code, "folder": str(self.folder)})
