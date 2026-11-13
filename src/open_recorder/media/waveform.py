"""Waveform peaks for the timeline: the loudest sample in every 1/50 s, from 0 to 1."""
from __future__ import annotations

import json
import subprocess
from array import array
from pathlib import Path

from .. import ffmpeg
from .cache import cache_path

PEAKS_PER_SECOND = 50
RATE = 8000


def peaks(source: Path, cache_dir: Path) -> dict | None:
    out = cache_path(cache_dir, source, "wave", "json")
    if out.exists():
        try:
            return json.loads(out.read_text(encoding="utf-8"))
        except ValueError:
            pass
    proc = subprocess.run([ffmpeg.FFMPEG, "-v", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", str(RATE),
                           "-f", "s16le", "-"], capture_output=True, creationflags=ffmpeg.NO_WINDOW)
    if proc.returncode != 0 or not proc.stdout:
        return None
    samples = array("h")
    samples.frombytes(proc.stdout[: len(proc.stdout) // 2 * 2])
    step = RATE // PEAKS_PER_SECOND
    values = []
    for i in range(0, len(samples), step):
        chunk = samples[i:i + step]
        values.append(round(max(abs(min(chunk)), abs(max(chunk))) / 32768, 3) if chunk else 0.0)
    data = {"per_second": PEAKS_PER_SECOND, "peaks": values}
    out.write_text(json.dumps(data), encoding="utf-8")
    return data
