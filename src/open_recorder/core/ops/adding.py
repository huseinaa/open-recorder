"""Ops that put things on the timeline: a file, a whole recording (screen + face), a blur, and
pulling a clip's sound onto its own lane."""
from __future__ import annotations

import copy

from .. import layout
from ..model import IMAGE_SECONDS, Clip, Project, new_id
from ..timeline import is_free, lane_end
from .lanes import make_lane
from .registry import OpError, op
from .util import get, get_lane, insert, r


def _media(p: Project, key: str):
    m = p.media.get(key)
    if m is None:
        raise OpError(f"no media '{key}' in this project")
    return m


def _free_lane(p: Project, kind: str, start: float, end: float):
    """The first lane of this kind (not a face or screen lane) with room, or a new one."""
    for lane in p.lanes:
        if lane.kind == kind and not lane.role and not lane.locked and is_free(lane, start, end):
            return lane
    return make_lane(p, kind)


@op("add_clip")
def add_clip(p: Project, media: str, lane: str | None = None, start: float | None = None,
             src_in: float = 0.0, src_out: float | None = None):
    """Put a file on the timeline. Without a lane: a free lane of the right kind, or a new one.
    Without a start: at the end of that lane."""
    m = _media(p, media)
    src_in = max(0.0, float(src_in))
    if src_out is None:
        src_out = src_in + (IMAGE_SECONDS if m.kind == "image" else max(0.0, m.duration - src_in))
    src_out = float(src_out) if m.kind == "image" else min(float(src_out), m.duration or float(src_out))
    if src_out - src_in < 0.05:
        raise OpError("the clip would be empty")
    kind = "audio" if m.kind == "audio" else "video"
    if lane:
        target = get_lane(p, lane)
        if target.kind == "blur":
            raise OpError("files cannot go on a blur lane")
        if target.kind == "audio" and not m.has_audio:
            raise OpError("this file has no sound for an audio lane")
        if target.kind == "video" and m.kind == "audio":
            raise OpError("a sound file goes on an audio lane")
        kind = target.kind
    at = float(start) if start is not None else None
    if not lane:
        target = _free_lane(p, kind, at or 0.0, (at or 0.0) + (src_out - src_in)) if at is not None \
            else next((ln for ln in p.lanes if ln.kind == kind and not ln.role), None) or make_lane(p, kind)
    if at is None:
        at = lane_end(target)
    clip = Clip(id=new_id("clip"), media=m.key, start=r(max(0.0, at)), src_in=r(src_in), src_out=r(src_out),
                video=kind == "video" and m.has_video, audio=m.has_audio,
                transform=layout.for_media(p.sequence, m, target.role))
    if target.locked:
        raise OpError(f"lane '{target.name}' is locked")
    insert(target, clip)
    return f"added {m.key} on {target.name} at {clip.start:.2f}s ({clip.id})"


def _role_lane(p: Project, role: str):
    lane = p.lane_by_role(role)
    if lane:
        return lane
    index = None
    if role == "screen":
        face = p.lane_by_role("face")
        index = p.lanes.index(face) + 1 if face else None
    return make_lane(p, "video", role=role, index=index)


@op("add_recording")
def add_recording(p: Project, recording: str, start: float | None = None):
    """Put a recording on the timeline: the face (with the voice) on the FACE + VOICE lane, the
    screen on the SCREEN lane, lined up with the recording's screen_offset and linked."""
    parts = {m.role: m for m in p.media.values() if m.recording == recording}
    if not parts:
        raise OpError(f"no recording '{recording}'")
    cam, scr = parts.get("camera"), parts.get("screen")
    face_lane = _role_lane(p, "face") if cam else None
    screen_lane = _role_lane(p, "screen") if scr else None
    if start is None:
        start = max(lane_end(face_lane) if face_lane else 0.0, lane_end(screen_lane) if screen_lane else 0.0)
    t0 = max(0.0, float(start))
    link = new_id("link") if cam and scr else ""
    made = []
    if cam:
        made.append((face_lane, Clip(id=new_id("clip"), media=cam.key, start=r(t0), src_in=0.0,
                                     src_out=r(cam.duration), audio=cam.has_audio, link=link,
                                     transform=layout.face(p.sequence))))
    if scr:
        offset = scr.offset if cam else 0.0  # screen time = camera time + offset
        start_at, src_in = (t0, offset) if offset >= 0 else (t0 - offset, 0.0)
        made.append((screen_lane, Clip(id=new_id("clip"), media=scr.key, start=r(start_at), src_in=r(src_in),
                                       src_out=r(scr.duration), audio=scr.has_audio and not cam, link=link,
                                       transform=layout.screen(p.sequence, scr))))
    for lane, clip in made:
        if clip.duration >= 0.05:
            insert(lane, clip)
    return f"added recording {recording} at {t0:.2f}s"


@op("add_blur")
def add_blur(p: Project, start: float, end: float, x: float | None = None, y: float | None = None,
             w: float | None = None, h: float | None = None, strength: float = 20.0, lane: str | None = None):
    """Blur a box of the frame between start and end (the box is a fraction of the canvas)."""
    start, end = max(0.0, float(start)), float(end)
    if end - start < 0.05:
        raise OpError("add_blur needs end after start")
    box = layout.blur_box()
    for key, value in (("x", x), ("y", y), ("w", w), ("h", h)):
        if value is not None:
            setattr(box, key, min(max(float(value), 0.0), 1.0))
    target = get_lane(p, lane) if lane else _free_lane(p, "blur", start, end)
    if target.kind != "blur":
        raise OpError("a blur goes on a blur lane")
    clip = Clip(id=new_id("clip"), media="", start=r(start), src_in=0.0, src_out=r(end - start),
                video=True, audio=False, transform=box, strength=max(1.0, min(float(strength), 100.0)))
    insert(target, clip)
    return f"added a blur from {start:.2f}s to {end:.2f}s ({clip.id})"


@op("detach_audio")
def detach_audio(p: Project, clip: str):
    """Move a clip's sound to an audio lane as its own linked clip; the video clip goes silent."""
    lane, main = get(p, clip)
    if lane.kind != "video" or not main.audio:
        raise OpError("this clip has no sound to detach")
    sound = copy.deepcopy(main)
    sound.id, sound.video, sound.audio = new_id("clip"), False, True
    main.audio = False
    if not main.link:
        main.link = new_id("link")
    sound.link = main.link
    target = _free_lane(p, "audio", sound.start, sound.end)
    insert(target, sound)
    return f"moved the sound of {main.id} to {target.name}"
