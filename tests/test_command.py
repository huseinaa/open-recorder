"""The ffmpeg command for every on/off combination of screen, camera and mic."""
from itertools import product
from pathlib import Path

import pytest

from open_recorder.capture import build_command, preview_size

SCREEN_IN = ["-f", "gdigrab", "-i", "desktop"]
VIDEO = ["-c:v", "libx264"]


def cmd(screen_on, cam_on, mic_on, recording=True, strict=True):
    return build_command(exe="ffmpeg", cam="Cam", mic="Mic", cam_on=cam_on, mic_on=mic_on, strict=strict,
                         width=1920, height=1080, fps=30, video_args=VIDEO, audio_bitrate="192k",
                         preview=preview_size(300), screen_in=SCREEN_IN,
                         screen_path=Path("s.mkv") if recording and screen_on else None,
                         camera_path=Path("c.mkv") if recording and cam_on else None,
                         udp_port=5000 if mic_on else None)


def maps(c):
    return [c[i + 1] for i, a in enumerate(c) if a == "-map"]


def test_preview_size_is_even_16_9():
    assert preview_size(300) == (300, 168)


@pytest.mark.parametrize("screen_on,cam_on,mic_on", list(product([True, False], repeat=3)))
def test_every_combination(screen_on, cam_on, mic_on):
    c = cmd(screen_on, cam_on, mic_on)
    joined = " ".join(c)
    assert ("s.mkv" in c) == screen_on
    assert ("c.mkv" in c) == cam_on
    assert ("pipe:1" in c) == cam_on  # preview frames only with a camera
    assert ("udp://" in joined) == mic_on  # the level meter only with a mic
    if cam_on or mic_on:
        assert c.index("dshow") < (c.index("gdigrab") if screen_on else len(c))  # camera input first
    m = maps(c)
    if screen_on:
        assert m[0] == ("1:v" if cam_on or mic_on else "0:v")
    if screen_on and mic_on and not cam_on:
        assert "0:a" in m[:2]  # the voice goes into the screen file
    if cam_on and mic_on:
        i = m.index("[cv]")
        assert m[i + 1] == "0:a"  # the voice goes into the camera file


def test_dshow_spec():
    c = cmd(True, True, True)
    assert c[c.index("-i", c.index("dshow")) + 1] == "video=Cam:audio=Mic"
    c = cmd(True, False, True)
    assert c[c.index("-i", c.index("dshow")) + 1] == "audio=Mic"


def test_strict_mode_asks_for_mjpeg_only_when_strict():
    assert "mjpeg" in cmd(True, True, True)
    assert "mjpeg" not in cmd(True, True, True, strict=False)


def test_preview_has_no_files():
    c = cmd(True, True, True, recording=False)
    assert not any(a.endswith(".mkv") for a in c)
    assert "split=2[a][b]" in " ".join(c)


def test_files_are_crash_safe_mkv():
    c = cmd(True, True, True)
    assert c.count("-cluster_time_limit") == 2
