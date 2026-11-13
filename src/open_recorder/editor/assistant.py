"""The AI tab's back end: connecting Claude or Codex, choosing a transcription engine, and the chat
itself. Each chat answer lands on the timeline as one undo step."""
from __future__ import annotations

import threading
import time
from pathlib import Path

from .. import media, transcribe
from ..ai import PROVIDERS, AIError, Router, ask
from ..core import OpError, apply
from ..logs import log
from ..project import load_chat, save_chat
from .session import voice_keys

CHECK_OPTIONS = {"claude": {"model": "haiku", "effort": "low"}, "codex": {"effort": "low"}}


class Assistant:
    def __init__(self, ctl):
        self.ctl = ctl
        self.router = Router(PROVIDERS)
        self.download_running = False

    @property
    def cfg(self):
        return self.ctl.cfg

    # ---------- providers ----------
    def providers(self) -> dict:
        out = {}
        for name, p in PROVIDERS.items():
            out[name] = {"name": name, "label": p.label, "installed": p.binary() is not None,
                         "connected": bool(self.cfg.ai_connected.get(name)), "install_hint": p.install_hint,
                         "install_url": p.install_url, "login_hint": p.login_hint}
        return out

    def summary(self) -> dict:
        providers = self.providers()
        return {"providers": providers, "primary": self.cfg.ai_primary,
                "ready": any(p["connected"] for p in providers.values()),
                "options": {"claude_model": self.cfg.claude_model, "claude_effort": self.cfg.claude_effort,
                            "codex_model": self.cfg.codex_model, "codex_effort": self.cfg.codex_effort},
                "transcriber": self.transcriber()}

    def check(self, name: str) -> dict:
        provider = PROVIDERS[name]
        status = provider.check(**CHECK_OPTIONS.get(name, {}))
        self.cfg.ai_connected = {**self.cfg.ai_connected, name: status.state == "connected"}
        if status.state == "connected" and not any(v for k, v in self.cfg.ai_connected.items() if k != name):
            self.cfg.ai_primary = name
        self.cfg.save()
        log.info(f"AI check {name}: {status.state}")
        return {"status": status.to_dict(), "summary": self.summary()}

    def disconnect(self, name: str) -> dict:
        self.cfg.ai_connected = {**self.cfg.ai_connected, name: False}
        self.cfg.save()
        return self.summary()

    def set_options(self, patch: dict) -> dict:
        allowed = {"ai_primary", "claude_model", "claude_effort", "codex_model", "codex_effort"}
        for key, value in (patch or {}).items():
            if key in allowed and isinstance(value, str):
                setattr(self.cfg, key, value.strip())
        self.cfg.save()
        return self.summary()

    # ---------- transcription engine ----------
    def transcriber(self) -> dict:
        w = transcribe.Whisper(self.cfg.whisper_model, self.cfg.whisper_device)
        engine = transcribe.from_settings(self.cfg)
        ready, message = engine.ready() if engine else (False, "")
        return {"engine": self.cfg.transcriber, "ready": ready, "message": message,
                "downloading": self.download_running,
                "whisper": {"installed": w.installed(), "downloaded": w.model_dir() is not None,
                            "size": w.size, "sizes": transcribe.SIZES_MB},
                "assemblyai": {"has_key": bool(self.cfg.assemblyai_key)}}

    def use_whisper(self, size: str = "small") -> dict:
        self.cfg.transcriber = "whisper"
        self.cfg.whisper_model = size if size in transcribe.SIZES_MB else "small"
        self.cfg.save()
        w = transcribe.Whisper(self.cfg.whisper_model, self.cfg.whisper_device)
        if w.model_dir() is None and not self.download_running:
            self.download_running = True
            threading.Thread(target=self._download, args=(w,), daemon=True).start()
        elif w.model_dir() is not None:
            self.ctl.auto_transcribe()
        return self.transcriber()

    def _download(self, w) -> None:
        emit = self.ctl.events.emit
        last = {"t": 0.0}

        def progress(fraction: float, message: str) -> None:
            if time.time() - last["t"] > 0.3 or fraction >= 1:
                last["t"] = time.time()
                emit("transcriber-progress", {"fraction": fraction, "message": message})
        try:
            w.download(progress)
        except transcribe.TranscribeError as e:
            self.download_running = False
            emit("transcriber-progress", {"fraction": -1, "message": str(e), "failed": True})
            return
        self.download_running = False
        emit("transcriber-ready", self.transcriber())
        self.ctl.auto_transcribe()

    def use_assemblyai(self, key: str) -> dict:
        ok, message = transcribe.AssemblyAI(key).check_key()
        if ok:
            self.cfg.transcriber, self.cfg.assemblyai_key = "assemblyai", key.strip()
            self.cfg.save()
            self.ctl.auto_transcribe()
        return {"ok": ok, "message": message, "transcriber": self.transcriber()}

    def skip_transcriber(self) -> dict:
        self.cfg.transcriber = "skip"
        self.cfg.save()
        return self.transcriber()

    def transcribe(self, keys: list[str] | None = None) -> dict:
        s = self.ctl.need()
        if keys is None:
            used = {c.media for _, c in s.project.clips()}
            keys = [k for k in voice_keys(s.project) if k in used]
        self.ctl.transcripts.enqueue(s, keys)
        return {"queued": keys}

    # ---------- chat ----------
    def history(self) -> list[dict]:
        s = self.ctl.session
        return load_chat(s.folder) if s else []

    def clear(self) -> list[dict]:
        s = self.ctl.need()
        save_chat(s.folder, [])
        return []

    def send(self, message: str, playhead: float = 0.0, selection: list[str] | None = None) -> dict:
        s = self.ctl.need()
        cfg = self.cfg
        self.router.primary = cfg.ai_primary if cfg.ai_primary in PROVIDERS else "claude"
        self.router.enabled = {n for n, ok in cfg.ai_connected.items() if ok}
        with s.lock:
            snapshot = s.project.to_dict()
            project = type(s.project).from_dict(snapshot)
        used = {c.media for _, c in project.clips() if c.audio}
        voices = [k for k in voice_keys(project) if k in used]
        transcripts = {k: t for k in voices if (t := self.ctl.transcripts.load(s, k))}
        silences = {k: media.silences(Path(project.media[k].path), s.files.cache, project.media[k].duration)
                    for k in voices}
        chat = load_chat(s.folder)
        options = {"claude": {"model": cfg.claude_model, "effort": cfg.claude_effort},
                   "codex": {"model": cfg.codex_model, "effort": cfg.codex_effort}}
        chat.append({"role": "user", "text": message, "at": time.time()})
        try:
            answer = ask(self.router, project, message, options=options, playhead=playhead, selection=selection,
                         transcripts=transcripts, silences=silences, history=chat[:-1])
        except AIError as e:
            chat.append({"role": "assistant", "text": str(e), "error": True, "at": time.time()})
            save_chat(s.folder, chat)
            return {"ok": False, "error": str(e), "chat": chat, "state": s.state()}
        changed, edited = answer.project is not None, answer.project
        if changed:
            with s.lock:
                if s.project.to_dict() != snapshot:  # the user edited while the AI was thinking
                    try:
                        edited, _ = apply(s.project, answer.ops)
                    except OpError as e:
                        changed, answer.reply = False, f"{answer.reply} (Not applied: the timeline changed meanwhile: {e})"
                if changed:
                    s.commit(edited, f"AI: {message[:40]}")
        chat.append({"role": "assistant", "text": answer.reply, "provider": answer.provider,
                     "note": answer.provider_note, "changed": changed, "ops": len(answer.ops),
                     "before": answer.before, "after": edited.duration if changed else answer.before,
                     "transcribed": bool(transcripts), "at": time.time()})
        save_chat(s.folder, chat)
        return {"ok": True, "chat": chat, "state": s.state()}
