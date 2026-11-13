"""The monitors, and how each one is captured.

Fast capture is ffmpeg's ddagrab (Desktop Duplication, on the GPU, ~30 real fps). It only works when
ffmpeg runs on the graphics chip that monitor is wired to ("Selected output not supported"
otherwise). On a desktop with one GPU that is always true. On a laptop with two chips (integrated +
dedicated, often a laptop panel on one and an external monitor on the other) Windows picks the chip
per .exe path, so two hard links to ffmpeg.exe are made in the app's data folder, one set to each
chip. Which ddagrab output index is which monitor also depends on the chip, so probe() tries each
and matches what it captures against a screenshot of every monitor. A monitor with no working
ddagrab is recorded with gdigrab cropped to it (CPU, ~18 real fps beside the camera)."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import mss
from PIL import Image, ImageChops, ImageStat

from .. import ffmpeg
from ..config import DATA_DIR
from ..logs import log
from ..win32 import set_gpu_preference, wake_display

GPU_LINKS = (("ffmpeg-integrated.exe", 1), ("ffmpeg-dedicated.exe", 2))


def list_monitors() -> list[dict]:
    with mss.mss() as sct:
        raw = sct.monitors[1:]  # [0] is all monitors together
    found = [{"x": m["left"], "y": m["top"], "w": m["width"], "h": m["height"],
              "primary": m["left"] == 0 and m["top"] == 0} for m in raw]
    found.sort(key=lambda m: (m["x"], m["y"]))
    many = len(found) > 1
    for i, m in enumerate(found):
        m["key"] = f"{m['x']},{m['y']},{m['w']},{m['h']}"
        pos = ("Left" if i == 0 else "Right" if i == len(found) - 1 else "Middle") if many else "Main"
        m["short"] = f"{pos}{' · main' if m['primary'] and many else ''}"
        m["label"] = f"{m['short']}  {m['w']}x{m['h']}"
    return found


def grab(sct, m: dict) -> Image.Image:
    shot = sct.grab({"left": m["x"], "top": m["y"], "width": m["w"], "height": m["h"]})
    return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def _gpu_link(name: str, pref: int) -> str | None:
    """A hard link to ffmpeg.exe (a copy on another drive) that Windows runs on one chip."""
    link, src = DATA_DIR / "gpu" / name, Path(ffmpeg.FFMPEG)
    try:
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.exists() and not os.path.samefile(link, src):
            link.unlink()  # ffmpeg was updated since
        if not link.exists():
            try:
                os.link(src, link)
            except OSError:
                shutil.copy2(src, link)
        set_gpu_preference(link, pref)
        return str(link)
    except OSError as e:
        log.warning(f"could not make {name}: {e!r}")
        return None


class Screens:
    def __init__(self):
        self.monitors: list[dict] = []
        self.grab: dict[str, tuple[str, int]] = {}  # monitor key -> (ffmpeg exe, ddagrab output index)
        self.probed = False

    def refresh(self) -> None:
        self.monitors = list_monitors()

    def get(self, key: str) -> dict:
        return next((m for m in self.monitors if m["key"] == key), self.primary())

    def primary(self) -> dict:
        return next((m for m in self.monitors if m["primary"]), self.monitors[0])

    def probe(self) -> None:
        self.probed = False
        wake_display()  # a monitor that went to sleep gives no frames and the probe would miss it
        monitors, grabbed = list(self.monitors), {}
        self._probe_with(ffmpeg.FFMPEG, monitors, grabbed)
        if len(grabbed) < len(monitors):  # a two-chip laptop: try ffmpeg on each chip
            for name, pref in GPU_LINKS:
                exe = _gpu_link(name, pref)
                if exe:
                    self._probe_with(exe, monitors, grabbed)
        for m in monitors:
            if m["key"] not in grabbed:
                log.info(f"screen {m['key']}: no ddagrab output matched, it records with gdigrab (~18 fps)")
        self.grab, self.probed = grabbed, True

    @staticmethod
    def _probe_with(exe: str, monitors: list[dict], grabbed: dict) -> None:
        side = (96, 54)
        n = side[0] * side[1]
        for idx in range(len(monitors) + 1):
            if len(grabbed) == len(monitors):
                return
            try:
                r = subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                                    f"ddagrab=output_idx={idx}:framerate=10,hwdownload,format=bgra,"
                                    f"scale={side[0]}:{side[1]},format=gray",
                                    "-frames:v", "10", "-f", "rawvideo", "-"],
                                   capture_output=True, creationflags=ffmpeg.NO_WINDOW, timeout=10)
            except (OSError, subprocess.TimeoutExpired) as e:
                log.info(f"probe {Path(exe).name} output {idx}: {e!r}")
                continue
            if r.returncode != 0 or len(r.stdout) < n:
                err = r.stderr.decode("utf-8", "replace").strip().splitlines()
                log.info(f"probe {Path(exe).name} output {idx}: exit {r.returncode}, {err[-1] if err else 'no frames'}")
                continue
            captured = Image.frombytes("L", side, r.stdout[-n:])  # the last frame: the first can be blank
            with mss.mss() as sct:
                scores = [(ImageStat.Stat(ImageChops.difference(grab(sct, m).convert("L").resize(side),
                                                                 captured)).mean[0], m["key"]) for m in monitors]
            diff, key = min(scores)
            if diff >= 25 or key in grabbed:
                log.info(f"probe {Path(exe).name} output {idx}: closest screen {key}, difference {diff:.1f}")
            if diff < 25 and key not in grabbed:
                grabbed[key] = (exe, idx)
                log.info(f"screen {key}: ddagrab output {idx} via {Path(exe).name} (difference {diff:.1f})")

    def input_args(self, m: dict, fps: int) -> tuple[str, list[str], str]:
        """(ffmpeg exe to run, its input arguments for this monitor, a short description)."""
        hit = self.grab.get(m["key"])
        if hit:
            # ddagrab's frames are stamped with the wall clock as they arrive: lavfi starts its own
            # timestamps at 0, and the gap to the camera could not be measured otherwise
            exe, idx = hit
            return exe, ["-use_wallclock_as_timestamps", "1", "-thread_queue_size", "1024", "-f", "lavfi", "-i",
                         f"ddagrab=output_idx={idx}:framerate={fps}:draw_mouse=1,hwdownload,format=bgra"], \
                f"ddagrab {idx} via {Path(exe).name}"
        return ffmpeg.FFMPEG, ["-thread_queue_size", "1024", "-f", "gdigrab", "-framerate", str(fps),
                               "-draw_mouse", "1", "-offset_x", str(m["x"]), "-offset_y", str(m["y"]),
                               "-video_size", f"{m['w']}x{m['h']}", "-i", "desktop"], "gdigrab"
