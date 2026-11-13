"""Lane ops: add, remove, reorder, rename, hide, mute, lock."""
from __future__ import annotations

from ..model import LANE_KINDS, Lane, Project, new_id
from .registry import OpError, op
from .util import get_lane

DEFAULT_NAMES = {"video": "VIDEO", "audio": "AUDIO", "blur": "BLUR"}
ROLE_NAMES = {"face": "FACE + VOICE", "screen": "SCREEN"}


def default_index(p: Project, kind: str) -> int:
    """Blur on top, audio at the bottom, a new video lane above the other video lanes."""
    if kind == "blur":
        return 0
    if kind == "audio":
        return len(p.lanes)
    return next((i for i, lane in enumerate(p.lanes) if lane.kind == "video"), len(p.lanes))


def make_lane(p: Project, kind: str, name: str | None = None, index: int | None = None, role: str = "") -> Lane:
    if kind not in LANE_KINDS:
        raise OpError(f"lane kind must be one of {', '.join(LANE_KINDS)}")
    if not name:
        if role:
            name = ROLE_NAMES.get(role, role.upper())
        else:
            count = sum(1 for lane in p.lanes if lane.kind == kind and not lane.role) + 1
            name = f"{DEFAULT_NAMES[kind]} {count}"
    lane = Lane(id=new_id("lane"), name=name, kind=kind, role=role)
    at = default_index(p, kind) if index is None else max(0, min(int(index), len(p.lanes)))
    p.lanes.insert(at, lane)
    return lane


@op("add_lane")
def add_lane(p: Project, kind: str = "video", name: str | None = None, index: int | None = None):
    lane = make_lane(p, kind, name, index)
    return f"added lane {lane.name} ({lane.id})"


@op("remove_lane")
def remove_lane(p: Project, lane: str):
    target = get_lane(p, lane)
    if target.locked:
        raise OpError(f"lane '{target.name}' is locked")
    p.lanes.remove(target)
    return f"removed lane {target.name}"


@op("reorder_lane")
def reorder_lane(p: Project, lane: str, index: int):
    target = get_lane(p, lane)
    p.lanes.remove(target)
    p.lanes.insert(max(0, min(int(index), len(p.lanes))), target)
    return None


@op("set_lane")
def set_lane(p: Project, lane: str, name: str | None = None, hidden: bool | None = None,
             muted: bool | None = None, locked: bool | None = None):
    target = get_lane(p, lane)
    if name is not None:
        target.name = str(name)[:40] or target.name
    for key, value in (("hidden", hidden), ("muted", muted), ("locked", locked)):
        if value is not None:
            setattr(target, key, bool(value))
    return None
