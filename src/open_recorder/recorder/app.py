"""The recorder itself: the state machine (idle, starting, recording, paused, saving), the actions
behind every button and hotkey, and the 30 ms UI loop.

  rec   start          (Ctrl+Alt+R)      pause / resume          (Ctrl+Alt+P)
  stop  save it        (Ctrl+Alt+R)      restart  throw this recording away and start again
  three fast high beeps = the mic went silent or the recording broke; the bar says which

Anything slow (starting or stopping ffmpeg, joining the segments) runs off the UI thread through
work(), and reports back through a queue the UI loop reads."""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from .. import APP_NAME, ffmpeg
from .capture import Capture, preview_size
from ..config import DEFAULT_OUTPUT, LOG_DIR, Settings
from ..logs import log
from .recording import Recording, recover
from .screens import Screens
from .ui.bar import Bar, fmt_time
from .ui.bubble import Bubble
from .ui.theme import Theme
from ..win32 import (BEEP_ALARM, BEEP_START, BEEP_STOP, beep, keep_awake, release, single_instance,
                    start_hotkeys)


class App:
    def __init__(self, cfg: Settings, selftest: bool = False, visible: bool = False, output: str | None = None,
                 linked: bool = False):
        self.cfg = cfg
        self.linked = linked  # started by the editor: report events on stdout, the editor owns the folder
        self.theme = Theme(cfg.theme)
        self.q: queue.Queue = queue.Queue()
        self.frame = self.frame_full = None
        self.frame_time = self.level_time = 0.0
        self.preview_since = 0.0
        self.level = -120.0
        self.cap: Capture | None = None
        self.rec: Recording | None = None
        self.state = "idle"
        self.busy = False
        self.elapsed = self.seg_start = 0.0
        self.silent_since = None
        self.alarmed = False
        self.strict: dict[str, bool] = {}  # camera -> False once its MJPEG mode has failed
        self.preview_retry = None
        self.message, self.message_color, self.message_until = "", self.theme.muted, 0.0
        self.encoder: str | None = None
        self.awake = False
        self.saved: list[Path] = []
        self.save_problems = 0
        self.pv, self.full_h = preview_size(cfg.bubble_size)

        self.screens = Screens()
        self.screens.refresh()
        if not any(m["key"] == cfg.screen for m in self.screens.monitors):
            cfg.screen = self.screens.primary()["key"]
        threading.Thread(target=self.screens.probe, daemon=True).start()
        self.cams, self.mics = ffmpeg.list_devices()
        self._pick_devices()

        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.report_callback_exception = lambda *a: log.error(f"UI ERROR {a[1]!r}")
        if output:  # this run only: the editor's project folder, not saved as the default
            self.set_output_dir(output)
        else:
            if not cfg.output_dir:
                self.root.withdraw()
                cfg.output_dir = self._ask_folder(first=True) or str(DEFAULT_OUTPUT)
                self.root.deiconify()
            self.set_output_dir(cfg.output_dir)
        cfg.save()

        self.bar = Bar(self, visible=visible)
        self.bubble = Bubble(self.root, cfg.bubble_size, cfg.bubble_margin, self.theme, visible=visible)
        self.bubble.place(self.monitor())
        self.bubble.show(cfg.camera_on)
        start_hotkeys({"record_stop": cfg.hotkey_record_stop, "pause": cfg.hotkey_pause},
                      lambda name: self.post("hotkey", name))
        log.info(f"OPEN  screen={cfg.screen}  camera={cfg.camera}  mic={cfg.mic}  "
                 f"toggles={[k for k in ('screen_on', 'camera_on', 'mic_on') if getattr(cfg, k)]}  "
                 f"saving to {self.out_dir}")
        self.work(self._startup)
        self.root.after(30, self.tick)
        if selftest:
            self._selftest()

    # ---------- small helpers ----------
    def _pick_devices(self):
        cfg = self.cfg
        if cfg.camera not in self.cams:
            cfg.camera = self.cams[0] if self.cams else ""
        if cfg.mic not in self.mics:
            cfg.mic = self.mics[0] if self.mics else ""
        if not self.cams and cfg.camera_on:
            log.info("no camera found, the camera is switched off")
            cfg.camera_on = False
        if not self.mics and cfg.mic_on:
            log.info("no microphone found, the mic is switched off")
            cfg.mic_on = False

    def _ask_folder(self, first=False) -> str | None:
        initial = self.out_dir if hasattr(self, "out_dir") else DEFAULT_OUTPUT.parent
        title = "Where should Open Recorder save your recordings?" if first else "Save recordings in…"
        chosen = filedialog.askdirectory(parent=self.root, title=title, initialdir=str(initial), mustexist=False)
        return chosen or None

    def set_output_dir(self, path) -> None:
        self.out_dir = Path(path)
        self.parts_dir = self.out_dir / ".recording"
        self.parts_dir.mkdir(parents=True, exist_ok=True)

    def monitor(self) -> dict:
        return self.screens.get(self.cfg.screen)

    def can_record(self) -> bool:
        return self.cfg.screen_on or self.cfg.camera_on

    def warnings(self, now: float) -> tuple[bool, bool]:
        cfg = self.cfg
        cam_bad = (cfg.camera_on and not self.busy and self.cap is not None
                   and now - self.preview_since > 5 and now - self.frame_time > 2)
        mic_bad = cfg.mic_on and self.silent_since is not None and now - self.silent_since > 1.5
        return cam_bad, mic_bad

    def status_text(self, now: float) -> tuple[str, str]:
        cfg, t = self.cfg, self.theme
        if now < self.message_until:
            return self.message, self.message_color
        if self.state == "idle":
            if not self.can_record():
                return "Turn on the screen or the camera to record", t.warn
            if not cfg.mic_on:
                return "Mic is off: no voice will be recorded", t.warn
            if not cfg.screen_on:
                return "Screen is off: camera only", t.warn
            if not cfg.camera_on:
                return "Camera is off: the voice goes in the screen file, no face bubble", t.warn
            if not self.screens.probed:
                return "Checking the screens…", t.muted
            return (f"Ready · {cfg.hotkey_record_stop.title()} record / stop · "
                    f"{cfg.hotkey_pause.title()} pause"), t.muted
        return {"starting": ("Starting… talk after the beep", t.muted),
                "recording": (f"Recording · {cfg.hotkey_pause.title()} pause · "
                              f"{cfg.hotkey_record_stop.title()} stop and save", t.muted),
                "paused": ("Paused · resume continues the same video, stop saves it", t.warn),
                "saving": ("Saving…", t.muted)}[self.state]

    def say(self, text: str, color: str | None = None, secs: float = 6.0) -> None:
        self.message, self.message_color, self.message_until = text, color or self.theme.muted, time.time() + secs
        log.info(f"STATUS {text}")

    def post(self, *msg) -> None:
        self.q.put(msg)

    def emit(self, event: str, **data) -> None:
        """One JSON line on stdout for the editor that started this recorder."""
        if not self.linked:
            return
        try:
            sys.stdout.write(json.dumps({"event": event, **data}) + "\n")
            sys.stdout.flush()
        except (OSError, ValueError, AttributeError):
            pass

    def work(self, fn) -> None:
        """Run a state change off the UI thread (stopping ffmpeg can take a second)."""
        self.busy = True

        def run():
            try:
                fn()
            except Exception as e:
                log.exception(f"ERROR in {getattr(fn, '__name__', fn)}: {e!r}")
            self.post("done")
        threading.Thread(target=run, daemon=True).start()

    # ---------- ffmpeg processes ----------
    def _on_frame(self, square: bytes, full: bytes) -> None:
        self.frame, self.frame_full, self.frame_time = square, full, time.time()

    def _on_level(self, db: float) -> None:
        self.level, self.level_time = db, time.time()

    def _capture(self, outputs=None) -> Capture:
        cfg = self.cfg
        screen = None
        if outputs and outputs[0]:
            exe, args, how = self.screens.input_args(self.monitor(), cfg.fps)
            screen = (exe, args, how, self.monitor())
        return Capture(cam=cfg.camera, mic=cfg.mic, cam_on=cfg.camera_on, mic_on=cfg.mic_on,
                       strict=self.strict.get(cfg.camera, True), width=cfg.width, height=cfg.height, fps=cfg.fps,
                       video_args=ffmpeg.video_args(self.encoder or "libx264", cfg.quality, cfg.fps),
                       audio_bitrate=cfg.audio_bitrate, preview=(self.pv, self.full_h),
                       on_frame=self._on_frame, on_level=self._on_level, post=self.post,
                       screen=screen, outputs=outputs, exe=ffmpeg.FFMPEG)

    def _stop_cap(self):
        if self.cap:
            cap, self.cap = self.cap, None
            cap.stop()

    def _start_preview(self):
        self._stop_cap()
        self.frame = self.frame_full = None
        self.preview_since = time.time()
        if self.cfg.camera_on or self.cfg.mic_on:
            self.cap = self._capture()

    def _startup(self):
        self.encoder = ffmpeg.pick_encoder(self.cfg.encoder)
        log.info(f"ENCODER {self.encoder}")
        found, seconds, problems = recover(self.parts_dir, self.out_dir)
        if found:
            if problems:
                self.say(f"Found {found} unfinished recording(s) from last time. {problems} part(s) could not be "
                         f"saved and are kept in {self.out_dir.name}\\.recording (see the log)", self.theme.error, 30)
            else:
                self.say(f"Recovered {found} recording{'s' if found > 1 else ''} ({fmt_time(seconds)}) from last "
                         f"time, saved in {self.out_dir.name}", self.theme.accent, 20)
        self._start_preview()

    def refresh_devices(self):
        cams, mics = ffmpeg.list_devices()
        self.cams, self.mics = cams or self.cams, mics or self.mics
        log.info(f"DEVICES found cameras={self.cams} mics={self.mics}")

    def refresh_screens(self):
        self.screens.refresh()
        if not any(m["key"] == self.cfg.screen for m in self.screens.monitors):
            self.cfg.screen = self.screens.primary()["key"]
            self.cfg.save()
        self.screens.probe()
        self.post("ui", lambda: self.bubble.place(self.monitor()))

    # ---------- the actions ----------
    def _begin_recording(self):
        cfg = self.cfg
        self.rec = Recording(self.parts_dir, cfg.screen_on, cfg.camera_on, cfg.mic_on)
        self.elapsed = 0.0
        log.info(f"BEGIN {self.rec.id}  toggles={self.rec.toggles}")
        self._start_segment()

    def _start_segment(self):
        self.state = "starting"
        waited = time.time()
        while self.cfg.screen_on and not self.screens.probed and time.time() - waited < 15:
            time.sleep(0.1)  # the screens are still being probed (they are at every open)
        while self.encoder is None and time.time() - waited < 30:
            time.sleep(0.1)
        self._stop_cap()
        self.cap = self._capture(outputs=self.rec.next_segment())

    def _pause(self):
        if self.state == "recording":
            self.elapsed += time.time() - self.seg_start
        self.state = "paused"
        self._stop_cap()
        log.info(f"PAUSE at {self.elapsed:.1f} s")
        self._start_preview()

    def _stop(self, then_quit=False):
        if self.state == "recording":
            self.elapsed += time.time() - self.seg_start
        self._stop_cap()
        rec, self.rec = self.rec, None
        self.state = "saving"
        if not then_quit:
            self._start_preview()
        seconds, problems = rec.finalize(self.out_dir) if rec else (0.0, ["nothing to save"])
        if rec:
            self.saved += rec.written
            self.emit("saved", id=rec.id, seconds=round(seconds, 2), problems=len(problems),
                      files=[str(p) for p in rec.written])
        self.save_problems += len(problems)
        self.state = "idle"
        if problems:
            self.say(f"Saved with problems: what was recorded is kept in {self.out_dir.name}\\.recording and "
                     "will be joined the next time the recorder opens (see the log)", self.theme.error, 30)
        else:
            self.say(f"Saved {fmt_time(seconds)} as one video in {self.out_dir.name}  ·  {rec.id}", self.theme.accent, 10)
        if then_quit:
            self.post("quit")

    def _restart(self):
        self._stop_cap()
        if self.rec:
            log.info(f"RESTART: deleted {self.rec.id} ({len(self.rec.segments)} segment(s))")
            self.rec.delete()
        self._begin_recording()

    def _quit(self):
        self._stop_cap()
        self.post("quit")

    def on_record(self):
        """Record when idle, pause when recording, resume when paused."""
        log.info(f"PRESS record/pause/resume (state {self.state}{', busy' if self.busy else ''})")
        if self.busy:
            return
        if self.state == "idle":
            if not self.can_record():
                self.say("Turn on the screen or the camera to record", self.theme.warn, 4)
                return
            self.work(self._begin_recording)
        elif self.state == "recording":
            beep(*BEEP_STOP[:1])
            self.work(self._pause)
        elif self.state == "paused":
            self.work(self._start_segment)

    def on_stop(self):
        log.info(f"PRESS stop (state {self.state}{', busy' if self.busy else ''})")
        if self.busy or self.state not in ("recording", "paused"):
            return
        beep(*BEEP_STOP)
        self.work(self._stop)

    def on_restart(self):
        log.info(f"PRESS restart (state {self.state}{', busy' if self.busy else ''})")
        if self.busy or self.state not in ("recording", "paused"):
            return
        self.work(self._restart)

    def on_close(self):
        if self.busy:
            return
        if self.state in ("recording", "paused"):
            self.work(lambda: self._stop(then_quit=True))
        else:
            self.work(self._quit)

    def on_toggle(self, which: str):
        cfg = self.cfg
        if self.state != "idle" or self.busy:
            self.say("The toggles are locked while recording", self.theme.warn, 3)
            return
        if which == "camera" and not cfg.camera_on and not self.cams:
            self.say("No camera found. Plug one in, then use the camera menu to look again", self.theme.warn, 5)
            return
        if which == "mic" and not cfg.mic_on and not self.mics:
            self.say("No mic found. Plug one in, then use the mic menu to look again", self.theme.warn, 5)
            return
        setattr(cfg, f"{which}_on", not getattr(cfg, f"{which}_on"))
        cfg.save()
        log.info(f"TOGGLE {which} {'on' if getattr(cfg, f'{which}_on') else 'off'}")
        if which == "camera":
            self.bubble.show(cfg.camera_on)
        if which in ("camera", "mic"):
            self.silent_since = None
            self.work(self._start_preview)

    def screen_changed(self, key: str):
        self.cfg.screen = key
        self.cfg.save()
        log.info(f"SCREEN {self.monitor()['label']} ({key})")
        self.bubble.place(self.monitor())

    def device_changed(self, which: str, name: str):
        setattr(self.cfg, which, name)
        self.cfg.save()
        log.info(f"DEVICES camera={self.cfg.camera}  mic={self.cfg.mic}")
        self.bubble.placeholder()
        self.work(self._start_preview)

    def open_folder(self):
        os.startfile(self.out_dir)

    def change_folder(self):
        if self.state != "idle" or self.busy:
            return
        if self.linked:
            self.say("This project's folder is set in the editor", self.theme.warn, 5)
            return
        chosen = self._ask_folder()
        if chosen:
            self.cfg.output_dir = chosen
            self.cfg.save()
            self.set_output_dir(chosen)
            self.say(f"Recordings are now saved in {self.out_dir}", self.theme.accent, 8)

    # ---------- events from ffmpeg and the hotkeys ----------
    def handle(self, msg):
        kind = msg[0]
        if kind == "done":
            self.busy = False
        elif kind == "quit":
            self.root.destroy()
        elif kind == "ui":
            msg[1]()
        elif kind == "started":
            cap = msg[1]
            if cap is self.cap and cap.outputs and self.state == "starting":
                self.state, self.seg_start = "recording", time.time()
                self.silent_since, self.alarmed = None, False
                offset = cap.screen_offset()
                self.rec.set_offset(cap.outputs, offset)
                beep(*BEEP_START)
                if len(self.rec.segments) == 1:
                    self.emit("recording", id=self.rec.id)
                log.info(f"RECORDING {Path(cap.outputs[0] or cap.outputs[1]).name}  screen_offset {offset}")
        elif kind == "exited":
            cap, code = msg[1], msg[2]
            if cap is not self.cap or cap.expected_exit:
                return
            self.cap = None
            cam = self.cfg.camera
            if not cap.started and self.cfg.camera_on and self.strict.get(cam, True):
                log.info(f"camera {cam} refused {self.cfg.width}x{self.cfg.height} MJPEG ({cap.last_err}), "
                         "retrying in its default mode")
                self.strict[cam] = False
                self.work(self._start_segment if cap.outputs else self._start_preview)
                return
            if cap.outputs:
                if self.state == "recording":
                    self.elapsed += time.time() - self.seg_start
                self.state = "paused"
                beep(*BEEP_ALARM)
                self.say(f"Recording broke ({cap.last_err or f'exit {code}'}). What was recorded is kept: "
                         "resume or stop.", self.theme.error, 60)
            else:
                self.say(f"Camera or mic not available: {cap.last_err or f'exit {code}'}. Retrying…",
                         self.theme.error, 4)
            self.preview_retry = time.time() + 3
        elif kind == "hotkey":
            if msg[1] == "record_stop":
                self.on_stop() if self.state in ("recording", "paused") else self.on_record()
            elif msg[1] == "pause" and self.state in ("recording", "paused"):
                self.on_record()

    # ---------- the 30 ms loop ----------
    def tick(self):
        """An error in one pass is logged and the loop carries on: a single error once ended the
        loop, the bar froze on screen and every click was ignored."""
        try:
            if self._tick_once() == "quit":
                return
        except Exception as e:
            log.exception(f"UI ERROR in tick: {e!r}")
        self.root.after(30, self.tick)

    def _tick_once(self):
        try:
            while True:
                msg = self.q.get_nowait()
                self.handle(msg)
                if msg[0] == "quit":
                    return "quit"
        except queue.Empty:
            pass
        now, cfg = time.time(), self.cfg

        busy_recording = self.state != "idle"
        if busy_recording != self.awake:
            self.awake = busy_recording
            keep_awake(busy_recording)

        if self.preview_retry and now > self.preview_retry and not self.busy and self.cap is None \
                and self.state in ("idle", "paused"):
            self.preview_retry = None
            self.work(self._start_preview)

        if cfg.camera_on:
            face = self.frame  # one read: another thread can clear it at any moment
            if face and now - self.frame_time < 2:
                ring = {"recording": self.theme.accent, "starting": self.theme.warn,
                        "paused": self.theme.warn}.get(self.state, self.theme.text)
                self.bubble.paint(face, ring)
            else:
                self.bubble.say("Opening camera…" if self.busy or now - self.preview_since < 5 else "No camera picture")

        level = self.level if now - self.level_time < 1.5 else -120.0
        if cfg.mic_on and level < cfg.silent_mic_db:
            self.silent_since = self.silent_since or now
        else:
            self.silent_since, self.alarmed = None, False
        quiet_for = now - self.silent_since if self.silent_since else 0
        if self.state == "recording" and quiet_for > cfg.silent_mic_seconds and not self.alarmed:
            self.alarmed = True
            beep(*BEEP_ALARM)
            self.say("The mic is silent. Is it switched on and connected?", self.theme.warn, 10)

        self.bar.compose(now)

    def _selftest(self):
        """Record 5 s, pause 2 s, resume 4 s, pause 2 s, resume 4 s, stop, quit: one video at the end."""
        steps = [("idle", 3, self.on_record), ("recording", 5, self.on_record), ("paused", 2, self.on_record),
                 ("recording", 4, self.on_record), ("paused", 2, self.on_record),
                 ("recording", 4, self.on_stop), ("idle", 3, self.on_close)]
        mark = {"t": None}

        def poll():
            if not steps:
                return
            want, secs, fn = steps[0]
            if self.busy or self.state != want:
                mark["t"] = None
            elif mark["t"] is None:
                mark["t"] = time.time()
            elif time.time() - mark["t"] >= secs:
                steps.pop(0)
                mark["t"] = None
                log.info(f"SELFTEST step: {fn.__name__} in state {self.state}")
                fn()
            self.root.after(100, poll)
        self.root.after(100, poll)


