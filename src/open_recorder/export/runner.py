"""Run an export: draw the masks, write the graph file, run ffmpeg, report progress, allow cancel."""
from __future__ import annotations

import subprocess
import tempfile
import threading
from collections import deque
from pathlib import Path
from typing import Callable

from .. import ffmpeg
from ..core import Project
from ..logs import log
from . import masks as mask_files
from .graph import GRAPH_TOKEN, build

QUALITY = {"high": 17, "normal": 21, "small": 26}  # lower = better and bigger


class ExportJob:
    def __init__(self, project: Project, out: Path, work_dir: Path, encoder: str = "auto",
                 quality: str = "normal", on_progress: Callable[[float], None] | None = None,
                 on_done: Callable[[bool, str], None] | None = None):
        self.project, self.out, self.work_dir = project, Path(out), Path(work_dir)
        self.encoder, self.quality = encoder, quality
        self.on_progress = on_progress or (lambda f: None)
        self.on_done = on_done or (lambda ok, msg: None)
        self.proc: subprocess.Popen | None = None
        self.cancelled = False
        self._errors: deque[str] = deque(maxlen=30)

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def cancel(self) -> None:
        self.cancelled = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()

    def _run(self) -> None:
        try:
            ok, message = self._export()
        except Exception as e:  # anything unexpected still reaches the UI
            log.exception(f"EXPORT crashed: {e!r}")
            ok, message = False, str(e)
        self.on_done(ok, message)

    def _export(self) -> tuple[bool, str]:
        encoder = ffmpeg.pick_encoder(self.encoder)
        q = QUALITY.get(self.quality, QUALITY["normal"])
        masks_dir = self.work_dir / "masks"
        plan = build(self.project, self.out, ffmpeg.video_args(encoder, q, self.project.sequence.fps), masks_dir,
                     ffmpeg_exe=ffmpeg.FFMPEG)
        for spec in plan.masks:
            mask_files.make(spec, masks_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        graph_file = Path(tempfile.mkstemp(suffix=".txt", prefix="graph-", dir=self.work_dir)[1])
        graph_file.write_text(plan.graph, encoding="utf-8")
        args = [str(graph_file) if a == GRAPH_TOKEN else a for a in plan.args]
        self.out.parent.mkdir(parents=True, exist_ok=True)
        log.info(f"EXPORT {self.out.name}  {plan.duration:.1f}s  encoder {encoder}  "
                 f"{len(plan.masks)} mask(s), graph {graph_file.name}")
        self.proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                     encoding="utf-8", errors="replace", creationflags=ffmpeg.NO_WINDOW)
        threading.Thread(target=self._read_errors, daemon=True).start()
        for line in self.proc.stdout:
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and value.isdigit():
                self.on_progress(min(1.0, int(value) / 1e6 / plan.duration))
        code = self.proc.wait()
        try:
            graph_file.unlink()
        except OSError:
            pass
        if self.cancelled:
            self.out.unlink(missing_ok=True)
            return False, "Export cancelled"
        if code != 0:
            detail = " ".join(self._errors)[-400:]
            log.error(f"EXPORT failed ({code}): {detail}")
            return False, f"ffmpeg stopped with an error: {detail or code}"
        self.on_progress(1.0)
        return True, str(self.out)

    def _read_errors(self) -> None:
        for line in self.proc.stderr:
            line = line.strip()
            if line:
                self._errors.append(line)
