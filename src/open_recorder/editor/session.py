"""The open project: its folder, the timeline, undo, and the media the page may play.
Every change goes through apply(), which saves at once."""
from __future__ import annotations

import threading
from dataclasses import asdict
from pathlib import Path

from .. import project as files
from ..core import History, Project, apply
from ..logs import log
from ..project import ProjectFiles
from .server import Server


def voice_keys(p: Project) -> list[str]:
    """The files whose sound is speech worth transcribing: the camera half of a take (or the
    screen half when the camera was off), and other files with sound."""
    pairs = {m.recording for m in p.media.values() if m.role == "camera"}
    out = []
    for m in p.media.values():
        if not m.has_audio:
            continue
        if m.role == "camera" or (m.role == "screen" and m.recording not in pairs) or not m.recording:
            out.append(m.key)
    return out


def _drop_media(snapshot: dict, keys: set[str]) -> None:
    """Take clips of deleted files out of one saved project (a dict from Project.to_dict)."""
    for lane in snapshot.get("lanes", []):
        lane["clips"] = [c for c in lane.get("clips", []) if c.get("media") not in keys]
    for key in keys:
        snapshot.get("media", {}).pop(key, None)


class Session:
    def __init__(self, folder: Path, server: Server):
        self.folder = Path(folder).resolve()
        self.files = ProjectFiles(self.folder)
        self.server = server
        self.lock = threading.RLock()
        self.history = History()
        self.extra: dict[str, dict] = {}       # media key -> strip / poster, filled in by the jobs
        self.transcript_status = None           # set by the editor: key -> {"state", "progress"}
        self.project = files.load(self.folder)
        self.rescan()

    # ---------- files ----------
    def allow(self) -> None:
        allowed = self.server.allowed
        allowed.reset()
        allowed.folder(self.files.cache)
        allowed.folder(self.files.exports)
        for m in self.project.media.values():
            allowed.file(m.path)

    def rescan(self) -> list[str]:
        with self.lock:
            new = files.scan(self.folder, self.project)
            files.save(self.folder, self.project)
            self.allow()
            if new:
                log.info(f"PROJECT {self.folder.name}: new media {new}")
            return new

    def add_paths(self, paths: list[str]) -> list[str]:
        with self.lock:
            keys = [k for k in (files.add_file(self.folder, self.project, Path(p)) for p in paths) if k]
            files.save(self.folder, self.project)
            self.allow()
            return keys

    def delete_media(self, keys: list[str]) -> dict:
        """Files in the project folder go to the Recycle Bin; files linked from elsewhere are only
        taken out of the project. Their clips leave the timeline and every undo step with them."""
        from ..win32 import recycle
        with self.lock:
            keys = [k for k in dict.fromkeys(keys) if k in self.project.media]
            if not keys:
                raise ValueError("That file is no longer in the project")
            gone, failed = set(), []
            for key in keys:
                path = Path(self.project.media[key].path)
                if not Path(key).is_absolute() and path.exists():  # inside the project folder
                    try:
                        recycle(path)
                    except OSError:
                        failed.append(path.name)
                        continue
                gone.add(key)
            clips = sum(1 for _, c in self.project.clips() if c.media in gone)
            for lane in self.project.lanes:
                lane.clips = [c for c in lane.clips if c.media not in gone]
            for key in gone:
                del self.project.media[key]
                self.extra.pop(key, None)
            self.history.scrub(lambda snap: _drop_media(snap, gone))
            files.save(self.folder, self.project)
            self.allow()
            if gone:
                log.info(f"PROJECT {self.folder.name}: deleted {sorted(gone)}, {clips} clip(s) with them")
            if failed and not gone:
                raise ValueError(f"Windows could not delete {', '.join(failed)}. It may be open somewhere, close it and try again")
            return {"deleted": sorted(gone), "clips": clips, "failed": failed}

    # ---------- edits ----------
    def apply(self, ops: list[dict], label: str) -> list[str]:
        with self.lock:
            edited, notes = apply(self.project, ops)
            self.commit(edited, label)
            return notes

    def commit(self, edited: Project, label: str) -> None:
        with self.lock:
            self.history.push(self.project.to_dict(), label)
            self.project = edited
            files.save(self.folder, self.project)

    def undo(self) -> str | None:
        return self._step(self.history.undo)

    def redo(self) -> str | None:
        return self._step(self.history.redo)

    def _step(self, fn) -> str | None:
        with self.lock:
            result = fn(self.project.to_dict())
            if result is None:
                return None
            label, data = result
            media = self.project.media  # the media list follows the folder, not the undo history
            self.project = Project.from_dict(data)
            self.project.media = {**self.project.media, **media}
            files.save(self.folder, self.project)
            return label

    # ---------- what the page gets ----------
    def media_payload(self) -> dict:
        status = self.transcript_status or (lambda key: None)
        voices = set(voice_keys(self.project))
        out = {}
        for key, m in self.project.media.items():
            item = asdict(m)
            item["url"] = self.server.media_url(m.path)
            item["name"] = Path(m.path).name
            item["voice"] = key in voices
            item["transcript"] = status(key)
            extra = self.extra.get(key) or {}
            if extra.get("poster"):
                item["poster"] = self.server.media_url(extra["poster"])
            if extra.get("strip"):
                strip = dict(extra["strip"])
                strip["url"] = self.server.media_url(strip.pop("path"))
                item["strip"] = strip
            out[key] = item
        return out

    def state(self) -> dict:
        with self.lock:
            undo, redo = self.history.labels()
            return {"folder": str(self.folder), "name": self.project.name, "project": self.project.to_dict(),
                    "media": self.media_payload(), "undo": undo, "redo": redo,
                    "exports": str(self.files.exports)}
