"""Silent stretches of a file, from ffmpeg's silencedetect. The AI uses them to cut dead air even
when no transcript was made."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .. import ffmpeg
from .cache import cache_path

NOISE_DB = -35
MIN_SILENCE = 0.6

_START = re.compile(r"silence_start: (-?[\d.]+)")
_END = re.compile(r"silence_end: (-?[\d.]+)")


def parse(stderr: str, duration: float | None = None) -> list[tuple[float, float]]:
    out, start = [], None
    for line in stderr.splitlines():
        if (m := _START.search(line)) is not None:
            start = max(0.0, float(m.group(1)))
        elif (m := _END.search(line)) is not None and start is not None:
            out.append((round(start, 3), round(float(m.group(1)), 3)))
            start = None
    if start is not None and duration:
        out.append((round(start, 3), round(duration, 3)))
    return out


def silences(source: Path, cache_dir: Path, duration: float | None = None,
             noise_db: float = NOISE_DB, min_len: float = MIN_SILENCE) -> list[tuple[float, float]]:
    out = cache_path(cache_dir, source, f"silence{noise_db}_{min_len}", "json")
    if out.exists():
        try:
            return [tuple(x) for x in json.loads(out.read_text(encoding="utf-8"))]
        except ValueError:
            pass
    r = ffmpeg.run([ffmpeg.FFMPEG, "-v", "info", "-nostats", "-i", str(source), "-vn",
                    "-af", f"silencedetect=noise={noise_db}dB:d={min_len}", "-f", "null", "-"], encoding="utf-8", errors="replace")
    found = parse(r.stderr or "", duration)
    out.write_text(json.dumps(found), encoding="utf-8")
    return found
