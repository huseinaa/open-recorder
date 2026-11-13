"""AssemblyAI: more accurate, especially with mixed languages, and needs the user's own API key.
Only the sound is sent: it is cut to a small mono file first."""
from __future__ import annotations

import json
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from .. import ffmpeg
from ..logs import log
from .base import Progress, TranscribeError, Transcriber

BASE_URL = "https://api.assemblyai.com/v2"
POLL_SECONDS = 3
TIMEOUT_MINUTES = 30


class AssemblyAI(Transcriber):
    name = "assemblyai"
    label = "AssemblyAI"

    def __init__(self, key: str, base_url: str = BASE_URL):
        self.key = (key or "").strip()
        self.base_url = base_url.rstrip("/")

    def ready(self) -> tuple[bool, str]:
        return (True, "") if self.key else (False, "Add your AssemblyAI API key.")

    # ---------- HTTP ----------
    def _request(self, method: str, path: str, data: bytes | None = None, content_type: str = "application/json"):
        req = urllib.request.Request(f"{self.base_url}{path}", data=data, method=method,
                                     headers={"authorization": self.key, "content-type": content_type})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise TranscribeError("AssemblyAI did not accept the API key.") from e
            body = e.read().decode("utf-8", "replace")[:300]
            raise TranscribeError(f"AssemblyAI answered {e.code}: {body}") from e
        except urllib.error.URLError as e:
            raise TranscribeError(f"Could not reach AssemblyAI: {e.reason}") from e

    def check_key(self) -> tuple[bool, str]:
        if not self.key:
            return False, "Paste your AssemblyAI API key."
        try:
            self._request("GET", "/transcript?limit=1")
        except TranscribeError as e:
            return False, str(e)
        return True, "AssemblyAI is connected"

    # ---------- transcribing ----------
    def transcribe(self, source: Path, duration: float, progress: Progress) -> dict:
        ok, why = self.ready()
        if not ok:
            raise TranscribeError(why)
        with tempfile.TemporaryDirectory(prefix="or-aai-") as tmp:
            audio = Path(tmp) / "voice.m4a"
            progress(0.02, "Preparing the sound…")
            r = ffmpeg.run([ffmpeg.FFMPEG, "-v", "error", "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000",
                            "-c:a", "aac", "-b:a", "48k", str(audio)], encoding="utf-8", errors="replace")
            if r.returncode != 0 or not audio.exists():
                raise TranscribeError(f"Could not read the sound of {source.name}.")
            progress(0.08, "Uploading the sound…")
            upload = self._request("POST", "/upload", audio.read_bytes(), "application/octet-stream")
        job = self._request("POST", "/transcript", json.dumps({
            "audio_url": upload["upload_url"], "language_detection": True,
            "punctuate": True, "format_text": True}).encode("utf-8"))
        started = time.time()
        while True:
            status = self._request("GET", f"/transcript/{job['id']}")
            state = status.get("status")
            if state == "completed":
                break
            if state == "error":
                raise TranscribeError(f"AssemblyAI could not transcribe it: {status.get('error')}")
            if time.time() - started > TIMEOUT_MINUTES * 60:
                raise TranscribeError("AssemblyAI took too long. Try again.")
            waited = time.time() - started
            expected = max(20.0, duration * 0.3)
            progress(min(0.95, 0.1 + 0.85 * waited / expected), "AssemblyAI is transcribing…")
            time.sleep(POLL_SECONDS)
        words = [{"w": w["text"], "s": round(w["start"] / 1000, 3), "e": round(w["end"] / 1000, 3)}
                 for w in status.get("words") or [] if w.get("text")]
        log.info(f"ASSEMBLYAI {source.name}: {len(words)} words ({status.get('language_code')})")
        return {"engine": self.name, "language": status.get("language_code") or "", "words": words}