def run(config_path=None, selftest: bool = False, visible: bool = False, output: str | None = None,
        linked: bool = False) -> int:
    """Open the recorder. Returns 0, or 1 when it could not run or (in a self-test) did not save."""
    if not ffmpeg.available():
        _message("error", f"{APP_NAME} needs ffmpeg and could not find it.\n\n"
                          f"Install it with:\n    {ffmpeg.INSTALL_HINT}\nthen open {APP_NAME} again.")
        return 1
    mutex = single_instance("OpenRecorder")
    if mutex is None:
        if linked:
            try:
                sys.stdout.write(json.dumps({"event": "busy"}) + "\n")
                sys.stdout.flush()
            except (OSError, ValueError, AttributeError):
                pass
        else:
            _message("info", f"{APP_NAME} is already open (the bar at the top of the screen).")
        return 1
    try:
        app = App(Settings.load(config_path), selftest=selftest, visible=visible, output=output, linked=linked)
        app.emit("open", folder=str(app.out_dir))
        app.root.mainloop()
        app.emit("closed")
        if selftest:
            for p in app.saved:
                print(f"saved {p}")
            return 0 if app.saved and not app.save_problems else 1
        return 0
    except Exception as e:
        log.exception(f"CRASH {e!r}")
        _message("error", f"{APP_NAME} crashed:\n{e}\n\nDetails in {LOG_DIR / 'recorder.log'}")
        return 1
    finally:
        release(mutex)


def _message(kind: str, text: str) -> None:
    r = tk.Tk()
    r.withdraw()
    (messagebox.showerror if kind == "error" else messagebox.showinfo)(APP_NAME, text)
    r.destroy()
