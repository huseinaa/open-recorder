"""Thumbnail strips for the timeline: one small frame every few seconds, tiled side by side in
one JPEG. The timeline draws the frame nearest to each spot of a clip."""
from __future__ import annotations

import math
from pathlib import Path

from .. import ffmpeg
from ..logs import log
from .cache import cache_path

TILE_H = 54          # px, the strip's height
MAX_TILES = 240


def strip(source: Path, duration: float, cache_dir: Path, aspect: float = 16 / 9) -> dict | None:
    """{path, every, tiles, tile_w, tile_h} or None when the file has no picture."""
    tiles = max(1, min(MAX_TILES, math.ceil(duration / 2.0))) if duration > 0 else 1
    every = duration / tiles if duration > 0 else 1.0
    tile_w = max(16, round(TILE_H * aspect / 2) * 2)
    out = cache_path(cache_dir, source, f"strip{tiles}", "jpg")
    info = {"path": str(out), "every": every, "tiles": tiles, "tile_w": tile_w, "tile_h": TILE_H}
    if out.exists():
        return info
    if duration > 0:
        vf = f"fps={tiles / duration:.6f},scale={tile_w}:{TILE_H},tile={tiles}x1"
        cmd = [ffmpeg.FFMPEG, "-v", "error", "-y", "-i", str(source), "-vf", vf, "-frames:v", "1", "-q:v", "5", str(out)]
    else:  # an image
        cmd = [ffmpeg.FFMPEG, "-v", "error", "-y", "-i", str(source), "-vf", f"scale={tile_w}:{TILE_H}",
               "-frames:v", "1", str(out)]
    r = ffmpeg.run(cmd, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not out.exists():
        log.warning(f"THUMBS failed for {source.name}: {(r.stderr or '').strip()[-200:]}")
        return None
    return info


def poster(source: Path, cache_dir: Path, at: float = 0.5, width: int = 320) -> Path | None:
    """One frame, for the media bin and the recent projects grid."""
    out = cache_path(cache_dir, source, f"poster{width}", "jpg")
    if out.exists():
        return out
    r = ffmpeg.run([ffmpeg.FFMPEG, "-v", "error", "-y", "-ss", f"{at:.2f}", "-i", str(source),
                    "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", str(out)], encoding="utf-8", errors="replace")
    return out if r.returncode == 0 and out.exists() else None
