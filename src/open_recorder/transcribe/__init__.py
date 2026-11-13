"""Turning speech into timed words, so the AI knows what was said and where."""
from .assemblyai import AssemblyAI
from .base import TranscribeError, Transcriber, load, plain_text, save
from .whisper import SIZES_MB, Whisper


def from_settings(cfg) -> Transcriber | None:
    """The engine the user picked in the app, or None when they skipped it."""
    if cfg.transcriber == "whisper":
        return Whisper(cfg.whisper_model, cfg.whisper_device)
    if cfg.transcriber == "assemblyai":
        return AssemblyAI(cfg.assemblyai_key)
    return None


__all__ = ["AssemblyAI", "SIZES_MB", "TranscribeError", "Transcriber", "Whisper", "from_settings", "load",
           "plain_text", "save"]
