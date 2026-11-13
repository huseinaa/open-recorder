"""The project model: plain data, no files, no ffmpeg, no UI.

Times are seconds. A clip's box (x, y, w, h) is a fraction of the canvas, so a layout survives a
change of export size. Lanes are listed top first: the top lane is drawn over the ones below it."""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field, fields

ASPECTS: dict[str, tuple[int, int]] = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
}
LANE_KINDS = ("video", "audio", "blur")
MASKS = ("none", "circle", "square")
FITS = ("contain", "cover")
MEDIA_KINDS = ("video", "image", "audio")
IMAGE_SECONDS = 5.0  # how long an image clip is when it is first dropped in


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _pick(cls, data: dict) -> dict:
    """Only the keys the dataclass knows, so an older or newer project file still loads."""
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in (data or {}).items() if k in names}


@dataclass
class Transform:
    x: float = 0.0
    y: float = 0.0
    w: float = 1.0
    h: float = 1.0
    fit: str = "contain"      # contain: the whole picture inside the box; cover: the box filled, edges cropped
    mask: str = "none"        # none, circle, square
    radius: float = 0.18      # square mask corner, as a fraction of the box's shorter side
    opacity: float = 1.0

    @classmethod
    def from_dict(cls, data: dict | None) -> "Transform":
        return cls(**_pick(cls, data or {}))


@dataclass
class Clip:
    id: str
    media: str                # key into Project.media; empty for a blur clip
    start: float              # where it sits on the timeline
    src_in: float             # the part of the file it plays
    src_out: float
    video: bool = True
    audio: bool = True
    volume: float = 1.0
    transform: Transform = field(default_factory=Transform)
    link: str = ""            # clips sharing a link id are cut, moved and deleted together
    strength: float = 20.0    # blur clips only

    @property
    def duration(self) -> float:
        return max(0.0, self.src_out - self.src_in)

    @property
    def end(self) -> float:
        return self.start + self.duration

    @classmethod
    def from_dict(cls, data: dict) -> "Clip":
        values = _pick(cls, data)
        values["transform"] = Transform.from_dict(data.get("transform"))
        return cls(**values)


@dataclass
class Lane:
    id: str
    name: str
    kind: str = "video"       # video, audio or blur
    clips: list[Clip] = field(default_factory=list)
    hidden: bool = False
    muted: bool = False
    locked: bool = False
    role: str = ""            # face or screen for the two lanes a recording lands on

    @classmethod
    def from_dict(cls, data: dict) -> "Lane":
        values = _pick(cls, data)
        values["clips"] = [Clip.from_dict(c) for c in data.get("clips", [])]
        return cls(**values)


@dataclass
class Media:
    key: str                  # the path relative to the project folder, or absolute when outside it
    path: str                 # absolute path on disk
    kind: str = "video"       # video, image or audio
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_video: bool = True
    has_audio: bool = False
    recording: str = ""       # the recording id when this file is half of a screen + camera pair
    role: str = ""            # screen or camera for those halves
    offset: float = 0.0       # screen_offset of the pair (screen time = camera time + offset)

    @property
    def aspect(self) -> float:
        return self.width / self.height if self.width and self.height else 16 / 9

    @classmethod
    def from_dict(cls, data: dict) -> "Media":
        return cls(**_pick(cls, data))


@dataclass
class Sequence:
    aspect: str = "16:9"
    fps: int = 30

    @property
    def size(self) -> tuple[int, int]:
        return ASPECTS.get(self.aspect, ASPECTS["16:9"])

    @classmethod
    def from_dict(cls, data: dict | None) -> "Sequence":
        return cls(**_pick(cls, data or {}))


@dataclass
class Project:
    name: str = "Untitled"
    sequence: Sequence = field(default_factory=Sequence)
    lanes: list[Lane] = field(default_factory=list)
    media: dict[str, Media] = field(default_factory=dict)
    version: int = 1

    # ---------- lookups ----------
    @property
    def duration(self) -> float:
        return max((c.end for lane in self.lanes for c in lane.clips), default=0.0)

    def lane(self, lane_id: str) -> Lane | None:
        return next((lane for lane in self.lanes if lane.id == lane_id), None)

    def lane_by_role(self, role: str) -> Lane | None:
        return next((lane for lane in self.lanes if lane.role == role), None)

    def find(self, clip_id: str) -> tuple[Lane, Clip] | tuple[None, None]:
        for lane in self.lanes:
            for clip in lane.clips:
                if clip.id == clip_id:
                    return lane, clip
        return None, None

    def clips(self):
        for lane in self.lanes:
            for clip in lane.clips:
                yield lane, clip

    def linked(self, clip: Clip) -> list[Clip]:
        """The clip plus every clip sharing its link id."""
        if not clip.link:
            return [clip]
        return [c for _, c in self.clips() if c.link == clip.link]

    # ---------- JSON ----------
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Project":
        return cls(
            name=data.get("name", "Untitled"),
            sequence=Sequence.from_dict(data.get("sequence")),
            lanes=[Lane.from_dict(lane) for lane in data.get("lanes", [])],
            media={k: Media.from_dict(m) for k, m in (data.get("media") or {}).items()},
            version=data.get("version", 1),
        )
