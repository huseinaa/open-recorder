"""Colours, icons and fonts. Any colour can be changed from the settings file, for example
"theme": {"accent": "#E5484D"} for a red record button."""
from __future__ import annotations

import os
import re
from pathlib import Path

from ..logs import log

DEFAULT = {
    "window": "#111318",       # the bar
    "card": "#1C1F26",         # the three device cards
    "strip": "#16191F",        # the bottom strip of a card
    "well": "#141720",         # behind the live pictures
    "border": "#262A33",
    "track": "#2A2E38",        # meter track, round buttons
    "accent": "#2F6BFF",       # record button, toggles, meter, recording ring
    "accent_deep": "#0051BD",  # record button while busy
    "blink": "#1A2F66",        # the recording dot's off phase
    "toggle_on_locked": "#24427F",
    "toggle_off_locked": "#2E323C",
    "warn": "#FFC53D",
    "error": "#FF5A5F",
    "text": "#F2F4F8",
    "muted": "#8A8F9C",
    "dim": "#4A4F5C",
    "off": "#3A3F4B",
}

# Segoe Fluent / MDL2 icon glyphs, shipped with Windows 10 and 11.
GLYPH = {"screen": "\uE7F4", "camera": "\uE714", "mic": "\uE720", "down": "\uE70D", "min": "\uE921",
         "close": "\uE8BB", "pause": "\uE769", "play": "\uE768", "stop": "\uE71A", "restart": "\uE72C",
         "expand": "\uE740", "folder": "\uE8B7"}

# The windows' transparent colour: never used for anything visible.
KEY, KEY_RGB = "#010203", (1, 2, 3)

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


class Theme:
    def __init__(self, overrides: dict | None = None):
        self._c = dict(DEFAULT)
        for name, value in (overrides or {}).items():
            if name in DEFAULT and isinstance(value, str) and _HEX.match(value):
                self._c[name] = value
            else:
                log.warning(f"theme: ignored {name}={value!r} (known names: {', '.join(DEFAULT)}; colours as #RRGGBB)")

    def __getattr__(self, name: str) -> str:
        try:
            return self._c[name]
        except KeyError:
            raise AttributeError(name) from None


def _font_file(*patterns: str) -> str | None:
    dirs = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"]
    for pattern in patterns:
        for d in dirs:
            hits = sorted(d.glob(pattern)) if d.exists() else []
            if hits:
                return str(hits[0])
    return None


# Inter when it is installed, Segoe UI (always on Windows) otherwise.
FONT_REGULAR = _font_file("Inter-Regular.ttf", "Inter_18pt-Regular.ttf", "segoeui.ttf")
FONT_BOLD = _font_file("Inter-SemiBold.ttf", "Inter_18pt-SemiBold.ttf", "seguisb.ttf", "segoeuib.ttf")
FONT_ICONS = _font_file("SegoeIcons.ttf", "segmdl2.ttf")
