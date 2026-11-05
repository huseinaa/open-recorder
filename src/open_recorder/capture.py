"""One ffmpeg process: the camera and/or mic that are switched on (feeding the bubble and the level
meter), plus the recording files while recording.

A new process starts for every segment, because a camera can be open in one process only and
Pause has to release it.

The mic level reaches the meter as low-rate PCM over a local UDP socket. Measuring it inside ffmpeg
(astats + ametadata print) halved ffmpeg's speed and cut the camera file to half the length of the
screen file, and ending that branch in anullsink crashed ffmpeg on 4 of 5 stops."""
from __future__ import annotations

import math
import re
import socket
import subprocess
import threading
import time
from array import array
from pathlib import Path
from typing import Callable

from .ffmpeg import NO_WINDOW
from .logs import log
from .win32 import interrupt_time


def preview_size(bubble: int) -> tuple[int, int]:
    """(bubble square side, height of the full 16:9 picture for the camera card, kept even)."""
    return bubble, bubble * 9 // 16 // 2 * 2


def build_command(*, exe: str, cam: str, mic: str, cam_on: bool, mic_on: bool, strict: bool,
                  width: int, height: int, fps: int, video_args: list[str], audio_bitrate: str,
                  preview: tuple[int, int], screen_in: list[str] | None = None,
                  screen_path: Path | None = None, camera_path: Path | None = None,
                  udp_port: int | None = None) -> list[str]:
    """The ffmpeg command line. No side effects, so every on/off combination can be tested.

    Outputs, in order: the screen file, the camera file (camera + voice), the preview frames on
    stdout (the bubble square stacked on the full picture, one pipe so they never drift apart), and
    the mic level over UDP. With the camera off, the voice goes into the screen file."""
    pv, full_h = preview
    cmd = [exe, "-hide_banner", "-nostats", "-y"]
    d = s = None
    if cam_on or mic_on:
        # the camera goes first: it takes ~1.5 s to open, and opened second the screen file
        # started 2.4 s before the camera file
        spec = ":".join(([f"video={cam}"] if cam_on else []) + ([f"audio={mic}"] if mic_on else []))
        cam_opts = (["-vcodec", "mjpeg", "-video_size", f"{width}x{height}", "-framerate", str(fps)]
                    if strict and cam_on else [])
        cmd += ["-rtbufsize", "512M", "-thread_queue_size", "1024", "-f", "dshow", *cam_opts,
                *(["-audio_buffer_size", "50"] if mic_on else []), "-i", spec]
        d = 0
    if screen_path:
        cmd += list(screen_in or [])
        s = 1 if d is not None else 0
    bubble = f"crop=ih:ih,scale={pv}:{pv},hflip,format=rgb24"
    aenc = ["-c:a", "aac", "-b:a", audio_bitrate, "-ar", "48000"]
    # small clusters, flushed as they are written: a crash loses about a second, not a minute
    mkv = ["-cluster_time_limit", "1000", "-flush_packets", "1"]
    if cam_on:
        views = f"[a]{bubble}[sq];[b]scale={pv}:{full_h},hflip,format=rgb24[fl];[sq][fl]vstack[pvo]"
        cmd += ["-filter_complex", f"[{d}:v]split=3[cv][a][b];{views}" if camera_path
                else f"[{d}:v]split=2[a][b];{views}"]
    if screen_path:
        cmd += ["-map", f"{s}:v", *video_args]
        if mic_on and not cam_on:  # no camera file: the voice goes into the screen file
            cmd += ["-map", f"{d}:a", *aenc]
        cmd += [*mkv, str(screen_path)]
    if camera_path and cam_on:
        cmd += ["-map", "[cv]", *video_args, *(["-map", f"{d}:a", *aenc] if mic_on else []), *mkv, str(camera_path)]
    if cam_on:
        cmd += ["-map", "[pvo]", "-f", "rawvideo", "pipe:1"]
    if mic_on and udp_port:
        cmd += ["-map", f"{d}:a", "-ac", "1", "-ar", "8000", "-f", "s16le",
                f"udp://127.0.0.1:{udp_port}?pkt_size=800"]
    return cmd


