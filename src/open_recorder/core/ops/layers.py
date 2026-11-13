"""Ops on how a clip looks and sounds: its box on the canvas, mask, opacity, volume, blur
strength, links, and the canvas shape itself."""
from __future__ import annotations

from .. import layout
from ..model import ASPECTS, FITS, MASKS, Project, Sequence, new_id
from .registry import OpError, op
from .util import get, ids


def _clamp(v, lo, hi):
    return min(max(float(v), lo), hi)


@op("set_transform")
def set_transform(p: Project, clips, x: float | None = None, y: float | None = None, w: float | None = None,
                  h: float | None = None, fit: str | None = None, opacity: float | None = None):
    """Place a clip's box: x, y, w, h are fractions of the canvas (0 to 1, the box may hang off)."""
    for cid in ids(clips):
        _, clip = get(p, cid)
        t = clip.transform
        for key, value in (("x", x), ("y", y)):
            if value is not None:
                setattr(t, key, _clamp(value, -1.0, 2.0))
        for key, value in (("w", w), ("h", h)):
            if value is not None:
                setattr(t, key, _clamp(value, 0.02, 3.0))
        if fit is not None:
            if fit not in FITS:
                raise OpError(f"fit must be one of {', '.join(FITS)}")
            t.fit = fit
        if opacity is not None:
            t.opacity = _clamp(opacity, 0.0, 1.0)
    return None


@op("set_mask")
def set_mask(p: Project, clips, mask: str, radius: float | None = None):
    """circle or square makes the box square (same centre, same height on screen)."""
    if mask not in MASKS:
        raise OpError(f"mask must be one of {', '.join(MASKS)}")
    cw, ch = p.sequence.size
    for cid in ids(clips):
        _, clip = get(p, cid)
        t = clip.transform
        t.mask = mask
        if radius is not None:
            t.radius = _clamp(radius, 0.0, 0.5)
        if mask != "none":
            side = min(t.w * cw, t.h * ch)
            cx, cy = t.x + t.w / 2, t.y + t.h / 2
            t.w, t.h = side / cw, side / ch
            t.x, t.y = cx - t.w / 2, cy - t.h / 2
            t.fit = "cover"
    return f"mask {mask} on {len(ids(clips))} clip(s)"


@op("reset_layout")
def reset_layout(p: Project, clips=None):
    """Put clips back in their default place for this canvas shape (all face and screen clips
    when none are named)."""
    targets = [get(p, cid) for cid in ids(clips)] if clips else \
        [(lane, c) for lane, c in p.clips() if lane.role in ("face", "screen")]
    for lane, clip in targets:
        m = p.media.get(clip.media)
        if lane.kind == "blur" or m is None:
            continue
        clip.transform = layout.for_media(p.sequence, m, lane.role)
    return f"reset the layout of {len(targets)} clip(s)"


@op("set_volume")
def set_volume(p: Project, clips, volume: float):
    for cid in ids(clips):
        _, clip = get(p, cid)
        clip.volume = _clamp(volume, 0.0, 2.0)
    return None


@op("set_blur")
def set_blur(p: Project, clips, strength: float):
    for cid in ids(clips):
        lane, clip = get(p, cid)
        if lane.kind != "blur":
            raise OpError(f"{cid} is not a blur")
        clip.strength = _clamp(strength, 1.0, 100.0)
    return None


@op("link")
def link(p: Project, clips):
    targets = [get(p, cid)[1] for cid in ids(clips)]
    if len(targets) < 2:
        raise OpError("link needs two clips or more")
    shared = new_id("link")
    for clip in targets:
        for other in p.linked(clip):
            other.link = shared
    return f"linked {len(targets)} clips"


@op("unlink")
def unlink(p: Project, clips):
    for cid in ids(clips):
        for clip in p.linked(get(p, cid)[1]):
            clip.link = ""
    return None


@op("set_sequence")
def set_sequence(p: Project, aspect: str | None = None, fps: int | None = None, relayout: bool = False):
    """Change the canvas shape. Boxes keep their shape and centre; relayout puts the face and
    screen back in this shape's default place."""
    old = Sequence(p.sequence.aspect, p.sequence.fps)
    if aspect is not None:
        if aspect not in ASPECTS:
            raise OpError(f"aspect must be one of {', '.join(ASPECTS)}")
        p.sequence.aspect = aspect
    if fps is not None:
        p.sequence.fps = int(_clamp(fps, 10, 60))
    for _, clip in p.clips():
        clip.transform = layout.refit(clip.transform, old, p.sequence)
    if relayout:
        reset_layout(p)
    return f"canvas {p.sequence.aspect}"
