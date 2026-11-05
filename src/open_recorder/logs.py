"""One log file for everything the recorder and ffmpeg do. It is the first place to look when a
recording goes wrong."""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

log = logging.getLogger("open_recorder")


def setup(log_dir: Path, console: bool = False) -> Path:
    """Log to <log_dir>/recorder.log (rotated at 2 MB, 3 old files kept), and to the terminal too
    when `console` is set (for --check and --selftest)."""
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "recorder.log"
    if not log.handlers:
        handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%Y-%m-%d %H:%M:%S"))
        log.addHandler(handler)
        if console and sys.stderr is not None:
            stream = logging.StreamHandler(sys.stderr)
            stream.setFormatter(logging.Formatter("%(message)s"))
            stream.setLevel(logging.WARNING)
            log.addHandler(stream)
        log.setLevel(logging.INFO)
    return path
