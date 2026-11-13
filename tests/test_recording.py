"""Joining segments into one pair, and recovering what a crash left behind. Uses real ffmpeg on
short generated clips, no camera or screen."""
import subprocess

import pytest

from open_recorder import ffmpeg
from open_recorder.recorder.recording import Recording, recover

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg is not installed")


def clip(path, seconds, audio=False):
    cmd = [ffmpeg.FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size=320x180:rate=30:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"] + (["-c:a", "aac"] if audio else []) + [str(path)]
    subprocess.run(cmd, check=True)


def make_recording(tmp_path, parts):
    """parts: list of (seconds, offset). Writes screen + camera .mkv for each, like the recorder."""
    parts_dir = tmp_path / ".recording"
    parts_dir.mkdir()
    rec = Recording(parts_dir, rid="20260101_120000")
    for i, (secs, offset) in enumerate(parts):
        sid = f"20260101_1200{i:02d}"
        seg = {"id": sid, "offset": offset, "screen": parts_dir / f"{sid}_screen.mkv",
               "camera": parts_dir / f"{sid}_camera.mkv"}
        clip(seg["screen"], secs)
        clip(seg["camera"], secs, audio=True)
        rec.segments.append(seg)
    rec.save()
    return rec


def test_manifest_round_trip(tmp_path):
    rec = Recording(tmp_path, rid="x")
    s, c = rec.next_segment()
    rec.set_offset((s, c), -0.47)
    again = Recording.load(rec.manifest)
    assert again.id == "x" and again.segments[0]["offset"] == -0.47
    assert again.segments[0]["screen"] == s and again.segments[0]["camera"] == c


def test_finalize_joins_segments_into_one_pair(tmp_path):
    rec = make_recording(tmp_path, [(2, -0.4), (2, -0.5), (1, -0.45)])
    seconds, problems = rec.finalize(tmp_path)
    assert problems == []
    screen, camera = tmp_path / "screen_20260101_120000.mp4", tmp_path / "camera_20260101_120000.mp4"
    assert screen.exists() and camera.exists()
    assert abs(ffmpeg.duration_of(camera) - 5) < 0.2
    assert abs(ffmpeg.duration_of(screen) - 5) < 0.3
    assert float(ffmpeg.format_tags(screen)["screen_offset"]) == -0.4
    assert not (tmp_path / ".recording" / "20260101_120000.json").exists()  # cleaned up
    assert not list((tmp_path / ".recording").glob("*.mkv"))


def test_recover_finishes_an_unfinished_recording(tmp_path):
    make_recording(tmp_path, [(2, -0.4)])
    found, seconds, problems = recover(tmp_path / ".recording", tmp_path)
    assert (found, problems) == (1, 0)
    assert (tmp_path / "screen_20260101_120000.mp4").exists()


def test_recover_loose_parts_without_manifest(tmp_path):
    parts = tmp_path / ".recording"
    parts.mkdir()
    clip(parts / "20260101_130000_camera.mkv", 1, audio=True)
    found, _, problems = recover(parts, tmp_path)
    assert (found, problems) == (1, 0)
    assert (tmp_path / "camera_20260101_130000.mp4").exists()


def test_recover_with_nothing_to_do(tmp_path):
    parts = tmp_path / ".recording"
    parts.mkdir()
    (parts / "stale.json").write_text("{}")
    assert recover(parts, tmp_path) == (0, 0.0, 0)
    assert not (parts / "stale.json").exists()
