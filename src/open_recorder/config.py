"""Settings, kept as JSON in the user's config folder. Every toggle and device pick in the bar is
saved here, so the recorder opens the way it was left."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir, user_log_dir, user_videos_dir

from . import APP_NAME
from .logs import log

CONFIG_DIR = Path(user_config_dir(APP_NAME, appauthor=False))
DATA_DIR = Path(user_data_dir(APP_NAME, appauthor=False))
LOG_DIR = Path(user_log_dir(APP_NAME, appauthor=False))
DEFAULT_CONFIG = CONFIG_DIR / "config.json"
DEFAULT_OUTPUT = Path(user_videos_dir()) / APP_NAME

# Older key names, read once and written back under the new name.
LEGACY = {"nvenc_cq": "quality"}


@dataclass
class Settings:
    output_dir: str = ""          # empty: asked on first launch
    camera: str = ""              # empty: the first camera found
    mic: str = ""                 # empty: the first mic found
    screen: str = ""              # "x,y,w,h" of the monitor; empty: the main one
    screen_on: bool = True
    camera_on: bool = True
    mic_on: bool = True
    width: int = 1920             # the camera mode asked for first (MJPEG); falls back to the default mode
    height: int = 1080
    fps: int = 30
    encoder: str = "auto"         # auto, h264_nvenc, h264_qsv, h264_amf or libx264
    quality: int = 19             # lower = better and bigger (cq / crf / qp, depending on the encoder)
    audio_bitrate: str = "192k"
    bubble_size: int = 300        # px, the face bubble on screen
    bubble_margin: int = 25       # px from the bottom-left corner of the recorded screen
    bar_scale: float = 0.75       # 1.0 = the full-size bar
    hotkey_record_stop: str = "ctrl+alt+r"
    hotkey_pause: str = "ctrl+alt+p"
    silent_mic_db: float = -75    # below this the mic counts as silent
    silent_mic_seconds: float = 4  # silent this long while recording = an alarm
    theme: dict = field(default_factory=dict)  # colour overrides, see recorder/ui/theme.py
    # ---- the editor ----
    recent: dict = field(default_factory=dict)   # project folder -> when it was last opened (unix time)
    editor: dict = field(default_factory=dict)   # window and panel sizes, last export choices
    # ---- the AI (runs on the user's own Claude or Codex subscription) ----
    ai_primary: str = "claude"    # which one answers first when both are connected
    ai_connected: dict = field(default_factory=dict)  # provider -> True once a test run worked
    claude_model: str = "sonnet"  # empty: Claude Code's own default
    claude_effort: str = "medium"
    codex_model: str = ""         # empty: Codex's own default
    codex_effort: str = "medium"
    transcriber: str = ""         # "", "whisper", "assemblyai", or "skip" when the user said not now
    whisper_model: str = "small"  # tiny, base, small or medium
    whisper_device: str = "cpu"   # cpu, or cuda with the NVIDIA libraries installed
    assemblyai_key: str = ""

    def __post_init__(self):
        self._path = DEFAULT_CONFIG

    @property
    def path(self) -> Path:
        return self._path

    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> "Settings":
        path = Path(path) if path else DEFAULT_CONFIG
        data = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("not a JSON object")
            except (ValueError, OSError) as e:
                broken = path.with_suffix(".broken.json")
                log.warning(f"settings file {path} could not be read ({e!r}), kept as {broken.name}, using defaults")
                try:
                    os.replace(path, broken)
                except OSError:
                    pass
                data = {}
        for old, new in LEGACY.items():
            if old in data and new not in data:
                data[new] = data[old]
        defaults = cls()
        values = {}
        for f in fields(cls):
            if f.name not in data:
                continue
            value, want = data[f.name], type(getattr(defaults, f.name))
            if want is bool and isinstance(value, bool):
                values[f.name] = value
            elif want is int and isinstance(value, int) and not isinstance(value, bool):
                values[f.name] = value
            elif want is float and isinstance(value, (int, float)) and not isinstance(value, bool):
                values[f.name] = float(value)
            elif want in (str, dict) and isinstance(value, want):
                values[f.name] = value
            else:
                log.warning(f"setting {f.name}={value!r} is not a {want.__name__}, using {getattr(defaults, f.name)!r}")
        settings = cls(**values)
        settings._path = path
        return settings

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def save(self) -> None:
        """Written to a temp file and renamed, so a crash never leaves half a settings file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self._path)
