"""Where a layer goes by default, for each canvas shape.

16:9  the screen fills the frame; the face is a circle bottom-left, 300 px at 1080p, 25 px in
9:16  the screen fits across the top; the face is a bigger circle bottom-left (40 % of the width)
1:1, 4:5  the screen fits; the face is a circle bottom-left"""
from __future__ import annotations

from .model import Media, Sequence, Transform

FACE_FRACTION_LANDSCAPE = 300 / 1080   # of the canvas height
FACE_FRACTION_PORTRAIT = 0.40          # of the canvas width
MARGIN_FRACTION = 25 / 1080            # of the shorter side
PORTRAIT_SCREEN_TOP = 0.14             # below the part a phone app covers


def _portrait(seq: Sequence) -> bool:
    w, h = seq.size
    return h > w


def face(seq: Sequence) -> Transform:
    w, h = seq.size
    side = FACE_FRACTION_PORTRAIT * w if _portrait(seq) else FACE_FRACTION_LANDSCAPE * min(w, h)
    margin = MARGIN_FRACTION * min(w, h)
    return Transform(x=margin / w, y=(h - side - margin) / h, w=side / w, h=side / h,
                     fit="cover", mask="circle")


def screen(seq: Sequence, media: Media | None = None) -> Transform:
    w, h = seq.size
    if not _portrait(seq):
        return Transform(fit="contain")
    aspect = media.aspect if media else 16 / 9
    box_h = w / aspect
    return Transform(x=0.0, y=PORTRAIT_SCREEN_TOP, w=1.0, h=box_h / h, fit="contain")


def full(seq: Sequence) -> Transform:
    return Transform(fit="contain")


def for_media(seq: Sequence, media: Media, role: str = "") -> Transform:
    """The default box for a clip of this media on a lane with this role."""
    if role == "face" or media.role == "camera":
        return face(seq)
    if role == "screen" or media.role == "screen":
        return screen(seq, media)
    return full(seq)


def blur_box() -> Transform:
    """A blur clip starts as a box in the middle of the frame for the user to drag."""
    return Transform(x=0.35, y=0.35, w=0.3, h=0.3, fit="cover")


def refit(t: Transform, old: Sequence, new: Sequence) -> Transform:
    """Keep a box's shape and centre when the canvas changes shape, scaled to still fit."""
    ow, oh = old.size
    nw, nh = new.size
    if (ow, oh) == (nw, nh):
        return t
    bw, bh = t.w * ow, t.h * oh
    cx, cy = t.x + t.w / 2, t.y + t.h / 2
    scale = min(nw / ow, nh / oh)
    if t.w >= 0.999 and t.h >= 0.999:  # a full-frame layer stays full frame
        return Transform(**{**t.__dict__})
    w, h = bw * scale / nw, bh * scale / nh
    x = min(max(cx - w / 2, 0.0), 1.0 - w)
    y = min(max(cy - h / 2, 0.0), 1.0 - h)
    return Transform(**{**t.__dict__, "x": x, "y": y, "w": w, "h": h})
