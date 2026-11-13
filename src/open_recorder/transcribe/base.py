"""What a transcriber looks like, and where transcripts are kept.

A transcript is a list of words with their start and end in the file, in seconds:
    {"engine": "whisper", "language": "en", "words": [{"w": "okay", "s": 0.12, "e": 0.40}, ...]}
One per media file, in <project>/.openrecorder/transcripts/."""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable

from ..media.cache import cache_path

Progress = Callable[[float, str], None]   # (0 to 1, what is happening)


class TranscribeError(Exception):
    """A failure with a message written for the user."""


class Transcriber(ABC):
    name = ""
    label = ""

    @abstractmethod
    def ready(self) -> tuple[bool, str]:
        """(can it run right now, why not)."""

    @abstractmethod
    def transcribe(self, source: Path, duration: float, progress: Progress) -> dict:
        """{"language", "words": [{"w", "s", "e"}]}."""


def transcript_path(folder: Path, source: Path) -> Path:
    return cache_path(folder, source, "words", "json")


def load(folder: Path, source: Path) -> dict | None:
    path = transcript_path(folder, source)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save(folder: Path, source: Path, data: dict) -> Path:
    path = transcript_path(folder, source)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    return path


def plain_text(data: dict) -> str:
    return " ".join(w["w"] for w in data.get("words", []))
