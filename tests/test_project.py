"""Projects on disk: the library under the root, the store, and the media scan. Uses real ffmpeg on
short generated clips."""
import subprocess

import pytest

from open_recorder import ffmpeg
from open_recorder.core import apply
from open_recorder.project import Library, load, load_chat, recordings, safe_name, save, save_chat, scan

needs_ffmpeg = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg is not installed")


def make_take(folder, rid="20260101_120000", seconds=2, offset=-0.4):
    for kind in ("screen", "camera"):
        cmd = [ffmpeg.FFMPEG, "-y", "-v", "error", "-f", "lavfi",
               "-i", f"testsrc=size=320x180:rate=30:duration={seconds}"]
        if kind == "camera":
            cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac"]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
        if kind == "screen":
            cmd += ["-metadata", f"screen_offset={offset}", "-movflags", "+use_metadata_tags"]
        subprocess.run(cmd + [str(folder / f"{kind}_{rid}.mp4")], check=True)


def test_safe_name():
    assert safe_name('My: "Lecture"?. ') == "My Lecture"
    assert safe_name("CON").startswith("Project ")
    assert safe_name("  ") .startswith("Project ")


def test_create_numbers_duplicates(tmp_path):
    lib = Library(tmp_path)
    a = lib.create("Day 1", aspect="9:16")
    b = lib.create("Day 1")
    assert a.name == "Day 1" and b.name == "Day 1 (2)"
    assert load(a).sequence.aspect == "9:16"
    names = [p["name"] for p in lib.projects()]
    assert set(names) == {"Day 1", "Day 1 (2)"}


def test_store_round_trip_and_broken_file(tmp_path, with_recording):
    save(tmp_path, with_recording)
    assert load(tmp_path).to_dict() == with_recording.to_dict()
    (tmp_path / ".openrecorder" / "project.json").write_text("{nope", encoding="utf-8")
    fresh = load(tmp_path)
    assert fresh.lanes == [] and (tmp_path / ".openrecorder" / "project.broken.json").exists()


def test_chat_is_kept(tmp_path):
    save_chat(tmp_path, [{"role": "user", "text": "hi"}])
    assert load_chat(tmp_path) == [{"role": "user", "text": "hi"}]


@needs_ffmpeg
def test_scan_pairs_a_take_and_reads_the_offset(tmp_path):
    make_take(tmp_path)
    p = load(tmp_path)
    new = scan(tmp_path, p)
    assert sorted(new) == ["camera_20260101_120000.mp4", "screen_20260101_120000.mp4"]
    pair = recordings(p)["20260101_120000"]
    assert pair["screen"].offset == pytest.approx(-0.4) and pair["camera"].offset == pytest.approx(-0.4)
    assert pair["camera"].has_audio and pair["screen"].duration == pytest.approx(2, abs=0.1)
    p, _ = apply(p, [{"op": "add_recording", "recording": "20260101_120000"}])
    assert scan(tmp_path, p) == []  # nothing new the second time


@needs_ffmpeg
def test_quick_takes_show_in_the_library(tmp_path):
    make_take(tmp_path)
    lib = Library(tmp_path)
    projects = lib.projects()
    assert projects[0]["quick"] and projects[0]["takes"] == 1
    assert lib.quick() == tmp_path


def test_rename_project_moves_the_folder_and_the_name(tmp_path):
    lib = Library(tmp_path)
    a, b = lib.create("Day 1"), lib.create("Day 2")
    new = lib.rename(a, "Day 1: final")
    assert new.name == "Day 1 final" and new.exists() and not a.exists()
    assert load(new).name == "Day 1 final"
    assert lib.rename(new, "Day 1 final") == new  # same name: nothing to do
    with pytest.raises(ValueError, match="already a folder"):
        lib.rename(new, "Day 2")
    with pytest.raises(ValueError, match="Quick takes"):
        lib.rename(tmp_path, "x")
    plain = tmp_path / "Not a project"
    plain.mkdir()
    with pytest.raises(ValueError, match="not an Open Recorder project"):
        lib.rename(plain, "x")
    assert b.exists()


def test_delete_project_goes_to_the_recycle_bin(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr("open_recorder.win32.recycle", lambda p: sent.append(p))
    lib = Library(tmp_path)
    folder = lib.create("Old")
    lib.delete(folder)
    assert sent == [folder.resolve()]
    with pytest.raises(ValueError, match="Quick takes"):
        lib.delete(tmp_path)
    plain = tmp_path / "Holiday photos"
    plain.mkdir()
    with pytest.raises(ValueError, match="not an Open Recorder project"):
        lib.delete(plain)
    assert sent == [folder.resolve()]


@pytest.mark.skipif(not __import__("os").environ.get("OR_TEST_RECYCLE"),
                    reason="puts a folder in your Recycle Bin; set OR_TEST_RECYCLE=1 to run it")
def test_recycle_really_moves_a_folder(tmp_path):
    from open_recorder.win32 import recycle
    victim = tmp_path / "or-recycle-test"
    victim.mkdir()
    (victim / "a.txt").write_text("x")
    recycle(victim)
    assert not victim.exists()
