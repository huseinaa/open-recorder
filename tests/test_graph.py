from pathlib import Path

import pytest

from open_recorder.core import apply
from open_recorder.export.graph import GRAPH_TOKEN, blur_box, build, place


def plan_for(p):
    return build(p, Path("out.mp4"), ["-c:v", "libx264"], Path("masks"))


def test_empty_timeline_is_refused(project):
    with pytest.raises(ValueError):
        plan_for(project)


def test_recording_graph(with_recording):
    plan = plan_for(with_recording)
    g = plan.graph
    assert plan.duration == 21
    assert "color=c=black:s=1920x1080:r=30:d=21.000" in g
    assert g.index("overlay=x=0:y=0") < g.index("overlay=x=25:y=755")  # screen drawn before the face
    assert "alphamerge" in g and len(plan.masks) == 1 and plan.masks[0].shape == "circle"
    assert g.count("adelay=") == 1  # only the face carries the voice
    assert GRAPH_TOKEN in plan.args and plan.args[-1] == "out.mp4"
    i = plan.args.index("-ss")
    assert plan.args[i + 1] in ("0.000",) and plan.args[i + 2] == "-t"


def test_screen_starts_at_its_offset(with_recording):
    g = plan_for(with_recording).graph
    assert "setpts=PTS+0.500/TB" in g and "between(t,0.500,21.000)" in g


def test_cut_makes_two_seeks(with_recording):
    p, _ = apply(with_recording, [{"op": "cut_range", "start": 5, "end": 8}])
    plan = plan_for(p)
    seeks = [plan.args[i + 1] for i, a in enumerate(plan.args) if a == "-ss"]
    assert "8.000" in seeks and seeks.count("0.000") == 2
    assert plan.duration == 18


def test_hidden_and_muted_lanes(with_recording):
    face = next(ln for ln in with_recording.lanes if ln.role == "face")
    p, _ = apply(with_recording, [{"op": "set_lane", "lane": face.id, "hidden": True, "muted": True}])
    g = plan_for(p).graph
    assert "alphamerge" not in g and "adelay" not in g and "anullsrc" in g


def test_blur_and_image_and_music(with_recording):
    p, _ = apply(with_recording, [{"op": "add_blur", "start": 1, "end": 3, "x": 0.9, "y": 0.9, "w": 0.3, "h": 0.3},
                                  {"op": "add_clip", "media": "logo.png", "start": 2},
                                  {"op": "add_clip", "media": "music.mp3"}])
    plan = plan_for(p)
    g = plan.graph
    assert "gblur" in g and "crop=" in g
    assert "-loop" in plan.args
    assert "amix=inputs=2" in g
    assert g.index("gblur") > g.index("alphamerge")  # the blur lane is on top, so it is applied last


def test_contain_keeps_the_picture_whole(with_recording):
    screen = next(ln for ln in with_recording.lanes if ln.role == "screen").clips[0]
    m = with_recording.media[screen.media]
    m.width, m.height = 1280, 1024  # a 5:4 screen on a 16:9 canvas
    layer = place(screen, m, 1920, 1080)
    assert layer.h == 1080 and layer.w == 1350 and layer.x == (1920 - 1350) // 2


def test_blur_box_stays_inside():
    from open_recorder.core.model import Clip, Transform
    c = Clip(id="b", media="", start=0, src_in=0, src_out=1, transform=Transform(x=0.9, y=-0.2, w=0.3, h=0.5))
    x, y, w, h = blur_box(c, 1920, 1080)
    assert x >= 0 and y >= 0 and x + w <= 1920 and y + h <= 1080 and w % 2 == 0 and h % 2 == 0
