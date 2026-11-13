"""The round face bubble: a borderless window bottom-left of the screen being recorded, hidden
from capture. Drag it anywhere. An editor can put the camera file back in the same place."""
from __future__ import annotations

import tkinter as tk

from PIL import Image, ImageDraw, ImageTk

from ...win32 import hide_from_capture
from .theme import KEY, KEY_RGB


class Bubble:
    def __init__(self, root: tk.Tk, size: int, margin: int, theme, visible: bool = False):
        self.size, self.margin, self.theme = size, margin, theme
        w = self.window = tk.Toplevel(root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.configure(bg=KEY)
        w.attributes("-transparentcolor", KEY)
        self.canvas = tk.Canvas(w, width=size, height=size, bg=KEY, highlightthickness=0, cursor="fleur")
        self.canvas.pack()
        self.mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(self.mask).ellipse((0, 0, size - 1, size - 1), fill=255)
        self.photo = ImageTk.PhotoImage(Image.new("RGB", (size, size), KEY_RGB))
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.text = self.canvas.create_text(size // 2, size // 2, text="Opening camera…",
                                            fill=theme.text, font=("Segoe UI", 12))
        self.placeholder()
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        if not visible:
            hide_from_capture(w)

    def place(self, monitor: dict) -> None:
        """Bottom-left of the screen being recorded."""
        s, gap = self.size, self.margin
        self.window.geometry(f"{s}x{s}+{monitor['x'] + gap}+{monitor['y'] + monitor['h'] - s - gap}")

    def show(self, on: bool) -> None:
        self.window.deiconify() if on else self.window.withdraw()

    def placeholder(self) -> None:
        img = Image.new("RGB", (self.size, self.size), KEY_RGB)
        img.paste(Image.new("RGB", (self.size, self.size), (28, 31, 38)), (0, 0), self.mask)
        self.photo.paste(img)

    def paint(self, face: bytes, ring: str) -> None:
        s = self.size
        img = Image.new("RGB", (s, s), KEY_RGB)
        img.paste(Image.frombuffer("RGB", (s, s), face), (0, 0), self.mask)
        ImageDraw.Draw(img).ellipse((2, 2, s - 3, s - 3), outline=ring, width=4)
        self.photo.paste(img)
        self.canvas.itemconfig(self.text, text="")

    def say(self, text: str) -> None:
        self.canvas.itemconfig(self.text, text=text)

    def _press(self, e):
        self._x, self._y = e.x_root, e.y_root

    def _drag(self, e):
        w = self.window
        w.geometry(f"+{w.winfo_x() + e.x_root - self._x}+{w.winfo_y() + e.y_root - self._y}")
        self._x, self._y = e.x_root, e.y_root
