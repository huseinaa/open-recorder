"""Draws the Open Recorder logo and writes every file that shows it.

The mark is an open ring (the O of Open). It starts at the gap with a leaf-shaped tip, one side rounded and one straight, and ends with a flat cut. It sits
on a rounded tile with a blue gradient.

Writes:
    src/open_recorder/assets/logo.svg           the tile, the source for everything below
    src/open_recorder/assets/open-recorder.ico  16 to 256 px, for the shortcut and the taskbar
    src/open_recorder/assets/icon.png           512 px, for the README and GitHub
    src/open_recorder/editor/ui/img/logo.svg    the tile again, the editor's favicon
    src/open_recorder/editor/ui/js/logo.js      the ring inline, for the editor's top bar

The PNGs are rendered by a headless Edge, so no window opens (needs `pip install playwright`).
Run it again after changing a number below:  python tools/make_icon.py
"""
from __future__ import annotations

import io
import math
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1] / "src" / "open_recorder"
ASSETS = ROOT / "assets"
UI = ROOT / "editor" / "ui"

GRADIENT = ("#0051BD", "#2F6BFF")  # top left to bottom right
RING = "#FFFFFF"
TILE_RADIUS = 14  # on the 64 grid

# The ring on a 64 x 64 grid. Angles in degrees, counter-clockwise from 3 o'clock.
NORMAL = dict(radius=17.4, stroke=8.4, tip=72.0, span=296.0)
SMALL = dict(radius=17.6, stroke=10.2, tip=74.0, span=290.0)  # 16 and 24 px: bolder or it blurs
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _pt(r: float, angle: float) -> tuple[float, float]:
    a = math.radians(angle)
    return 32 + r * math.cos(a), 32 - r * math.sin(a)


def _f(p) -> str:
    return f"{p[0]:.2f} {p[1]:.2f}"


def ring_path(radius: float, stroke: float, tip: float, span: float, **_) -> str:
    """The open ring as one filled outline: the inner edge from the tip round to the flat end,
    the outer edge back, then the leaf curve from the outer edge into the pointed tip."""
    ri, ro = radius - stroke / 2, radius + stroke / 2
    end, mid = tip + span, tip + span / 2
    back = math.degrees(stroke / ro)  # the outer edge stops one stroke short of the tip
    tip_in, outer_start, corner = _pt(ri, tip), _pt(ro, tip + back), _pt(ro, tip)
    k = 0.55  # how full the leaf curve is (the same feel as the stem tops of the uh mark)
    c1 = tuple(o + k * (c - o) for o, c in zip(outer_start, corner))
    c2 = tuple(i + k * (c - i) for i, c in zip(tip_in, corner))
    return (f"M{_f(tip_in)}A{ri} {ri} 0 0 0 {_f(_pt(ri, mid))}A{ri} {ri} 0 0 0 {_f(_pt(ri, end))}"
            f"L{_f(_pt(ro, end))}A{ro} {ro} 0 0 1 {_f(_pt(ro, mid))}A{ro} {ro} 0 0 1 {_f(outer_start)}"
            f"C{_f(c1)} {_f(c2)} {_f(tip_in)}Z")


def tile_svg(g: dict = NORMAL) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
            f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
            f'<stop offset="0" stop-color="{GRADIENT[0]}"/><stop offset="1" stop-color="{GRADIENT[1]}"/>'
            f'</linearGradient></defs>'
            f'<rect width="64" height="64" rx="{TILE_RADIUS}" fill="url(#g)"/>'
            f'<path fill="{RING}" d="{ring_path(**g)}"/></svg>\n')


def mark_js() -> str:
    """The ring in the text colour, cropped close to it."""
    pad = NORMAL["radius"] + NORMAL["stroke"] / 2 + 0.5
    box = f"{32 - pad:.2f} {32 - pad:.2f} {2 * pad:.2f} {2 * pad:.2f}"
    svg = (f'<svg class="logo-mark" viewBox="{box}" aria-hidden="true">'
           f'<path fill="currentColor" d="{ring_path(**NORMAL)}"/></svg>')
    return ("// Written by tools/make_icon.py, do not edit by hand: change the numbers there and run it.\n"
            f"export const LOGO_MARK = '{svg}';\n")


def render(svgs: dict[int, str]) -> dict[int, Image.Image]:
    """Each SVG at its size, with a transparent background, through a headless Edge."""
    from playwright.sync_api import sync_playwright
    out = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(device_scale_factor=1)
        for size, svg in svgs.items():
            sized = svg.replace("<svg ", '<svg width="100%" height="100%" ', 1)
            page.set_viewport_size({"width": size, "height": size})
            page.set_content('<html><body style="margin:0;background:transparent">'
                             f'<div style="width:{size}px;height:{size}px">{sized}</div></body></html>')
            png = page.screenshot(omit_background=True, clip={"x": 0, "y": 0, "width": size, "height": size})
            out[size] = Image.open(io.BytesIO(png)).convert("RGBA")
        browser.close()
    return out


def main() -> int:
    normal, small = tile_svg(NORMAL), tile_svg(SMALL)
    (UI / "img").mkdir(parents=True, exist_ok=True)
    for path in (ASSETS / "logo.svg", UI / "img" / "logo.svg"):
        path.write_text(normal, encoding="utf-8")
    (UI / "js" / "logo.js").write_text(mark_js(), encoding="utf-8")

    images = render({s: (small if s <= 24 else normal) for s in (*ICO_SIZES, 512)})
    images[512].save(ASSETS / "icon.png")
    images[256].save(ASSETS / "open-recorder.ico", format="ICO", sizes=[(s, s) for s in ICO_SIZES],
                     append_images=[images[s] for s in ICO_SIZES if s != 256])
    for name in ("logo.svg", "open-recorder.ico", "icon.png"):
        print(f"wrote {ASSETS / name}")
    print(f"wrote {UI / 'img' / 'logo.svg'}\nwrote {UI / 'js' / 'logo.js'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
