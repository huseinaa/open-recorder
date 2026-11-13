"""Building blocks the ops share: finding clips, splitting one, clearing a stretch of a lane."""
from __future__ import annotations

import copy

from ..model import Clip, Lane, Project, new_id
from ..timeline import EPS, overlapping
from .registry import OpError

MIN_CLIP = 0.05  # seconds; anything shorter is dropped rather than kept as a sliver


def r(x: float) -> float:
    """Round times so a hundred edits never drift by float error."""
    return round(float(x), 6)


def ids(value) -> list[str]:
    if value is None:
        return []
    return [value] if isinstance(value, str) else [str(v) for v in value]


def get(p: Project, clip_id: str) -> tuple[Lane, Clip]:
    lane, clip = p.find(clip_id)
    if clip is None:
        raise OpError(f"no clip '{clip_id}'")
    return lane, clip


def get_lane(p: Project, lane_id: str) -> Lane:
    lane = p.lane(lane_id)
    if lane is None:
        raise OpError(f"no lane '{lane_id}'")
    return lane


def group(p: Project, clip_ids, link: bool = True) -> list[tuple[Lane, Clip]]:
    """The named clips, plus the clips linked to them when link is on, each once."""
    seen: dict[str, tuple[Lane, Clip]] = {}
    for cid in ids(clip_ids):
        lane, clip = get(p, cid)
        for other in (p.linked(clip) if link else [clip]):
            if other.id not in seen:
                seen[other.id] = (p.find(other.id)[0], other)
    return list(seen.values())


def unlocked(p: Project, lane_ids=None) -> list[Lane]:
    if lane_ids:
        lanes = [get_lane(p, lid) for lid in ids(lane_ids)]
    else:
        lanes = list(p.lanes)
    return [lane for lane in lanes if not lane.locked]


def media_limit(p: Project, clip: Clip) -> float | None:
    """How far into its file a clip can reach (None: no end, an image or a blur)."""
    m = p.media.get(clip.media)
    if m is None or m.kind == "image":
        return None
    return m.duration or None


def split_clip(lane: Lane, clip: Clip, t: float, links: dict[str, str]) -> Clip | None:
    """Cut a clip in two at timeline time t. The right half gets a new id, and a new link id
    shared with the right halves of its linked clips (links remembers which)."""
    if not (clip.start + EPS < t < clip.end - EPS):
        return None
    right = copy.deepcopy(clip)
    right.id = new_id("clip")
    offset = t - clip.start
    right.start = r(t)
    right.src_in = r(clip.src_in + offset)
    clip.src_out = r(clip.src_in + offset)
    if clip.link:
        right.link = links.setdefault(clip.link, new_id("link"))
    lane.clips.append(right)
    return right


def clear_range(lane: Lane, start: float, end: float, links: dict[str, str],
                ignore: set[str] = frozenset()) -> None:
    """Remove whatever is on this lane between start and end, without moving anything else."""
    for clip in list(overlapping(lane, start, end, ignore)):
        if clip.start + EPS < start and clip.end - EPS > end:
            right = split_clip(lane, clip, end, links)
            clip.src_out = r(clip.src_in + (start - clip.start))
            if right and right.duration < MIN_CLIP:
                lane.clips.remove(right)
        elif clip.start + EPS < start:
            clip.src_out = r(clip.src_in + (start - clip.start))
        elif clip.end - EPS > end:
            cut = end - clip.start
            clip.src_in = r(clip.src_in + cut)
            clip.start = r(end)
        else:
            lane.clips.remove(clip)
            continue
        if clip.duration < MIN_CLIP:
            lane.clips.remove(clip)


def shift_after(lanes: list[Lane], t: float, delta: float) -> None:
    """Move every clip starting at or after t by delta (negative closes a gap)."""
    for lane in lanes:
        for clip in lane.clips:
            if clip.start >= t - EPS:
                clip.start = r(max(0.0, clip.start + delta))


def insert(lane: Lane, clip: Clip, links: dict[str, str] | None = None) -> None:
    """Put a clip on a lane, overwriting what was under it (as an editor's overwrite edit does)."""
    clear_range(lane, clip.start, clip.end, links if links is not None else {}, ignore={clip.id})
    lane.clips.append(clip)
    lane.clips.sort(key=lambda c: c.start)
