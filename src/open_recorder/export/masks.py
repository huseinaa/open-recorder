"""Circle and rounded-square masks as greyscale PNGs, drawn 4x larger and scaled down so the
edge is smooth. ffmpeg's alphamerge uses them to cut a layer to shape."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

SUPERSAMPLE = 4


@dataclass(frozen=True)
class MaskSpec:
    shape: str      # circle or square
    width: int
    height: int
    radius: float   # square only: corner radius as a fraction of the shorter side

    @property
    def name(self) -> str:
        return f"{self.shape}-{self.width}x{self.height}-{self.radius:.3f}.png"


def draw(spec: MaskSpec) -> Image.Image:
    w, h = spec.width * SUPERSAMPLE, spec.height * SUPERSAMPLE
    img = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(img)
    if spec.shape == "circle":
        side = min(w, h)
        x0, y0 = (w - side) // 2, (h - side) // 2
        d.ellipse([x0, y0, x0 + side - 1, y0 + side - 1], fill=255)
    else:
        radius = int(spec.radius * min(w, h))
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    return img.resize((spec.width, spec.height), Image.LANCZOS)


def make(spec: MaskSpec, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / spec.name
    if not path.exists():
        draw(spec).save(path)
    return path
