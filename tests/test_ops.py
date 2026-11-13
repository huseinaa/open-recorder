import pytest

from open_recorder.core import OpError, Project, apply
from open_recorder.core.ops import describe


def lane(p, role=None, kind=None):
    return next(ln for ln in p.lanes if (role and ln.role == role) or (kind and ln.kind == kind and not ln.role))


def spans(ln):
    return [(round(c.start, 3), round(c.end, 3)) for c in sorted(ln.clips, key=lambda c: c.start)]


# ---------- adding ----------
def test_add_recording_places_face_over_screen_with_offset(with_recording):
    p = with_recording
    assert [ln.role for ln in p.lanes] == ["face", "screen"]
    face, screen = lane(p, "face").clips[0], lane(p, "screen").clips[0]
    assert face.start == 0 and face.src_in == 0
    assert screen.start == 0.5 and screen.src_in == 0  # offset -0.5: the screen began half a second later
    assert face.link and face.link == screen.link
    assert face.audio and not screen.audio  # the voice is in the camera file
    assert face.transform.mask == "circle"


def test_add_recording_positive_offset_trims_screen_start(project):
    project.media["screen_1.mp4"].offset = 0.3
    p, _ = apply(project, [{"op": "add_recording", "recording": "1"}])
    screen = lane(p, "screen").clips[0]
    assert screen.start == 0 and screen.src_in == pytest.approx(0.3)


def test_second_recording_goes_after_the_first(with_recording):
    p, _ = apply(with_recording, [{"op": "add_recording", "recording": "1"}])
    assert spans(lane(p, "face")) == [(0, 20), (21, 41)]  # after the screen clip, which ends at 21


def test_add_clip_defaults(project):
    p, _ = apply(project, [{"op": "add_clip", "media": "broll.mp4"},
                           {"op": "add_clip", "media": "logo.png", "start": 2},
                           {"op": "add_clip", "media": "music.mp3"}])
    kinds = [ln.kind for ln in p.lanes]
    assert kinds.count("audio") == 1 and kinds.index("audio") == len(kinds) - 1
    image = next(c for _, c in p.clips() if c.media == "logo.png")
    assert image.duration == 5.0
    music = next(c for _, c in p.clips() if c.media == "music.mp3")
    assert not music.video and music.audio


def test_add_clip_rejects_wrong_lane(project):
    p, _ = apply(project, [{"op": "add_lane", "kind": "audio"}])
    audio = lane(p, kind="audio")
    with pytest.raises(OpError):
        apply(p, [{"op": "add_clip", "media": "logo.png", "lane": audio.id}])


def test_add_clip_overwrites_what_is_under_it(project):
    p, _ = apply(project, [{"op": "add_lane", "kind": "video", "name": "B"}])
    b = p.lanes[0].id
    p, _ = apply(p, [{"op": "add_clip", "media": "broll.mp4", "lane": b, "start": 0},
                     {"op": "add_clip", "media": "logo.png", "lane": b, "start": 2}])
    assert spans(p.lane(b)) == [(0, 2), (2, 7), (7, 8)]


# ---------- cutting ----------
def test_split_links_the_right_halves(with_recording):
    p, _ = apply(with_recording, [{"op": "split", "t": 10}])
    face, screen = lane(p, "face"), lane(p, "screen")
    assert spans(face) == [(0, 10), (10, 20)] and spans(screen) == [(0.5, 10), (10, 21)]
    right_face = sorted(face.clips, key=lambda c: c.start)[1]
    right_screen = sorted(screen.clips, key=lambda c: c.start)[1]
    left_face = sorted(face.clips, key=lambda c: c.start)[0]
    assert right_face.link == right_screen.link != left_face.link
    assert right_face.src_in == 10


def test_cut_range_ripples_every_lane(with_recording):
    p, _ = apply(with_recording, [{"op": "cut_range", "start": 5, "end": 8}])
    assert spans(lane(p, "face")) == [(0, 5), (5, 17)]
    assert spans(lane(p, "screen")) == [(0.5, 5), (5, 18)]
    later = sorted(lane(p, "face").clips, key=lambda c: c.start)[1]
    assert later.src_in == 8  # it plays from where the cut ended


def test_cut_range_without_ripple_leaves_a_gap(with_recording):
    p, _ = apply(with_recording, [{"op": "cut_range", "start": 5, "end": 8, "ripple": False}])
    assert spans(lane(p, "face")) == [(0, 5), (8, 20)]


def test_cut_range_skips_locked_lanes(with_recording):
    screen = lane(with_recording, "screen")
    p, _ = apply(with_recording, [{"op": "set_lane", "lane": screen.id, "locked": True},
                                  {"op": "cut_range", "start": 5, "end": 8}])
    assert spans(lane(p, "screen")) == [(0.5, 21)]


def test_delete_follows_links_unless_told_not_to(with_recording):
    face = lane(with_recording, "face").clips[0]
    p, _ = apply(with_recording, [{"op": "delete", "clips": face.id}])
    assert not lane(p, "face").clips and not lane(p, "screen").clips
    p, _ = apply(with_recording, [{"op": "delete", "clips": face.id, "link": False}])
    assert not lane(p, "face").clips and lane(p, "screen").clips


