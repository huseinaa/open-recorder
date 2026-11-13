"""What a file is: video, image or sound, its size, frame rate, length, and whether it has sound."""
from __future__ import annotations

import json
from pathlib import Path

from .. import ffmpeg
from ..logs import log

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus"}
MEDIA_EXT = VIDEO_EXT | IMAGE_EXT | AUDIO_EXT


def kind_of(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in IMAGE_EXT:
        return "image"
    if ext in AUDIO_EXT:
        return "audio"
    return None


def _rate(text: str) -> float:
    try:
        num, _, den = (text or "0/1").partition("/")
        return round(float(num) / float(den or 1), 3) if float(den or 1) else 0.0
    except ValueError:
        return 0.0


def probe(path: Path) -> dict:
    """{kind, duration, width, height, fps, has_video, has_audio, tags}. Empty when unreadable."""
    kind = kind_of(path)
    if kind is None:
        return {}
    r = ffmpeg.run([ffmpeg.FFPROBE, "-v", "error", "-show_entries",
                    "format=duration:format_tags:stream=codec_type,width,height,avg_frame_rate,duration",
                    "-of", "json", str(path)], encoding="utf-8", errors="replace")
    try:
        data = json.loads(r.stdout or "{}")
    except ValueError:
        data = {}
    streams = data.get("streams") or []
    if r.returncode != 0 or not streams:
        log.warning(f"PROBE could not read {path.name}: {(r.stderr or '').strip()[-200:]}")
        return {}
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    try:
        duration = float((data.get("format") or {}).get("duration") or (video or audio or {}).get("duration") or 0)
    except ValueError:
        duration = 0.0
    return {
        "kind": kind,
        "duration": 0.0 if kind == "image" else round(duration, 3),
        "width": int(video.get("width") or 0) if video else 0,
        "height": int(video.get("height") or 0) if video else 0,
        "fps": _rate(video.get("avg_frame_rate")) if video and kind == "video" else 0.0,
        "has_video": video is not None and kind != "audio",
        "has_audio": audio is not None,
        "tags": (data.get("format") or {}).get("tags") or {},
    }
