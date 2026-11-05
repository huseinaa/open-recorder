import json

from open_recorder.config import Settings


def test_defaults_when_missing(tmp_path):
    s = Settings.load(tmp_path / "config.json")
    assert s.fps == 30 and s.encoder == "auto" and s.output_dir == ""
    assert s.path == tmp_path / "config.json"


def test_round_trip(tmp_path):
    path = tmp_path / "config.json"
    s = Settings.load(path)
    s.camera, s.mic_on, s.theme = "Cam", False, {"accent": "#E5484D"}
    s.save()
    again = Settings.load(path)
    assert again.camera == "Cam" and again.mic_on is False and again.theme == {"accent": "#E5484D"}


def test_wrong_types_and_unknown_keys_are_ignored(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"fps": "fast", "screen_on": 1, "bar_scale": 1, "nope": 3, "nvenc_cq": 23}))
    s = Settings.load(path)
    assert s.fps == 30           # not an int
    assert s.screen_on is True   # 1 is not a bool
    assert s.bar_scale == 1.0    # an int is fine for a float
    assert s.quality == 23       # the old key name is read


def test_broken_file_is_kept_aside(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json")
    s = Settings.load(path)
    assert s.fps == 30
    assert (tmp_path / "config.broken.json").exists()
