"""The editor's Python side without a window: the media server, the session, the controller's
take handling, the recorder link and the API's error wrapping."""
import json
import subprocess
import sys
import urllib.error
import urllib.request

import pytest

from open_recorder import ffmpeg
from open_recorder.config import Settings
from open_recorder.editor.api import safe
from open_recorder.editor.controller import Controller
from open_recorder.editor.recorder_link import RecorderLink
from open_recorder.editor.server import Server
from open_recorder.editor.session import Session, voice_keys

from test_project import make_take

needs_ffmpeg = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg is not installed")


@pytest.fixture
def server():
    srv = Server()
    srv.start()
    yield srv
    srv.stop()


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), b""


def test_server_ranges_and_permissions(server, tmp_path):
    f = tmp_path / "clip.mp4"
    f.write_bytes(bytes(range(256)) * 4)
    url = server.media_url(f)
    assert get(url)[0] == 403  # not allowed yet
    server.allowed.file(f)
    status, headers, body = get(url, {"Range": "bytes=10-19"})
    assert status == 206 and body == bytes(range(10, 20)) and headers["Content-Range"] == "bytes 10-19/1024"
    status, _, body = get(url, {"Range": "bytes=-4"})
    assert status == 206 and body == bytes(range(252, 256))
    assert get(url, {"Range": "bytes=5000-"})[0] == 416
    assert get(url.replace(server.token, "wrong"))[0] == 403
    other = tmp_path / "secret.txt"
    other.write_text("no")
    assert get(server.media_url(other))[0] == 403


def test_server_ui_and_no_escape(server):
    status, headers, body = get(server.url)
    assert status == 200 and b"Open Recorder" in body
    assert get(server.url + "js/main.js")[1]["Content-Type"] == "text/javascript"
    assert get(server.url + "../../config.py")[0] in (403, 404)


def test_safe_wraps_errors():
    class A:
        @safe
        def good(self):
            return {"x": 1}

        @safe
        def bad(self):
            raise ValueError("nope")

        @safe
        def boom(self):
            raise RuntimeError("kaput")
    assert A().good() == {"ok": True, "x": 1}
    assert A().bad() == {"ok": False, "error": "nope"}
    assert A().boom()["ok"] is False


@needs_ffmpeg
def test_session_undo_keeps_new_media(server, tmp_path):
    make_take(tmp_path, "20260101_120000")
    s = Session(tmp_path, server)
    assert voice_keys(s.project) == ["camera_20260101_120000.mp4"]
    s.apply([{"op": "add_recording", "recording": "20260101_120000"}], "Add take")
    make_take(tmp_path, "20260101_130000")
    s.rescan()
    assert s.undo() == "Add take"
    assert not list(s.project.clips()) and len(s.project.media) == 4  # the timeline went back, the files did not
    assert s.redo() == "Add take"
    state = s.state()
    assert state["undo"] == "Add take" and all(m["url"].startswith(server.url) for m in state["media"].values())


class FakeWindow:
    def __init__(self):
        self.calls = []

    def minimize(self):
        self.calls.append("min")

    def restore(self):
        self.calls.append("restore")

    def evaluate_js(self, script):
        self.calls.append(script)


@needs_ffmpeg
def test_controller_project_and_take(tmp_path):
    cfg = Settings.load(tmp_path / "config.json")
    ctl = Controller(cfg)
    try:
        assert ctl.boot()["needs_root"]
        ctl.set_root(str(tmp_path / "root"))
        state = ctl.create("Day 1", "9:16")
        assert state["name"] == "Day 1" and state["project"]["sequence"]["aspect"] == "9:16"
        window = FakeWindow()
        ctl.window = window
        ctl.events.attach(window)
        make_take(ctl.session.folder, "20260101_120000")
        ctl._on_recorder({"event": "saved", "id": "20260101_120000", "seconds": 2, "folder": str(ctl.session.folder)})
        lanes = ctl.session.project.lanes
        assert [ln.role for ln in lanes] == ["face", "screen"] and ctl.session.history.labels()[0] == "Add take"
        assert "restore" in window.calls and any("take" in c for c in window.calls if isinstance(c, str))
        names = [p["name"] for p in ctl.projects()]
        assert "Day 1" in names and str(ctl.session.folder) in cfg.recent
    finally:
        ctl.server.stop()


def test_recorder_link_reads_events(tmp_path):
    got = []
    link = RecorderLink(got.append)
    link.folder = tmp_path
    script = ("import json\nprint('noise')\nprint(json.dumps({'event': 'recording', 'id': 'a'}))\n"
              "print(json.dumps({'event': 'saved', 'id': 'a', 'files': []}))\n")
    proc = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
    link._read(proc)
    assert [e["event"] for e in got] == ["recording", "saved", "exited"]
    assert got[1]["folder"] == str(tmp_path)


@needs_ffmpeg
def test_delete_media_takes_clips_and_undo_steps_with_it(server, tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr("open_recorder.win32.recycle", lambda p: (sent.append(p.name), p.unlink()))
    make_take(tmp_path, "20260101_120000")
    make_take(tmp_path, "20260101_130000")
    s = Session(tmp_path, server)
    s.apply([{"op": "add_recording", "recording": "20260101_120000"}], "Add take")
    s.apply([{"op": "add_recording", "recording": "20260101_130000"}], "Add take")
    result = s.delete_media(["screen_20260101_120000.mp4", "camera_20260101_120000.mp4"])
    assert sorted(sent) == ["camera_20260101_120000.mp4", "screen_20260101_120000.mp4"]
    assert result["clips"] == 2 and len(s.project.media) == 2
    assert all("120000" not in c.media for _, c in s.project.clips())
    while s.undo():  # no step can bring a deleted file's clips back
        assert all("120000" not in c.media for _, c in s.project.clips())
    linked = tmp_path.parent / "elsewhere.mp4"
    linked.write_bytes((tmp_path / "screen_20260101_130000.mp4").read_bytes())
    key = s.add_paths([str(linked)])[0]
    s.delete_media([key])
    assert linked.exists() and key not in s.project.media  # linked files only leave the project
