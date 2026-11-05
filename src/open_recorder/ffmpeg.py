"""Everything about the ffmpeg install: where it is, what it can do, and which video encoder this
PC can use. The recording itself is in capture.py and recording.py."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from .logs import log

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
INSTALL_HINT = "winget install Gyan.FFmpeg"


def _find_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def _find_ffprobe(ffmpeg: str | None) -> str | None:
    if ffmpeg:
        beside = Path(ffmpeg).with_name("ffprobe.exe")
        if beside.exists():
            return str(beside)
    return shutil.which("ffprobe")


FFMPEG = _find_ffmpeg() or "ffmpeg"
FFPROBE = _find_ffprobe(_find_ffmpeg()) or "ffprobe"


def available() -> bool:
    return _find_ffmpeg() is not None and _find_ffprobe(_find_ffmpeg()) is not None


def run(cmd, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW, **kw)


def version() -> str | None:
    try:
        r = run([FFMPEG, "-hide_banner", "-version"], text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.match(r"ffmpeg version (\S+)", r.stdout)
    return m.group(1) if m else None


def has_filter(name: str) -> bool:
    try:
        r = run([FFMPEG, "-hide_banner", "-filters"], text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return re.search(rf"^\s*\S+\s+{re.escape(name)}\s", r.stdout, re.M) is not None


def duration_of(path) -> float | None:
    r = run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def format_tags(path) -> dict:
    r = run([FFPROBE, "-v", "error", "-show_entries", "format_tags", "-of", "json", str(path)], text=True)
    try:
        return json.loads(r.stdout).get("format", {}).get("tags", {}) or {}
    except ValueError:
        return {}


def list_devices() -> tuple[list[str], list[str]]:
    """(cameras, microphones) as DirectShow names, the way ffmpeg needs them."""
    try:
        r = run([FFMPEG, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"], timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return [], []
    cams, mics = [], []
    for m in re.finditer(r'"([^"]+)" \((video|audio)\)', r.stderr.decode("utf-8", "replace")):
        (cams if m.group(2) == "video" else mics).append(m.group(1))
    return cams, mics


# ---------- video encoders ----------
# The GPU encoders keep the CPU free for the capture itself. Tried in this order; libx264 (CPU)
# works everywhere. Each entry: extra arguments for a quality value, and the pixel format it takes.
ENCODERS = {
    "h264_nvenc": (lambda q: ["-preset", "p5", "-cq", str(q)], "yuv420p"),
    "h264_qsv": (lambda q: ["-preset", "faster", "-global_quality", str(q)], "nv12"),
    "h264_amf": (lambda q: ["-quality", "balanced", "-rc", "cqp", "-qp_i", str(q), "-qp_p", str(q)], "nv12"),
    "libx264": (lambda q: ["-preset", "veryfast", "-crf", str(q)], "yuv420p"),
}
_working: dict[str, bool] = {}


def encoder_works(name: str) -> bool:
    """A real 3-frame test encode: being listed by ffmpeg doesn't mean the GPU or driver is there."""
    if name not in _working:
        extra, pix = ENCODERS[name]
        try:
            r = run([FFMPEG, "-hide_banner", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=1280x720:r=30",
                     "-frames:v", "3", "-c:v", name, *extra(23), "-pix_fmt", pix, "-f", "null", "-"], timeout=30)
            _working[name] = r.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _working[name] = False
        log.info(f"encoder {name}: {'works' if _working[name] else 'not available'}")
    return _working[name]


def pick_encoder(preferred: str = "auto") -> str:
    if preferred in ENCODERS and encoder_works(preferred):
        return preferred
    if preferred not in ("auto", "", None):
        log.warning(f"encoder {preferred!r} is not available here, picking one automatically")
    for name in ENCODERS:
        if encoder_works(name):
            return name
    return "libx264"


def video_args(encoder: str, quality: int, fps: int) -> list[str]:
    extra, pix = ENCODERS[encoder]
    return ["-c:v", encoder, *extra(quality), "-pix_fmt", pix, "-fps_mode", "cfr", "-r", str(fps)]
