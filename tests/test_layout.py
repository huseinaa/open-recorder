import pytest

from open_recorder.core import Sequence
from open_recorder.core import layout


def px(t, seq):
    w, h = seq.size
    return t.x * w, t.y * h, t.w * w, t.h * h


def test_landscape_face_matches_the_lectures():
    seq = Sequence("16:9")
    x, y, w, h = px(layout.face(seq), seq)
    assert (round(x), round(y), round(w), round(h)) == (25, 1080 - 300 - 25, 300, 300)


@pytest.mark.parametrize("aspect", ["16:9", "9:16", "1:1", "4:5"])
def test_face_is_square_bottom_left_and_inside(aspect):
    seq = Sequence(aspect)
    x, y, w, h = px(layout.face(seq), seq)
    cw, ch = seq.size
    assert w == pytest.approx(h)
    assert x > 0 and y + h < ch and x < cw / 2 and y > ch / 2


def test_portrait_screen_fits_the_width_near_the_top():
    seq = Sequence("9:16")
    t = layout.screen(seq)
    x, y, w, h = px(t, seq)
    assert w == 1080 and h == pytest.approx(1080 * 9 / 16) and t.y == layout.PORTRAIT_SCREEN_TOP


def test_refit_keeps_full_frame_full():
    t = layout.screen(Sequence("16:9"))
    again = layout.refit(t, Sequence("16:9"), Sequence("1:1"))
    assert (again.x, again.y, again.w, again.h) == (0, 0, 1, 1)
