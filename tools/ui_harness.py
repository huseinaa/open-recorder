"""Drive the editor's real back end and page in a headless browser, with no window on screen.

    python tools/ui_harness.py OUT_DIR            # builds a demo project, walks the UI, saves screenshots

The page talks to the real Controller and Api through a Playwright-exposed function instead of
pywebview, and the events Python pushes are pumped into the page. Needs `pip install playwright`
and Microsoft Edge (the same engine as the editor's WebView2)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from playwright.sync_api import sync_playwright  # noqa: E402

from open_recorder import ffmpeg  # noqa: E402
from open_recorder.config import Settings  # noqa: E402
from open_recorder.editor.api import Api  # noqa: E402
from open_recorder.editor.assistant import Assistant  # noqa: E402
from open_recorder.editor.controller import Controller  # noqa: E402

SHIM = """
window.pywebview = { api: new Proxy({}, { get: (_, name) => (...args) =>
  window.__rpc(String(name), JSON.stringify(args)).then(r => JSON.parse(r)) }) };
window.addEventListener('DOMContentLoaded', () => setTimeout(() => window.dispatchEvent(new Event('pywebviewready')), 50));
"""


class FakeWindow:
    """Stands in for the pywebview window: collects pushed events, ignores minimize/restore."""

    def __init__(self):
        self.scripts: list[str] = []
        self.lock = threading.Lock()
        self.width, self.height = 1440, 900

    def evaluate_js(self, script):
        with self.lock:
            self.scripts.append(script)

    def take(self):
        with self.lock:
            out, self.scripts = self.scripts, []
        return out

    def minimize(self):
        pass

    def restore(self):
        pass

    def create_file_dialog(self, *a, **k):
        return None


def make_take(folder: Path, rid: str, seconds: int, offset: float, tone_gap: bool = True) -> None:
    """A screen file (moving test card) and a camera file (another card + a tone with pauses)."""
    for kind in ("screen", "camera"):
        src = "testsrc2=size=1920x1080:rate=30" if kind == "screen" else "smptebars=size=1280x720:rate=30"
        cmd = [ffmpeg.FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", f"{src}:duration={seconds}"]
        if kind == "camera":
            expr = "sin(2*PI*220*t)*0.4*(lt(mod(t,4),2.5))" if tone_gap else "sin(2*PI*220*t)*0.4"
            cmd += ["-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000:d={seconds}", "-c:a", "aac"]
        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
        if kind == "screen":
            cmd += ["-metadata", f"screen_offset={offset}", "-movflags", "+use_metadata_tags"]
        subprocess.run(cmd + [str(folder / f"{kind}_{rid}.mp4")], check=True)


def main(out_dir: str, ai: bool = False) -> int:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="or-harness-"))
    root = work / "Recordings"
    root.mkdir()
    cfg = Settings.load(work / "config.json")
    cfg.output_dir = str(root)
    cfg.save()
    ctl = Controller(cfg)
    api = Api(ctl, Assistant(ctl))
    window = FakeWindow()
    ctl.window = window
    ctl.events.attach(window)

    def rpc(name, args):
        result = getattr(api, name)(*json.loads(args))
        return json.dumps(result, default=str)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        logs = []
        page.on("console", lambda m: logs.append(f"{m.type}: {m.text}"))
        page.on("pageerror", lambda e: logs.append(f"PAGE ERROR: {e}"))
        page.expose_function("__rpc", rpc)
        page.add_init_script(SHIM)

        def pump(ms=300):
            for _ in range(max(1, ms // 100)):
                page.wait_for_timeout(100)
                for script in window.take():
                    page.evaluate(script)

        def shot(name):
            pump(400)
            page.screenshot(path=str(out / f"{name}.png"))
            print("shot", name)

        page.goto(ctl.server.url)
        pump(800)
        shot("01-start-empty")

        # a project with two takes
        page.click("text=New project")
        pump(300)
        page.fill(".modal input", "Brick Breaker lesson")
        shot("02-new-project")
        page.click(".modal >> text=Create project")
        pump(600)
        folder = Path(ctl.session.folder)
        make_take(folder, "20261112_101500", 12, -0.4)
        make_take(folder, "20261112_102200", 8, 0.2)
        page.click("[title='Look for new files in the folder']")
        pump(2500)
        shot("03-editor-bin")
        page.dblclick(".bin-item >> nth=1")
        pump(800)
        page.dblclick(".bin-item >> nth=0")
        pump(2500)
        shot("04-editor-two-takes")

        # select the face clip, see Effect Controls and the handles
        page.click(".clip.k-face >> nth=0", position={"x": 30, "y": 30})
        pump(500)
        shot("05-face-selected")

        # split at 5s with the razor tool, then delete the right part with ripple
        page.keyboard.press("Home")
        page.keyboard.press("c")
        box = page.locator(".clip.k-face >> nth=0").bounding_box()
        page.mouse.click(box["x"] + box["width"] * 0.4, box["y"] + 20)
        pump(800)
        page.keyboard.press("v")
        shot("06-after-razor")

        # vertical canvas
        page.select_option(".aspect-pick", "9:16")
        pump(1200)
        page.click(".toast >> text=Use the default layout")
        pump(800)
        shot("07-vertical")

        # blur lane
        page.click(".tl-toolbar button:has-text(\"Lane\")")
        pump(200)
        page.click(".menu >> text=Blur a box at the playhead")
        pump(800)
        shot("08-blur")

        # AI tab: setup cards
        page.click(".tabs >> text=AI")
        pump(800)
        shot("09-ai-setup")
        if ai:
            page.click("text=Connect Claude")
            pump(40000)
            shot("10-ai-connected")
            if page.locator("text=Not now").count():
                page.click("text=Not now")
                pump(500)
            page.fill(".composer textarea", "Cut the silences")
            page.keyboard.press("Enter")
            for _ in range(120):
                pump(1000)
                if not page.locator(".thinking").count():
                    break
            shot("11-ai-answer")

        # export
        page.click(".topbar >> text=Export")
        pump(500)
        shot("12-export")
        page.click(".modal button.primary")
        for _ in range(120):
            pump(500)
            if page.locator(".modal >> text=Exported").count() or page.locator(".modal >> text=Export failed").count():
                break
        shot("13-exported")
        page.keyboard.press("Escape")
        pump(300)

        page.click("[title='Settings']")
        pump(600)
        shot("14-settings")
        page.keyboard.press("Escape")

        page.click("[title='Back to projects']")
        pump(1500)
        shot("15-start-with-project")
        (out / "console.txt").write_text("\n".join(logs), encoding="utf-8")
        print("\n".join(l for l in logs if "error" in l.lower()) or "no page errors")
        browser.close()
    print("work folder:", work)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], ai="--ai" in sys.argv))
