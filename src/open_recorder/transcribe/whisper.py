"""Whisper on this PC (faster-whisper): free and offline. Needs the add-on package and a one-time
model download; both can be done from the app."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import threading
import time
from pathlib import Path

from ..config import DATA_DIR
from ..logs import log
from .base import Progress, TranscribeError, Transcriber

SIZES_MB = {"tiny": 75, "base": 145, "small": 484, "medium": 1530}
PACKAGE = "faster-whisper>=1.0"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_models: dict[tuple[str, str], object] = {}  # loaded once per size and device


def python_exe() -> str:
    """python.exe next to pythonw.exe, so pip's output can be read."""
    exe = Path(sys.executable)
    console = exe.with_name("python.exe")
    return str(console if exe.name.lower() == "pythonw.exe" and console.exists() else exe)


def _folder_mb(path: Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1e6 if path.exists() else 0.0


class Whisper(Transcriber):
    name = "whisper"
    label = "Whisper"

    def __init__(self, size: str = "small", device: str = "cpu", models_dir: Path | None = None):
        self.size = size if size in SIZES_MB else "small"
        self.device = device or "cpu"
        self.models_dir = Path(models_dir) if models_dir else DATA_DIR / "models"

    # ---------- what is there ----------
    @staticmethod
    def installed() -> bool:
        return importlib.util.find_spec("faster_whisper") is not None

    def target(self) -> Path:
        return self.models_dir / f"faster-whisper-{self.size}"

    def model_dir(self) -> Path | None:
        for folder in (self.target(), Path.home() / ".cache" / f"faster-whisper-{self.size}"):
            if (folder / "model.bin").exists():
                return folder
        return None

    def ready(self) -> tuple[bool, str]:
        if not self.installed():
            return False, "The Whisper add-on is not installed yet."
        if not self.model_dir():
            return False, f"The Whisper {self.size} model is not downloaded yet (about {SIZES_MB[self.size]} MB)."
        return True, ""

    # ---------- getting it ----------
    def install(self, progress: Progress) -> None:
        progress(0.0, "Installing the Whisper add-on…")
        proc = subprocess.Popen([python_exe(), "-m", "pip", "install", "--disable-pip-version-check", PACKAGE],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                errors="replace", creationflags=NO_WINDOW)
        tail = []
        for line in proc.stdout:
            line = line.strip()
            if line:
                tail = (tail + [line])[-5:]
                progress(-1, line[:120])
        if proc.wait() != 0:
            raise TranscribeError("Installing Whisper failed: " + " ".join(tail)[-300:])
        importlib.invalidate_caches()
        progress(1.0, "Whisper add-on installed")

    def download(self, progress: Progress) -> Path:
        if self.model_dir():
            return self.model_dir()
        if not self.installed():
            self.install(progress)
        from faster_whisper import download_model
        target, total = self.target(), SIZES_MB[self.size]
        target.mkdir(parents=True, exist_ok=True)
        done = threading.Event()

        def watch():
            while not done.wait(0.5):
                mb = _folder_mb(target) + _folder_mb(self.models_dir / ".cache")
                progress(min(0.99, mb / total), f"Downloading the {self.size} model… {mb:.0f} of {total} MB")
        threading.Thread(target=watch, daemon=True).start()
        try:
            download_model(self.size, output_dir=str(target))
        except Exception as e:
            raise TranscribeError(f"The Whisper model could not be downloaded: {e}") from e
        finally:
            done.set()
        progress(1.0, "Whisper is ready")
        return target

    # ---------- using it ----------
    def _model(self):
        key = (self.size, self.device)
        if key not in _models:
            from faster_whisper import WhisperModel
            folder = self.model_dir()
            if folder is None:
                raise TranscribeError("The Whisper model is not downloaded yet.")
            _models[key] = WhisperModel(str(folder), device=self.device, compute_type="int8")
        return _models[key]

    def transcribe(self, source: Path, duration: float, progress: Progress) -> dict:
        ok, why = self.ready()
        if not ok:
            raise TranscribeError(why)
        progress(0.0, "Loading Whisper…")
        started = time.time()
        segments, info = self._model().transcribe(str(source), word_timestamps=True, vad_filter=True, beam_size=5)
        words = []
        for seg in segments:
            for w in seg.words or []:
                text = w.word.strip()
                if text:
                    words.append({"w": text, "s": round(w.start, 3), "e": round(w.end, 3)})
            if duration:
                progress(min(0.99, seg.end / duration), "Transcribing…")
        log.info(f"WHISPER {source.name}: {len(words)} words in {time.time() - started:.0f}s ({info.language})")
        return {"engine": self.name, "language": info.language, "words": words}
