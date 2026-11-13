"""Find the media in a project folder: recordings (a screen_<id>.mp4 + camera_<id>.mp4 pair,
lined up by the screen file's screen_offset tag) and any other video, image or sound file."""
from __future__ import annotations

import re
from pathlib import Path

from ..core import Media, Project
from ..media import MEDIA_EXT, probe

PAIR = re.compile(r"^(screen|camera)_(\d{8}_\d{6})\.mp4$", re.IGNORECASE)
SKIP_DIRS = {".openrecorder", ".recording", "Exports"}


def media_key(folder: Path, path: Path) -> str:
    """Relative to the project folder when inside it, so a moved project still opens."""
    try:
        return path.resolve().relative_to(folder.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def to_media(folder: Path, path: Path) -> Media | None:
    info = probe(path)
    if not info:
        return None
    m = Media(key=media_key(folder, path), path=str(path.resolve()), kind=info["kind"], duration=info["duration"],
              width=info["width"], height=info["height"], fps=info["fps"], has_video=info["has_video"],
              has_audio=info["has_audio"])
    pair = PAIR.match(path.name)
    if pair:
        m.role, m.recording = pair.group(1).lower(), pair.group(2)
        try:
            m.offset = float(info["tags"].get("screen_offset", 0) or 0)
        except ValueError:
            m.offset = 0.0
    return m


def media_files(folder: Path) -> list[Path]:
    return sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in MEDIA_EXT
                   and not p.name.endswith(".part.mp4")), key=lambda p: p.name.lower())


def scan(folder: Path, project: Project) -> list[str]:
    """Bring project.media in line with the folder. Returns the keys that are new. Files that are
    gone are dropped unless a clip still uses them; files linked from outside the folder stay."""
    folder = Path(folder)
    found: dict[str, Path] = {media_key(folder, p): p for p in media_files(folder)}
    used = {c.media for _, c in project.clips()}
    new = []
    for key, path in found.items():
        if key not in project.media:
            m = to_media(folder, path)
            if m:
                project.media[key] = m
                new.append(key)
    for key in list(project.media):
        inside = not Path(key).is_absolute()
        gone = (inside and key not in found) or (not inside and not Path(key).exists())
        if gone and key not in used:
            del project.media[key]
    _pair_offsets(project)
    return new


def add_file(folder: Path, project: Project, path: Path) -> str | None:
    """Link a file from anywhere (dragged in from Explorer). It is not copied."""
    m = to_media(Path(folder), Path(path))
    if m is None:
        return None
    project.media[m.key] = m
    return m.key


def recordings(project: Project) -> dict[str, dict[str, Media]]:
    """recording id → {"screen": Media, "camera": Media} (either may be missing)."""
    out: dict[str, dict[str, Media]] = {}
    for m in project.media.values():
        if m.recording:
            out.setdefault(m.recording, {})[m.role] = m
    return out


def _pair_offsets(project: Project) -> None:
    """A camera file has no tag of its own: give it its screen's offset so either half knows it."""
    for parts in recordings(project).values():
        if "screen" in parts and "camera" in parts:
            parts["camera"].offset = parts["screen"].offset
