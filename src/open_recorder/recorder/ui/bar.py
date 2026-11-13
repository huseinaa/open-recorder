"""The control bar at the top of the screen: Screen, Camera and Mic cards (each with an on/off
toggle and a device menu), the record button, and a status line. Minimize turns it into a small
timer pill. Hidden from capture, so it never shows in a recording.

It is drawn with Pillow into one image: a static layer, rebuilt only when something changes, plus
the live parts (camera picture, screen thumbnail, mic meter, timer) pasted on every frame. Shapes
are drawn at 3x and scaled down so the edges are smooth."""
from __future__ import annotations

import re
import threading
import time
import tkinter as tk

import mss
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageTk

from ...logs import log
from ..screens import grab
from ...win32 import hide_from_capture
from .theme import FONT_BOLD, FONT_ICONS, FONT_REGULAR, GLYPH, KEY, KEY_RGB


def short_device(name: str) -> str:
    """'Microphone (Wireless microphone)' -> 'Wireless microphone'."""
    m =re.fullmatch(r"Microphone(?: Array)? \((.+)\)", name or "")
    return m.group(1) if m else (name or "")


class Bar:
    def __init__(self, app, visible: bool = False):
        self.app = app
        self.t = app.theme
        r = self.root = app.root
        self.U = float(app.cfg.bar_scale)               # shapes scale with it
        self.S0 = r.winfo_fpixels("1i") / 96.0           # the display's scale
        self.S = self.S0 * self.U
        self._fonts = {}
        self.compact = False
        self.hint = ""
        self.regions, self.dyn = [], {}
        self.bg_key = None
        self.screen_thumb = None

        r.overrideredirect(True)
        r.attributes("-topmost", True)
        r.configure(bg=KEY)
        r.attributes("-transparentcolor", KEY)
        self.bg = self.render_bg(False, False)
        self.photo = ImageTk.PhotoImage(self.bg)
        self.canvas = tk.Canvas(r, width=self.bg.size[0], height=self.bg.size[1], bg=KEY,
                                highlightthickness=0, bd=0)
        self.canvas.pack()
        self.item = self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<Leave>", lambda e: setattr(self, "hint", ""))
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.place(first=True)
        if not visible:
            hide_from_capture(r)
        threading.Thread(target=self._screen_thumbs, daemon=True).start()

    # ---------- drawing ----------
    def px(self, v: float) -> int:
        return int(round(v * self.S))

    def font(self, size, bold=False, icon=False, k=1):
        key = (size, bold, icon, k)
        if key not in self._fonts:
            path = FONT_ICONS if icon else (FONT_BOLD if bold else FONT_REGULAR)
            try:  # text keeps a readable minimum size when the bar is scaled down
                dp = max(size * self.U, 5.0 if icon else 6.5)
                self._fonts[key] = ImageFont.truetype(path, max(6, int(round(dp * self.S0 * k))))
            except (OSError, TypeError):
                self._fonts[key] = ImageFont.load_default()
        return self._fonts[key]

    @staticmethod
    def fit(text, f, width):
        if f.getlength(text) <= width:
            return text
        while text and f.getlength(text + "…") > width:
            text = text[:-1]
        return text.rstrip() + "…"

    def render_bg(self, cam_bad: bool, mic_bad: bool) -> Image.Image:
        """The static layer: everything except the camera picture, meter, timer and status text."""
        app, cfg, t = self.app, self.app.cfg, self.t
        k = 3
        W, H = (262, 48) if self.compact else (572, 178)
        w, h = self.px(W), self.px(H)
        big = Image.new("RGBA", (w * k, h * k), (0, 0, 0, 0))
        d = ImageDraw.Draw(big)
        S = self.S * k

        def q(*v):
            return [x * S for x in v]

        def rr(x0, y0, x1, y1, r, fill=None, outline=None, width=0):
            d.rounded_rectangle(q(x0, y0, x1, y1), radius=r * S, fill=fill, outline=outline,
                                width=int(width * S) if width else 0)

        def circ(cx, cy, r, fill=None, outline=None, width=0):
            d.ellipse(q(cx - r, cy - r, cx + r, cy + r), fill=fill, outline=outline,
                      width=int(width * S) if width else 0)

        def icon(cx, cy, name, size, fill):
            d.text(q(cx, cy), GLYPH[name], font=self.font(size, icon=True, k=k), fill=fill, anchor="mm")

        texts, regions, dyn = [], [], {}
        live = app.state in ("recording", "paused")
        locked = app.state != "idle" or app.busy

        if self.compact:
            rr(0, 0, W, H, 24, fill=t.window, outline=t.border, width=1)
            if live:
                dyn["dot"] = (20, 24, 4.5)
                dyn["timer"] = (32, 24, 14, "lm")
                paused = app.state == "paused"
                circ(160, 24, 15, fill=t.warn if paused else t.track)
                icon(160, 24, "play" if paused else "pause", 11, t.window if paused else t.text)
                circ(198, 24, 15, fill=t.track)
                icon(198, 24, "stop", 11, t.text)
                regions += [("pause", 143, 7, 177, 41), ("stop", 181, 7, 215, 41)]
            else:
                busy = app.state in ("starting", "saving")
                circ(26, 24, 15, fill=(t.accent_deep if busy else t.accent) if app.can_record() else t.off)
                texts.append((26, 24, "…" if busy else "rec", self.font(8, True), t.text, "mm"))
                texts.append((50, 24, {"starting": "Starting", "saving": "Saving"}.get(app.state, "Ready"),
                              self.font(9.5), t.muted, "lm"))
                regions.append(("rec", 9, 7, 43, 41))
            icon(238, 24, "expand", 11, t.muted)
            regions.append(("min", 222, 6, 256, 42))
            regions.append(("title", 0, 0, W, H))
        else:
            rr(0, 0, W, H, 14, fill=t.window, outline=t.border, width=1)
            # title strip: the mark, the name, folder / minimize / close
            rr(14, 9, 32, 27, 5, fill=t.accent)
            circ(23, 18, 4, fill=t.text)
            texts.append((40, 18, "Open Recorder", self.font(10, True), t.text, "lm"))
            icon(W - 82, 18, "folder", 9, t.muted)
            icon(W - 52, 18, "min", 9, t.muted)
            icon(W - 22, 18, "close", 9, t.muted)
            regions += [("folder", W - 96, 4, W - 68, 32), ("min", W - 66, 4, W - 38, 32),
                        ("close", W - 36, 4, W - 8, 32)]
            # the three cards
            mon = app.monitor()
            labels = {"screen": mon["short"], "camera": cfg.camera or "No camera", "mic": short_device(cfg.mic) or "No mic"}
            for i, name in enumerate(("screen", "camera", "mic")):
                x0, y0 = 12 + i * 144, 38
                x1, y1 = x0 + 134, y0 + 108
                on = getattr(cfg, f"{name}_on")
                rr(x0, y0, x1, y1, 10, fill=t.strip)
                rr(x0, y0, x1, y0 + 80, 10, fill=t.card)
                d.rectangle(q(x0, y0 + 70, x1, y0 + 80), fill=t.card)
                cx = x0 + 67
                if name in ("camera", "screen"):
                    # the live picture fills this: the full camera view, or the chosen screen
                    cy = y0 + 40
                    rr(x0 + 6, y0 + 6, x1 - 6, y0 + 74, 6, fill=t.well)
                    icon(cx, cy, name, 24 if name == "camera" else 26, t.muted if on else t.dim)
                    if on:
                        dyn[f"{name}_view"] = (x0 + 6, y0 + 6, x1 - 6, y0 + 74)
                        if name == "camera":
                            dyn["campic"] = (cx, cy)
                else:
                    cy = y0 + 31
                    icon(cx, cy, "mic", 24, t.text if on else t.dim)
                    rr(x0 + 22, y0 + 56, x0 + 112, y0 + 62, 3, fill=t.track)
                    if on:
                        dyn["meter"] = (x0 + 22, y0 + 56, x0 + 112, y0 + 62)
                        dyn["nosignal"] = (cx, y0 + 71)
                if not on:  # the "off" slash, cut out of the card colour
                    d.line(q(cx - 17, cy - 15, cx + 17, cy + 15), fill=t.card, width=int(5 * S))
                    d.line(q(cx - 17, cy - 15, cx + 17, cy + 15), fill=t.muted, width=int(2 * S))
                # toggle pill
                pill_on, pill_off = (t.accent, t.off) if not locked else (t.toggle_on_locked, t.toggle_off_locked)
                rr(x0 + 10, y0 + 86, x0 + 38, y0 + 100, 7, fill=pill_on if on else pill_off)
                circ(x0 + 31 if on else x0 + 17, y0 + 93, 5, fill=t.text if on else t.muted)
                texts.append((x0 + 45, y0 + 93, labels[name], self.font(9), t.text if on else t.muted, "lm", 72))
                icon(x0 + 124, y0 + 93, "down", 7, t.muted)
                regions += [(f"toggle_{name}", x0 + 4, y0 + 82, x0 + 42, y0 + 104),
                            (f"menu_{name}", x0 + 42, y0 + 82, x1, y0 + 104)]
                if (name == "camera" and cam_bad) or (name == "mic" and mic_bad):
                    rr(x0, y0, x1, y1, 10, outline=t.warn, width=1.5)
            # the record side
            cx, cy = 503, 84
            if app.state == "idle":
                circ(cx, cy, 34, fill=t.accent if app.can_record() and not app.busy else t.off)
                texts.append((cx, cy - 1, "rec", self.font(15, True), t.text, "mm"))
                texts.append((cx, 136, "Start", self.font(9), t.muted, "mm"))
                regions.append(("rec", cx - 36, cy - 36, cx + 36, cy + 36))
            elif app.state in ("starting", "saving"):
                circ(cx, cy, 34, fill=t.accent_deep)
                texts.append((cx, cy - 2, "…", self.font(18, True), t.text, "mm"))
                texts.append((cx, 136, "Starting" if app.state == "starting" else "Saving", self.font(9), t.muted, "mm"))
            else:
                paused = app.state == "paused"
                dyn["dot"] = (cx - 47, 62, 4.5)
                dyn["timer"] = (cx + 5, 62, 19, "mm")
                for name, x, glyph, fill, color in (
                        ("pause", cx - 38, "play" if paused else "pause", t.warn if paused else t.track,
                         t.window if paused else t.text),
                        ("stop", cx, "stop", t.track, t.text),
                        ("restart", cx + 38, "restart", t.track, t.text)):
                    circ(x, 108, 16, fill=fill)
                    icon(x, 108, glyph, 12, color)
                    regions.append((name, x - 18, 90, x + 18, 126))
                texts.append((cx, 136, "Paused" if paused else "Recording", self.font(9),
                              t.warn if paused else t.muted, "mm"))
            dyn["status"] = (16, 163)
            regions.append(("title", 0, 0, W, 34))

        img = big.resize((w, h), Image.LANCZOS)
        base = Image.new("RGB", (w, h), KEY_RGB)
        base.paste(img, (0, 0), img)
        dr = ImageDraw.Draw(base)
        for item in texts:
            x, y, text, f, fill, anchor = item[:6]
            if len(item) > 6:
                text = self.fit(text, f, self.px(item[6]))
            dr.text((self.px(x), self.px(y)), text, font=f, fill=fill, anchor=anchor)
        self.regions = [(n, self.px(a), self.px(b), self.px(c), self.px(e)) for n, a, b, c, e in regions]
        self.dyn = dyn
        return base

    def compose(self, now: float) -> None:
        """Called every 30 ms: the static layer plus the live parts."""
        app, cfg, t = self.app, self.app.cfg, self.t
        cam_bad, mic_bad = app.warnings(now)
        key = (self.compact, app.state, app.busy, cfg.screen_on, cfg.camera_on, cfg.mic_on,
               cfg.screen, cfg.camera, cfg.mic, cam_bad, mic_bad, app.can_record())
        if key != self.bg_key:
            self.bg = self.render_bg(cam_bad, mic_bad)
            self.bg_key = key
            if (self.photo.width(), self.photo.height()) != self.bg.size:
                self.photo = ImageTk.PhotoImage(self.bg)
                self.canvas.config(width=self.bg.size[0], height=self.bg.size[1])
                self.canvas.itemconfig(self.item, image=self.photo)
                self.place()
        img = self.bg.copy()
        dr = ImageDraw.Draw(img)
        P, dyn = self.px, self.dyn
        full = app.frame_full  # one read: another thread can replace it at any moment
        fresh = full is not None and now - app.frame_time < 2
        views = {"camera_view": Image.frombuffer("RGB", (app.pv, app.full_h), full) if fresh else None,
                 "screen_view": self.screen_thumb}
        for name, pic in views.items():
            if name in dyn and pic is not None:
                x0, y0, x1, y1 = dyn[name]
                size = (P(x1) - P(x0), P(y1) - P(y0))
                img.paste(ImageOps.fit(pic, size, Image.BILINEAR), (P(x0), P(y0)), self._card_mask(size))
        if "campic" in dyn and not fresh:
            cx, cy = dyn["campic"]
            if app.busy or now - app.preview_since < 5:
                dr.text((P(cx), P(cy + 18)), "Opening…", font=self.font(7.5), fill=t.muted, anchor="mm")
            else:
                dr.text((P(cx), P(cy + 18)), "No picture", font=self.font(7.5, True), fill=t.warn, anchor="mm")
        level = app.level if now - app.level_time < 1.5 else -120.0
        if "meter" in dyn:
            x0, y0, x1, y1 = dyn["meter"]
            frac = max(0.0, min(1.0, (level + 80) / 80))  # from -80 dB, so room noise shows the mic is live
            if frac > 0.02:
                dr.rounded_rectangle((P(x0), P(y0), P(x0 + (x1 - x0) * frac), P(y1)), radius=P(3),
                                     fill=t.warn if level > -6 else t.accent)
            if mic_bad:
                dr.text((P(dyn["nosignal"][0]), P(dyn["nosignal"][1])), "No signal",
                        font=self.font(7.5, True), fill=t.warn, anchor="mm")
        if "timer" in dyn:
            x, y, size, anchor = dyn["timer"]
            shown = app.elapsed + (now - app.seg_start if app.state == "recording" else 0)
            dr.text((P(x), P(y)), fmt_time(shown), font=self.font(size, True),
                    fill=t.warn if app.state == "paused" else t.text, anchor=anchor)
        if "dot" in dyn:
            x, y, r = dyn["dot"]
            color = t.warn if app.state == "paused" else (t.accent if int(now * 2) % 2 == 0 else t.blink)
            dr.ellipse((P(x - r), P(y - r), P(x + r), P(y + r)), fill=color)
        if "status" in dyn:
            text, color = (self.hint, t.text) if self.hint else app.status_text(now)
            dr.text((P(dyn["status"][0]), P(dyn["status"][1])), self.fit(text, self.font(8.5), P(540)),
                    font=self.font(8.5), fill=color, anchor="lm")
        self.photo.paste(img)

    def _card_mask(self, size):
        """A rounded-corner mask for a card picture, drawn at 4x for smooth corners."""
        if getattr(self, "_mask_size", None) != size:
            w, h = size
            big = Image.new("L", (w * 4, h * 4), 0)
            ImageDraw.Draw(big).rounded_rectangle((0, 0, w * 4 - 1, h * 4 - 1), radius=self.px(6) * 4, fill=255)
            self._mask, self._mask_size = big.resize(size, Image.LANCZOS), size
        return self._mask

    def _screen_thumbs(self):
        """A live thumbnail of the chosen screen for the screen card: 2 a second, 1 while recording.
        Windows hidden from capture (the bar, the bubble) are not in it."""
        sct = mss.mss()  # an mss instance belongs to the thread that made it
        while True:
            try:
                if self.app.cfg.screen_on:
                    self.screen_thumb = grab(sct, self.app.monitor()).reduce(6)
                else:
                    self.screen_thumb = None
            except Exception as e:  # a screen unplugged mid-grab: try again next time
                log.info(f"screen thumbnail: {e!r}")
                time.sleep(2)
            time.sleep(1.0 if self.app.state == "recording" else 0.5)

    # ---------- the window ----------
    def place(self, first: bool = False) -> None:
        w = self.bg.size[0]
        if first or not hasattr(self, "_center"):
            self._center = (self.root.winfo_screenwidth() // 2, self.px(12))
        x, y = self._center[0] - w // 2, self._center[1]
        self.root.geometry(f"{w}x{self.bg.size[1]}+{x}+{y}")

    def _hit(self, x, y):
        return next((n for n, x0, y0, x1, y1 in self.regions if x0 <= x <= x1 and y0 <= y <= y1), None)

    def _hint_for(self, name: str) -> str:
        app, cfg = self.app, self.app.cfg
        locked = "  (locked while recording)" if app.state != "idle" else ""
        hints = {"min": "Expand" if self.compact else "Minimize to a small timer",
                 "close": "Close (a recording in progress is saved first)",
                 "folder": f"Recordings are saved in {app.out_dir} · click to open or change",
                 "rec": f"Record ({cfg.hotkey_record_stop.title()})" if app.can_record()
                 else "Turn on the screen or the camera first",
                 "pause": f"{'Resume' if app.state == 'paused' else 'Pause'} ({cfg.hotkey_pause.title()})",
                 "stop": f"Stop and save ({cfg.hotkey_record_stop.title()})",
                 "restart": "Restart: delete this recording and start again",
                 "toggle_screen": "Record the screen: on / off" + locked,
                 "toggle_camera": "Record the camera: on / off" + locked,
                 "toggle_mic": "Record the mic: on / off" + locked,
                 "menu_screen": f"Screen: {app.monitor()['label']} · click to change" + locked,
                 "menu_camera": f"Camera: {cfg.camera or 'none found'} · click to change" + locked,
                 "menu_mic": f"Mic: {cfg.mic or 'none found'} · click to change" + locked}
        return hints.get(name, "")

    def _motion(self, e):
        name = self._hit(e.x, e.y)
        self.hint = self._hint_for(name) if name and name != "title" else ""
        self.canvas.config(cursor="hand2" if name and name != "title" else "fleur")

    def _press(self, e):
        self._dx, self._dy = e.x_root, e.y_root
        self._dragging = False
        name = self._hit(e.x, e.y)
        if not name or name == "title":
            self._dragging = True
            return
        app = self.app
        actions = {"min": self.toggle_compact, "close": app.on_close, "rec": app.on_record,
                   "pause": app.on_record, "stop": app.on_stop, "restart": app.on_restart}
        if name in actions:
            actions[name]()
        elif name == "folder":
            self.open_folder_menu()
        elif name.startswith("toggle_"):
            app.on_toggle(name[7:])
        elif name.startswith("menu_"):
            self.open_device_menu(name[5:])

    def _drag(self, e):
        if not getattr(self, "_dragging", False):
            return
        x = self.root.winfo_x() + e.x_root - self._dx
        y = self.root.winfo_y() + e.y_root - self._dy
        self._dx, self._dy = e.x_root, e.y_root
        self.root.geometry(f"+{x}+{y}")
        self._center = (x + self.bg.size[0] // 2, y)

    def toggle_compact(self):
        self.compact = not self.compact
        self.hint = ""

    def _menu(self):
        t = self.t
        return tk.Menu(self.root, tearoff=0, bg=t.card, fg=t.text, activebackground=t.accent,
                       activeforeground=t.text, selectcolor=t.accent, bd=0, font=("Segoe UI", 10))

    def _popup(self, menu, region):
        r = next(r for r in self.regions if r[0] == region)
        try:
            menu.tk_popup(self.root.winfo_rootx() + r[1], self.root.winfo_rooty() + r[4] + 2)
        finally:
            menu.grab_release()

    def open_device_menu(self, which: str):
        app, cfg = self.app, self.app.cfg
        if app.state != "idle" or app.busy:
            app.say("Devices are locked while recording", self.t.warn, 3)
            return
        m = self._menu()
        if which == "screen":
            var = tk.StringVar(value=cfg.screen)
            for mon in app.screens.monitors:
                m.add_radiobutton(label=mon["label"], value=mon["key"], variable=var,
                                  command=lambda k=mon["key"]: app.screen_changed(k))
            m.add_separator()
            m.add_command(label="Look for screens again", command=lambda: app.work(app.refresh_screens))
        else:
            names = app.cams if which == "camera" else app.mics
            var = tk.StringVar(value=getattr(cfg, which))
            for n in names:
                m.add_radiobutton(label=n, value=n, variable=var, command=lambda n=n: app.device_changed(which, n))
            if not names:
                m.add_command(label=f"No {which} found", state="disabled")
            m.add_separator()
            m.add_command(label="Look for devices again", command=lambda: app.work(app.refresh_devices))
        self._menu_var = var  # keep it alive while the menu is open
        self._popup(m, f"menu_{which}")

    def open_folder_menu(self):
        app = self.app
        m = self._menu()
        m.add_command(label="Open the recordings folder", command=app.open_folder)
        m.add_command(label="Change where recordings are saved…", command=app.change_folder,
                      state="normal" if app.state == "idle" and not app.busy else "disabled")
        self._popup(m, "folder")


def fmt_time(secs: float) -> str:
    secs = int(secs)
    return f"{secs // 3600}:{secs % 3600 // 60:02d}:{secs % 60:02d}" if secs >= 3600 else f"{secs // 60:02d}:{secs % 60:02d}"
