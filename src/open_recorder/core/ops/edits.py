"""Cutting ops: split, delete, ripple delete, cut a range, trim and move."""
from __future__ import annotations

from ..model import Project
from ..timeline import EPS, is_free
from .registry import OpError, op
from .util import (MIN_CLIP, clear_range, get, get_lane, group, insert, media_limit, r, shift_after,
                   split_clip, unlocked)


@op("split")
def split(p: Project, t: float, clips=None, link: bool = True):
    """Cut at time t: the named clips (and their linked clips), or everything under t."""
    t = float(t)
    if clips:
        targets = [(lane, c) for lane, c in group(p, clips, link) if not lane.locked]
    else:
        targets = [(lane, c) for lane in unlocked(p) for c in list(lane.clips)]
    links: dict[str, str] = {}
    made = sum(1 for lane, c in targets if split_clip(lane, c, t, links))
    return f"split {made} clip(s) at {t:.2f}s" if made else None


@op("delete")
def delete(p: Project, clips, link: bool = True):
    targets = group(p, clips, link)
    for lane, clip in targets:
        if lane.locked:
            raise OpError(f"lane '{lane.name}' is locked")
        lane.clips.remove(clip)
    return f"deleted {len(targets)} clip(s)"


@op("ripple_delete")
def ripple_delete(p: Project, clips, link: bool = True):
    """Delete and close the gap, but only when closing it cannot pull other lanes out of sync."""
    targets = group(p, clips, link)
    start = min(c.start for _, c in targets)
    end = max(c.end for _, c in targets)
    delete(p, [c.id for _, c in targets], link=False)
    lanes = unlocked(p)
    if all(is_free(lane, start, end) for lane in lanes):
        shift_after(lanes, end, -(end - start))
        return f"deleted {len(targets)} clip(s) and closed the {end - start:.2f}s gap"
    return f"deleted {len(targets)} clip(s); the gap stays because other lanes have clips there"


@op("cut_range")
def cut_range(p: Project, start: float, end: float, lanes=None, ripple: bool = True):
    """Remove a stretch of time. With ripple, everything after it moves left to close it."""
    start, end = float(start), float(end)
    if end - start < 0.01:
        raise OpError("cut_range needs end after start")
    targets = unlocked(p, lanes)
    links: dict[str, str] = {}
    for lane in targets:
        clear_range(lane, start, end, links)
    if ripple:
        shift_after(targets, end, -(end - start))
    return f"cut {start:.2f}s to {end:.2f}s ({end - start:.2f}s)"


def _edge_room(p: Project, clip, lane, edge: str) -> tuple[float, float]:
    """How far an edge can move (negative = left, positive = right) for one clip."""
    others = [c for c in lane.clips if c.id != clip.id]
    limit = media_limit(p, clip)
    if edge == "start":
        prev_end = max((c.end for c in others if c.end <= clip.start + EPS), default=0.0)
        lo = max(prev_end - clip.start, -clip.start, -clip.src_in if limit is not None else -float("inf"))
        hi = clip.duration - MIN_CLIP
    else:
        next_start = min((c.start for c in others if c.start >= clip.end - EPS), default=float("inf"))
        lo = MIN_CLIP - clip.duration
        hi = next_start - clip.end
        if limit is not None:
            hi = min(hi, limit - clip.src_out)
    return lo, hi


@op("trim")
def trim(p: Project, clip: str, start: float | None = None, end: float | None = None, link: bool = True):
    """Move a clip's left edge to timeline time start, or its right edge to end."""
    lane, main = get(p, clip)
    targets = group(p, clip, link)
    for edge, value in (("start", start), ("end", end)):
        if value is None:
            continue
        want = float(value) - (main.start if edge == "start" else main.end)
        lo, hi = -float("inf"), float("inf")
        for ln, c in targets:
            a, b = _edge_room(p, c, ln, edge)
            lo, hi = max(lo, a), min(hi, b)
        delta = min(max(want, lo), hi)
        for _, c in targets:
            if edge == "start":
                c.start, c.src_in = r(c.start + delta), r(c.src_in + delta)
            else:
                c.src_out = r(c.src_out + delta)
    return f"trimmed {len(targets)} clip(s)"


@op("move")
def move(p: Project, clip: str, start: float, lane: str | None = None, link: bool = True):
    """Move a clip (and its linked clips by the same amount) to a new start, optionally to
    another lane. Whatever is already there is overwritten."""
    src_lane, main = get(p, clip)
    targets = group(p, clip, link)
    delta = float(start) - main.start
    delta = max(delta, -min(c.start for _, c in targets))
    dest = get_lane(p, lane) if lane else src_lane
    if dest.locked or any(ln.locked for ln, _ in targets):
        raise OpError("a locked lane cannot change")
    if dest.kind != src_lane.kind:
        raise OpError(f"a {src_lane.kind} clip cannot go on a {dest.kind} lane")
    links: dict[str, str] = {}
    for ln, c in targets:
        ln.clips.remove(c)
        c.start = r(c.start + delta)
    for ln, c in targets:
        insert(dest if c.id == main.id else ln, c, links)
    return f"moved {len(targets)} clip(s) by {delta:+.2f}s"
