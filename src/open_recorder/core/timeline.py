"""Read-only questions about a timeline: what plays at a time, where a lane is free, and how a
moment on the timeline maps to a moment in a file."""
from __future__ import annotations

from .model import Clip, Lane, Project

EPS = 1e-6


def sorted_clips(lane: Lane) -> list[Clip]:
    return sorted(lane.clips, key=lambda c: c.start)


def lane_end(lane: Lane) -> float:
    return max((c.end for c in lane.clips), default=0.0)


def clips_at(project: Project, t: float) -> list[tuple[Lane, Clip]]:
    """Every clip playing at time t, top lane first."""
    return [(lane, c) for lane in project.lanes for c in lane.clips if c.start - EPS <= t < c.end - EPS]


def overlapping(lane: Lane, start: float, end: float, ignore: set[str] = frozenset()) -> list[Clip]:
    return [c for c in lane.clips if c.id not in ignore and c.start < end - EPS and c.end > start + EPS]


def is_free(lane: Lane, start: float, end: float, ignore: set[str] = frozenset()) -> bool:
    return not overlapping(lane, start, end, ignore)


def to_source(clip: Clip, t: float) -> float:
    """Timeline time → time inside the clip's file."""
    return clip.src_in + (t - clip.start)


def to_timeline(clip: Clip, src_t: float) -> float | None:
    """Time inside the clip's file → timeline time, or None when that moment was cut out."""
    if clip.src_in - EPS <= src_t <= clip.src_out + EPS:
        return clip.start + (src_t - clip.src_in)
    return None


def neighbours(lane: Lane, clip: Clip) -> tuple[Clip | None, Clip | None]:
    """The clips right before and right after this one on its lane."""
    others = [c for c in sorted_clips(lane) if c.id != clip.id]
    before = [c for c in others if c.end <= clip.start + EPS]
    after = [c for c in others if c.start >= clip.end - EPS]
    return (before[-1] if before else None), (after[0] if after else None)