def test_ripple_delete_closes_the_gap(with_recording):
    p, _ = apply(with_recording, [{"op": "split", "t": 5}, {"op": "split", "t": 8}])
    middle = next(c for c in lane(p, "face").clips if c.start == 5)
    p, notes = apply(p, [{"op": "ripple_delete", "clips": middle.id}])
    assert spans(lane(p, "face")) == [(0, 5), (5, 17)]
    assert "closed" in notes[0]


def test_ripple_delete_keeps_the_gap_when_another_lane_has_clips(with_recording):
    p, _ = apply(with_recording, [{"op": "split", "t": 5}, {"op": "split", "t": 8},
                                  {"op": "add_clip", "media": "logo.png", "start": 6}])
    middle = next(c for c in lane(p, "face").clips if c.start == 5)
    p, notes = apply(p, [{"op": "ripple_delete", "clips": middle.id}])
    assert spans(lane(p, "face")) == [(0, 5), (8, 20)]
    assert "gap stays" in notes[0]


def test_trim_is_clamped_to_the_file_and_neighbours(with_recording):
    p, _ = apply(with_recording, [{"op": "split", "t": 10}])
    left = next(c for c in lane(p, "face").clips if c.start == 0)
    p2, _ = apply(p, [{"op": "trim", "clip": left.id, "end": 15, "link": False}])
    assert spans(lane(p2, "face"))[0] == (0, 10)  # the right half is in the way
    p3, _ = apply(p, [{"op": "trim", "clip": left.id, "start": 2}])
    assert spans(lane(p3, "face"))[0] == (2, 10)
    assert spans(lane(p3, "screen"))[0] == (2.5, 10)  # the linked screen clip moved its edge too
    p4, _ = apply(p3, [{"op": "trim", "clip": left.id, "start": -5}])
    assert spans(lane(p4, "face"))[0] == (0, 10)  # stops where the file starts


def test_move_carries_linked_clips(with_recording):
    face = lane(with_recording, "face").clips[0]
    p, _ = apply(with_recording, [{"op": "move", "clip": face.id, "start": 4}])
    assert spans(lane(p, "face")) == [(4, 24)] and spans(lane(p, "screen")) == [(4.5, 25)]
    p, _ = apply(p, [{"op": "move", "clip": face.id, "start": -10}])
    assert spans(lane(p, "face")) == [(0, 20)]  # nothing goes before zero


def test_move_to_other_lane_kind_is_refused(with_recording):
    p, _ = apply(with_recording, [{"op": "add_lane", "kind": "audio"}])
    face = lane(p, "face").clips[0]
    with pytest.raises(OpError):
        apply(p, [{"op": "move", "clip": face.id, "start": 0, "lane": lane(p, kind="audio").id}])


def test_detach_audio(with_recording):
    face = lane(with_recording, "face").clips[0]
    p, _ = apply(with_recording, [{"op": "detach_audio", "clip": face.id}])
    audio = lane(p, kind="audio").clips[0]
    face = lane(p, "face").clips[0]
    assert not face.audio and audio.audio and not audio.video and audio.link == face.link


# ---------- layers ----------
def test_set_mask_makes_the_box_square_on_screen(with_recording):
    screen = lane(with_recording, "screen").clips[0]
    p, _ = apply(with_recording, [{"op": "set_mask", "clips": screen.id, "mask": "square"}])
    t = lane(p, "screen").clips[0].transform
    w, h = p.sequence.size
    assert t.w * w == pytest.approx(t.h * h)


def test_blur(with_recording):
    p, _ = apply(with_recording, [{"op": "add_blur", "start": 2, "end": 4, "x": 0.7, "y": 0, "w": 0.3, "h": 0.2}])
    assert p.lanes[0].kind == "blur"
    blur = p.lanes[0].clips[0]
    assert blur.start == 2 and blur.duration == 2 and blur.transform.x == 0.7


def test_set_sequence_keeps_the_face_round(with_recording):
    p, _ = apply(with_recording, [{"op": "set_sequence", "aspect": "9:16"}])
    t = lane(p, "face").clips[0].transform
    w, h = p.sequence.size
    assert (w, h) == (1080, 1920) and t.w * w == pytest.approx(t.h * h)
    p, _ = apply(p, [{"op": "set_sequence", "relayout": True}])
    t = lane(p, "face").clips[0].transform
    assert t.w * w == pytest.approx(0.4 * 1080)


# ---------- the batch ----------
def test_a_bad_op_changes_nothing(with_recording):
    before = with_recording.to_dict()
    with pytest.raises(OpError):
        apply(with_recording, [{"op": "split", "t": 5}, {"op": "delete", "clips": "nope"}])
    assert with_recording.to_dict() == before


def test_unknown_op_and_argument(with_recording):
    with pytest.raises(OpError):
        apply(with_recording, [{"op": "explode"}])
    with pytest.raises(OpError):
        apply(with_recording, [{"op": "split", "t": 1, "colour": "red"}])


def test_json_round_trip(with_recording):
    again = Project.from_dict(with_recording.to_dict())
    assert again.to_dict() == with_recording.to_dict()


def test_describe_lists_every_op():
    ops = describe()
    for name in ("split", "cut_range", "add_recording", "add_blur", "detach_audio", "set_mask", "set_sequence"):
        assert name in ops
    assert "t" in ops["split"]
