"""The editor's brain behind the page: the root folder and its projects, the open project, the
recorder, background jobs and export. The page reaches it through api.py."""
from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

from .. import __version__, media, transcribe
from ..config import DATA_DIR, DEFAULT_OUTPUT, Settings
from ..core import Project
from ..export import ExportJob
from ..logs import log
from ..project import Library, safe_name
from .events import Events
from .jobs import MediaJobs, Transcripts
from .recorder_link import RecorderLink
from .server import Server
from .session import Session, voice_keys

POSTERS = DATA_DIR / "posters"
RECENT_KEEP = 30


class Controller:
    def __init__(self, cfg: Settings, config_path: str | None = None):
        self.cfg = cfg
        self.server = Server()
        self.server.start()
        self.events = Events()
        self.window = None
        self.session: Session | None = None
        self.media_jobs = MediaJobs(self.events.emit)
        self.transcripts = Transcripts(self.events.emit, lambda: transcribe.from_settings(self.cfg))
        self.recorder = RecorderLink(self._on_recorder, config_path)
        self.export_job: ExportJob | None = None

    # ---------- the root folder and its projects ----------
    @property
    def root(self) -> Path | None:
        return Path(self.cfg.output_dir) if self.cfg.output_dir else None

    def boot(self) -> dict:
        return {"version": __version__, "root": str(self.root or ""), "default_root": str(DEFAULT_OUTPUT),
                "needs_root": self.root is None, "projects": self.projects() if self.root else [],
                "open": self.state() if self.session else None, "recording": self.recorder.running}

    def set_root(self, folder: str) -> dict:
        path = Path(folder)
        path.mkdir(parents=True, exist_ok=True)
        self.cfg.output_dir = str(path)
        self.cfg.save()
        log.info(f"EDITOR root folder {path}")
        return self.boot()

    def projects(self) -> list[dict]:
        if not self.root:
            return []
        self.root.mkdir(parents=True, exist_ok=True)
        POSTERS.mkdir(parents=True, exist_ok=True)
        self.server.allowed.folder(POSTERS)
        listed = Library(self.root).projects(extra=list(self.cfg.recent))
        missing = []
        for p in listed:
            source = Path(p.pop("poster_source")) if p.get("poster_source") else None
            cached = media.cache.cache_path(POSTERS, source, "poster320", "jpg") if source else None
            p["poster"] = self.server.media_url(cached) if cached and cached.exists() else ""
            if source and not p["poster"]:
                missing.append((p["path"], source))
        if missing:
            threading.Thread(target=self._make_posters, args=(missing,), daemon=True).start()
        return listed

    def _make_posters(self, items) -> None:
        for path, source in items:
            poster = media.poster(source, POSTERS)
            if poster:
                self.events.emit("project-poster", {"path": path, "poster": self.server.media_url(poster)})

    def _remember(self, folder: Path) -> None:
        recent = dict(self.cfg.recent)
        recent[str(folder)] = time.time()
        self.cfg.recent = dict(sorted(recent.items(), key=lambda kv: -kv[1])[:RECENT_KEEP])
        self.cfg.save()

    # ---------- the open project ----------
    def open(self, folder: str) -> dict:
        session = Session(Path(folder), self.server)
        session.transcript_status = lambda key: self.transcripts.status_for(session, key)
        self.session = session
        self._remember(session.folder)
        self.media_jobs.request(session)
        self.auto_transcribe()
        log.info(f"EDITOR opened {session.folder}")
        return self.state()

    def create(self, name: str, aspect: str = "16:9") -> dict:
        if not self.root:
            raise ValueError("Choose a root folder first")
        return self.open(str(Library(self.root).create(name, aspect)))

    def open_quick(self) -> dict:
        return self.open(str(Library(self.root).quick()))

    def close(self) -> dict:
        self.session = None
        return self.boot()

    def _let_go(self, folder: Path) -> None:
        """Close the project if it is the open one, so nothing holds its files."""
        if self.session and Path(self.session.folder).resolve() == folder:
            self.session = None

    def rename_project(self, path: str, name: str) -> list[dict]:
        folder = Path(path).resolve()
        self._let_go(folder)
        target = Library(self.root).rename(folder, name)
        self.cfg.recent = {(str(target) if Path(k).resolve() == folder else k): v for k, v in self.cfg.recent.items()}
        self.cfg.save()
        log.info(f"EDITOR renamed {folder} to {target.name}")
        return self.projects()

    def delete_project(self, path: str) -> list[dict]:
        folder = Path(path).resolve()
        self._let_go(folder)
        Library(self.root).delete(folder)
        self.cfg.recent = {k: v for k, v in self.cfg.recent.items() if Path(k).resolve() != folder}
        self.cfg.save()
        log.info(f"EDITOR sent {folder} to the Recycle Bin")
        return self.projects()

    def state(self) -> dict | None:
        return self.session.state() if self.session else None

    def need(self) -> Session:
        if self.session is None:
            raise ValueError("No project is open")
        return self.session

    def apply(self, ops: list[dict], label: str) -> dict:
        s = self.need()
        notes = s.apply(ops, label or "Edit")
        if any(o.get("op") in ("add_recording", "add_clip") for o in ops):
            self.auto_transcribe()
        return {"notes": notes, "state": s.state()}

    def undo(self) -> dict:
        s = self.need()
        return {"label": s.undo(), "state": s.state()}

    def redo(self) -> dict:
        s = self.need()
        return {"label": s.redo(), "state": s.state()}

    def add_paths(self, paths: list[str]) -> dict:
        s = self.need()
        keys = s.add_paths(paths)
        self.media_jobs.request(s, keys)
        return {"keys": keys, "state": s.state()}

    def rescan(self) -> dict:
        s = self.need()
        new = s.rescan()
        self.media_jobs.request(s, new)
        return {"new": new, "state": s.state()}

    def auto_transcribe(self) -> None:
        """Transcribe the voices on the timeline when an engine is set up and ready."""
        s = self.session
        engine = transcribe.from_settings(self.cfg)
        if s is None or engine is None or not engine.ready()[0]:
            return
        used = {c.media for _, c in s.project.clips()}
        self.transcripts.enqueue(s, [k for k in voice_keys(s.project) if k in used])

    def delete_media(self, keys: list[str]) -> dict:
        s = self.need()
        result = s.delete_media(keys)
        return {**result, "state": s.state()}

    def waveform(self, key: str) -> dict | None:
        return self.media_jobs.waveform(self.need(), key)

    # ---------- recording ----------
    def record(self) -> dict:
        folder = self.session.folder if self.session else self.root
        if folder is None:
            raise ValueError("Choose a root folder first")
        if not self.recorder.start(folder):
            return {"started": False, "message": "The recorder is already open"}
        if self.window:
            self.window.minimize()
        return {"started": True, "folder": str(folder)}

    def _on_recorder(self, event: dict) -> None:
        kind = event.get("event")
        log.info(f"RECORDER event {kind}")
        if kind == "recording" and self.window:
            self.window.minimize()
        elif kind == "saved":
            self._take_saved(event)
        elif kind == "busy":
            self.events.emit("recorder", {"state": "busy"})
        elif kind in ("closed", "exited"):
            self.events.emit("recorder", {"state": "closed"})
            if self.window:
                self.window.restore()

    def _take_saved(self, event: dict) -> None:
        s = self.session
        folder = Path(event.get("folder") or "")
        same = s is not None and folder.resolve() == s.folder
        payload = {"id": event.get("id"), "seconds": event.get("seconds"), "problems": event.get("problems", 0),
                   "folder": str(folder), "in_project": same}
        if same:
            new = s.rescan()
            self.media_jobs.request(s, new)
            added = False
            if self.cfg.editor.get("auto_add", True) and any(s.project.media[k].recording == event.get("id") for k in new):
                try:
                    s.apply([{"op": "add_recording", "recording": event["id"]}], "Add take")
                    added = True
                except ValueError as e:
                    log.warning(f"could not add the take: {e}")
            self.auto_transcribe()
            payload.update(added=added, state=s.state())
        self.events.emit("take", payload)
        if self.window:
            self.window.restore()

    # ---------- export ----------
    def export_start(self, name: str, quality: str) -> dict:
        s = self.need()
        if self.export_job and self.export_job.proc and self.export_job.proc.poll() is None:
            raise ValueError("An export is already running")
        exports = s.files.exports
        base = safe_name(name or s.project.name)
        out, n = exports / f"{base}.mp4", 2
        while out.exists():
            out, n = exports / f"{base} ({n}).mp4", n + 1
        last = {"f": -1.0}

        def progress(f: float) -> None:
            if f - last["f"] >= 0.01 or f >= 1:
                last["f"] = f
                self.events.emit("export-progress", {"fraction": round(f, 3)})

        def done(ok: bool, message: str) -> None:
            self.events.emit("export-done", {"ok": ok, "message": message, "path": str(out) if ok else ""})

        self.export_job = ExportJob(snapshot(s), out, s.files.cache, encoder=self.cfg.encoder,
                                    quality=quality, on_progress=progress, on_done=done)
        self.export_job.start()
        self.cfg.editor = {**self.cfg.editor, "export_quality": quality}
        self.cfg.save()
        return {"path": str(out)}

    def export_cancel(self) -> None:
        if self.export_job:
            self.export_job.cancel()

    # ---------- the desktop ----------
    @staticmethod
    def reveal(path: str) -> None:
        p = Path(path)
        if p.is_file():
            subprocess.Popen(["explorer", "/select,", str(p)])
        elif p.exists():
            os.startfile(p)

    @staticmethod
    def open_path(path: str) -> None:
        if Path(path).exists():
            os.startfile(path)


def snapshot(s: Session) -> Project:
    """Export works on a copy, so editing during an export changes nothing in the file."""
    with s.lock:
        return Project.from_dict(s.project.to_dict())
