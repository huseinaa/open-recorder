"""Draws src/open_recorder/assets/icon.ico: the bar's mark (accent square, white record dot).
Run it again after changing the colours: python tools/make_icon.py"""
from pathlib import Path

from PIL import Image, ImageDraw

ACCENT, WHITE = "#2F6BFF", "#F2F4F8"
OUT = Path(__file__).resolve().parents[1] / "src" / "open_recorder" / "assets" / "icon.ico"


def draw(size: int) -> Image.Image:
    k = 4
    s = size * k
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=s * 0.24, fill=ACCENT)
    r = s * 0.22
    d.ellipse((s / 2 - r, s / 2 - r, s / 2 + r, s / 2 + r), fill=WHITE)
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    draw(256).save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"wrote {OUT}")
