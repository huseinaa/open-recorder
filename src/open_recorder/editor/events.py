"""Python → page messages: progress, new takes, transcripts, the recorder's state. The page
listens with OR.on(name, fn)."""
from __future__ import annotations

import json
import threading

from ..logs import log


class Events:
    def __init__(self):
        self.window = None
        self._lock = threading.Lock()

    def attach(self, window) -> None:
        self.window = window

    def emit(self, name: str, payload=None) -> None:
        window = self.window
        if window is None:
            return
        script = f"window.OR && window.OR.emit({json.dumps(name)}, {json.dumps(payload, default=str)})"
        try:
            with self._lock:
                window.evaluate_js(script)
        except Exception as e:  # the window may be closing
            log.debug(f"EVENT {name} not delivered: {e!r}")
