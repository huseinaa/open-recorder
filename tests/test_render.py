"""A real export: two takes, a cut, a blur, a square mask, then the output is checked with ffprobe."""
import json

import pytest

from open_recorder import ffmpeg
from open_recorder.core import apply
from open_recorder.export import ExportJob
from open_recorder.project import load, scan

from test_project import make_take

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg is not installed")


def streams(path):
    r = ffmpeg.run([ffmpeg.FFPROBE, "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
                    "-of", "json", str(path)], encoding="utf-8")
    return json.loads(r.stdout)


@pytest.mark.parametrize("aspect,size", [("16:9", (1920, 1080)), ("9:16", (1080, 1920))])
def test_export(tmp_path, aspect, size):
    make_take(tmp_path, "20260101_120000", seconds=3)
    make_take(tmp_path, "20260101_120500", seconds=2, offset=0.2)
    p = load(tmp_path)
    p.sequence.aspect = aspect
    scan(tmp_path, p)
    p, _ = apply(p, [{"op": "add_recording", "recording": "20260101_120000"},
                     {"op": "add_recording", "recording": "20260101_120500"},
                     {"op": "cut_range", "start": 1.0, "end": 1.5},
                     {"op": "add_blur", "start": 0.2, "end": 1.0}])
    face = next(ln for ln in p.lanes if ln.role == "face").clips[1]
    p, _ = apply(p, [{"op": "set_mask", "clips": face.id, "mask": "square"}])
    expected = p.duration
    done = {}
    job = ExportJob(p, tmp_path / "Exports" / "out.mp4", tmp_path / ".openrecorder" / "cache", encoder="libx264",
                    on_done=lambda ok, msg: done.update(ok=ok, msg=msg))
    job._run()
    assert done["ok"], done["msg"]
    info = streams(tmp_path / "Exports" / "out.mp4")
    kinds = {s["codec_type"] for s in info["streams"]}
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert kinds == {"video", "audio"}
    assert (video["width"], video["height"]) == size
    assert float(info["format"]["duration"]) == pytest.approx(expected, abs=0.15)