class Capture:
    def __init__(self, *, cam: str, mic: str, cam_on: bool, mic_on: bool, strict: bool,
                 width: int, height: int, fps: int, video_args: list[str], audio_bitrate: str,
                 preview: tuple[int, int], on_frame: Callable[[bytes, bytes], None],
                 on_level: Callable[[float], None], post: Callable,
                 screen: tuple[str, list[str], str, dict] | None = None, outputs=None, exe: str = "ffmpeg"):
        """screen = (ffmpeg exe, input args, description, monitor) when the screen is recorded.
        outputs = (screen_path or None, camera_path or None) while recording, None for preview."""
        self.outputs = outputs
        self.preview = preview
        self.on_frame, self.on_level, self.post = on_frame, on_level, post
        self.expected_exit = self.started = False
        self.last_err = ""
        self.starts: list[float] = []  # each input's first timestamp, as ffmpeg prints it
        screen_path, camera_path = outputs or (None, None)
        self.has_dshow, self.has_screen = cam_on or mic_on, bool(screen_path)
        self.has_frames = cam_on
        self.sock = None
        if mic_on:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind(("127.0.0.1", 0))
            self.sock.settimeout(0.5)
        how = ""
        if screen_path and screen:
            exe, screen_in, how, monitor = screen
        else:
            screen_in, monitor = None, None
        cmd = build_command(exe=exe, cam=cam, mic=mic, cam_on=cam_on, mic_on=mic_on, strict=strict,
                            width=width, height=height, fps=fps, video_args=video_args,
                            audio_bitrate=audio_bitrate, preview=preview, screen_in=screen_in,
                            screen_path=screen_path, camera_path=camera_path,
                            udp_port=self.sock.getsockname()[1] if self.sock else None)
        what = (f"RECORD {Path(screen_path or camera_path).name}"
                + (f"  screen={monitor['key']} ({how})" if screen_path and monitor else "  screen=off")) \
            if outputs else "PREVIEW"
        log.info(f"{what}  camera={cam if cam_on else 'off'}  mic={mic if mic_on else 'off'}"
                 f"{'' if strict or not cam_on else '  (camera default mode)'}")
        # camera frames are stamped in interrupt time, screen frames in wall-clock time: this
        # converts one to the other, so each segment's screen-to-camera gap can be worked out
        self.clock_delta = time.time() - interrupt_time()
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, creationflags=NO_WINDOW)
        for target in (self._frames, self._stderr, self._watch, self._levels):
            threading.Thread(target=target, daemon=True).start()

    def screen_offset(self) -> float | None:
        """Seconds to add to a camera-file (or voice) time to get the same moment in the screen
        file. None without both inputs."""
        if not (self.has_dshow and self.has_screen) or len(self.starts) < 2:
            return None
        return round((self.starts[0] + self.clock_delta) - self.starts[1], 3)

    def _frames(self):
        if not self.has_frames:
            return
        pv, full_h = self.preview
        cut = pv * pv * 3
        size = cut + pv * full_h * 3
        while True:
            b = self.proc.stdout.read(size)
            if len(b) < size:
                return
            self.on_frame(b[:cut], b[cut:])

    def _levels(self):
        if not self.sock:
            return
        while self.proc.poll() is None:
            try:
                data = self.sock.recv(4096)
            except OSError:
                continue
            samples = array("h", data[: len(data) // 2 * 2])
            if samples:
                rms = math.sqrt(sum(x * x for x in samples) / len(samples))
                self.on_level(20 * math.log10(rms / 32768) if rms > 0 else -120.0)
        self.sock.close()

    def _stderr(self):
        for raw in self.proc.stderr:
            line = raw.decode("utf-8", "replace").rstrip()
            if not line:
                continue
            log.info(f"    ffmpeg: {line}")
            m = re.search(r"Duration: .*start: ([\d.]+)", line)
            if m:
                self.starts.append(float(m.group(1)))
            elif line.startswith("Press [q] to stop"):
                self.started = True
                self.post("started", self)
            elif re.search(r"error|could not|cannot|failed|I/O", line, re.I):
                self.last_err = re.sub(r"^\[[^\]]+\]\s*", "", line)[:120]

    def _watch(self):
        self.post("exited", self, self.proc.wait())

    def stop(self):
        self.expected_exit = True
        try:
            self.proc.stdin.write(b"q")
            self.proc.stdin.flush()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            log.warning("ffmpeg did not stop in 15 s, killed (the segment stays as .mkv)")
            self.proc.kill()
            self.proc.wait()
