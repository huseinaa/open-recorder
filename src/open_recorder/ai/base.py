"""What every AI provider looks like, and the errors they raise.

A provider is a command-line agent the user installed and signed into themselves (Claude Code or
Codex). The app never handles a login: it runs the CLI on the user's machine, with any API key
removed from its environment, so the work is billed to the user's own subscription."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
TIMEOUT_SECONDS = 240


class AIError(Exception):
    """A failure with a message written for the person who asked."""


class NotInstalled(AIError):
    pass


class NotSignedIn(AIError):
    pass


class LimitReached(AIError):
    def __init__(self, message: str, resets_at: datetime | None = None):
        super().__init__(message)
        self.resets_at = resets_at


class Unavailable(AIError):
    """Too slow, or the CLI failed for another reason. Another provider may still work."""


@dataclass
class Status:
    provider: str
    state: str            # not_installed, not_signed_in, connected, limited, error, unchecked
    message: str = ""

    def to_dict(self) -> dict:
        return {"provider": self.provider, "state": self.state, "message": self.message}


class Provider(ABC):
    name: str = ""
    label: str = ""
    command: str = ""
    install_hint: str = ""
    install_url: str = ""
    login_hint: str = ""
    api_credentials: tuple[str, ...] = ()

    def binary(self) -> str | None:
        return shutil.which(self.command)

    def environment(self) -> dict[str, str]:
        """The user's own environment minus any API key, so the subscription pays, not a key."""
        return {k: v for k, v in os.environ.items() if k.upper() not in self.api_credentials}

    @abstractmethod
    def run(self, system: str, prompt: str, schema: dict, model: str = "", effort: str = "",
            timeout: int = TIMEOUT_SECONDS) -> dict:
        """The structured answer as a dict, or an AIError."""

    def check(self, model: str = "", effort: str = "low") -> Status:
        """Installed? Signed in? Proven with one tiny real run."""
        if not self.binary():
            return Status(self.name, "not_installed", f"{self.label} is not installed. {self.install_hint}")
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
        try:
            self.run("Answer with ok set to true.", "Are you there?", schema, model=model, effort=effort, timeout=120)
        except NotInstalled as e:
            return Status(self.name, "not_installed", str(e))
        except NotSignedIn as e:
            return Status(self.name, "not_signed_in", str(e))
        except LimitReached as e:
            return Status(self.name, "limited", str(e))
        except AIError as e:
            return Status(self.name, "error", str(e))
        return Status(self.name, "connected", f"{self.label} is connected")


# ---------- shared helpers ----------
def workdir() -> Path:
    """An empty folder to run in, so no project instructions or settings ride along."""
    path = Path(tempfile.gettempdir()) / "open-recorder-ai"
    path.mkdir(exist_ok=True)
    return path


def content_file(prefix: str, content: str, suffix: str = ".md") -> Path:
    """A file named by its content, so the same prompt is written once and reused."""
    path = workdir() / f"{prefix}-{hashlib.sha256(content.encode()).hexdigest()[:16]}{suffix}"
    if not path.is_file():
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
    return path


def is_limit(text: str) -> bool:
    text = text.lower()
    return ("limit" in text and any(w in text for w in ("usage", "rate", "hit your", "reached"))) \
        or "too many requests" in text or re.search(r"\bstatus\W+429\b|\b429 too many", text) is not None


_UNITS = {"day": timedelta(days=1), "hour": timedelta(hours=1), "hr": timedelta(hours=1),
          "minute": timedelta(minutes=1), "min": timedelta(minutes=1), "second": timedelta(seconds=1),
          "sec": timedelta(seconds=1)}


def resets_at(text: str, now: datetime | None = None) -> datetime | None:
    """When a limit message says the limit resets, if it says so in a form we can read."""
    now = now or datetime.now(timezone.utc)
    epoch = re.search(r"\|(\d{10})\b", text)
    if epoch:
        moment = datetime.fromtimestamp(int(epoch.group(1)), timezone.utc)
        return moment if moment > now else None
    seconds = re.search(r"resets?_in_seconds\W+(\d+)", text)
    if seconds:
        return now + timedelta(seconds=int(seconds.group(1)))
    span = re.search(r"(?:resets?|try again) in ([0-9a-z ,]+)", text, re.I)
    if span:
        total = sum((int(n) * _UNITS[u.lower()] for n, u in
                     re.findall(r"(\d+)\s*(day|hour|hr|minute|min|second|sec)", span.group(1), re.I)), timedelta())
        if total:
            return now + total
    return None


def unescape(value):
    """Models sometimes over-escape quotes inside structured output; strip the leftover \\"."""
    if isinstance(value, str):
        return value.replace('\\"', '"')
    if isinstance(value, list):
        return [unescape(v) for v in value]
    if isinstance(value, dict):
        return {k: unescape(v) for k, v in value.items()}
    return value


def run_cli(command: list[str], prompt: str, env: dict, timeout: int, label: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, input=prompt, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=env, cwd=workdir(), timeout=timeout, creationflags=NO_WINDOW)
    except FileNotFoundError as e:
        raise NotInstalled(f"{label} is not installed.") from e
    except subprocess.TimeoutExpired as e:
        raise Unavailable(f"{label} took longer than {timeout} seconds. Try again.") from e
