import pytest

from open_recorder.core import Media, Project, apply


def make_project(aspect="16:9", offset=-0.5, cam=20.0, scr=20.5) -> Project:
    p = Project(name="Test")
    p.sequence.aspect = aspect
    p.media = {
        "camera_1.mp4": Media(key="camera_1.mp4", path="C:/x/camera_1.mp4", duration=cam, width=1920, height=1080,
                              fps=30, has_audio=True, recording="1", role="camera"),
        "screen_1.mp4": Media(key="screen_1.mp4", path="C:/x/screen_1.mp4", duration=scr, width=1920, height=1080,
                              fps=30, has_audio=True, recording="1", role="screen", offset=offset),
        "broll.mp4": Media(key="broll.mp4", path="C:/x/broll.mp4", duration=8.0, width=1280, height=720,
                           fps=30, has_audio=True),
        "logo.png": Media(key="logo.png", path="C:/x/logo.png", kind="image", width=500, height=500),
        "music.mp3": Media(key="music.mp3", path="C:/x/music.mp3", kind="audio", duration=60.0,
                           has_video=False, has_audio=True),
    }
    return p


@pytest.fixture
def project():
    return make_project()


@pytest.fixture
def with_recording(project):
    p, _ = apply(project, [{"op": "add_recording", "recording": "1"}])
    return p
