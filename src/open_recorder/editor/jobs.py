"""Work that runs in the background while the user edits: thumbnail strips and posters for new
media, and transcripts, one file at a time. Each finished piece is pushed to the page."""
from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Callable

from .. import media, transcribe
from ..logs import log
from .session import Session


class Worker:
    """One thread working through a queue, so heavy ffmpeg or Whisper jobs never pile up."""

    def __init__(self, name: str):
        self.q: queue.Queue = queue.Queue()
        threading.Thread(target=self._loop, name=name, daemon=True).start()

    def put(self, fn: Callable[[], None]) -> None:
        self.q.put(fn)

    def _loop(self) -> None:
        while True:
            fn = self.q.get()
            try:
                fn()
            except Exception as e:
                log.exception(f"JOB failed: {e!r}")


class MediaJobs:
    def __init__(self, emit: Callable[[str, object], None]):
        self.emit = emit
        self.worker = Worker("media-jobs")

    def request(self, session: Session, keys: list[str] | None = None) -> None:
        keys = list(session.project.media) if keys is None else keys
        for key in keys:
            if key not in session.extra:
                session.extra[key] = {}
                self.worker.put(lambda k=key: self._make(session, k))

    def _make(self, session: Session, key: str) -> None:
        m = session.project.media.get(key)
        if m is None:
            return
        source, cache = Path(m.path), session.files.cache
        extra = session.extra.setdefault(key, {})
        if m.has_video:
            poster = media.poster(source, cache, at=min(0.5, m.duration / 2) if m.duration else 0)
            if poster:
                extra["poster"] = str(poster)
                session.server.allowed.file(poster)
            strip = media.strip(source, m.duration, cache, aspect=m.aspect)
            if strip:
                extra["strip"] = strip
        self.emit("media-extra", {"folder": str(session.folder), "key": key})

    def waveform(self, session: Session, key: str) -> dict | None:
        m = session.project.media.get(key)
        return media.peaks(Path(m.path), session.files.cache) if m and m.has_audio else None


class Transcripts:
    """The transcription queue. Status per media key: queued, working (with progress), done,
    failed (with a message), or None when nothing was asked."""

    def __init__(self, emit: Callable[[str, object], None], engine: Callable[[], transcribe.Transcriber | None]):
        self.emit = emit
        self.engine = engine
        self.worker = Worker("transcripts")
        self.status: dict[tuple[str, str], dict] = {}

    def status_for(self, session: Session, key: str) -> dict | None:
        found = self.status.get((str(session.folder), key))
        if found:
            return found
        m = session.project.media.get(key)
        if m and transcribe.load(session.files.transcripts, Path(m.path)):
            return {"state": "done"}
        return None

    def load(self, session: Session, key: str) -> dict | None:
        m = session.project.media.get(key)
        return transcribe.load(session.files.transcripts, Path(m.path)) if m else None

    def enqueue(self, session: Session, keys: list[str]) -> None:
        for key in keys:
            current = self.status_for(session, key) or {}
            if current.get("state") in ("queued", "working", "done"):
                continue
            self._set(session, key, {"state": "queued", "progress": 0})
            self.worker.put(lambda k=key: self._run(session, k))

    def _set(self, session: Session, key: str, status: dict) -> None:
        self.status[(str(session.folder), key)] = status
        self.emit("transcript", {"folder": str(session.folder), "key": key, **status})

    def _run(self, session: Session, key: str) -> None:
        m = session.project.media.get(key)
        engine = self.engine()
        if m is None or engine is None:
            self.status.pop((str(session.folder), key), None)
            return
        ok, why = engine.ready()
        if not ok:
            return self._set(session, key, {"state": "failed", "message": why})
        last = {"p": -1.0}

        def progress(fraction: float, message: str) -> None:
            if fraction >= 0 and fraction - last["p"] >= 0.02:
                last["p"] = fraction
                self._set(session, key, {"state": "working", "progress": round(fraction, 3), "message": message})
        try:
            data = engine.transcribe(Path(m.path), m.duration, progress)
        except transcribe.TranscribeError as e:
            return self._set(session, key, {"state": "failed", "message": str(e)})
        except Exception as e:
            log.exception(f"TRANSCRIBE {key} crashed: {e!r}")
            return self._set(session, key, {"state": "failed", "message": str(e)})
        transcribe.save(session.files.transcripts, Path(m.path), data)
        self._set(session, key, {"state": "done", "words": len(data.get("words", []))})
