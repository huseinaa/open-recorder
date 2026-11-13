from open_recorder.core import History


def test_undo_redo_round_trip():
    h = History(limit=3)
    states = [{"n": i} for i in range(5)]
    for before in states[:4]:
        h.push(before, f"step {before['n']}")
    current = states[4]
    label, current = h.undo(current)
    assert label == "step 3" and current == {"n": 3}
    label, current = h.redo(current)
    assert label == "step 3" and current == {"n": 4}


def test_limit_and_new_edit_clears_redo():
    h = History(limit=2)
    for i in range(4):
        h.push({"n": i}, str(i))
    assert h.undo({"n": 4})[1] == {"n": 3}
    assert h.undo({"n": 3})[1] == {"n": 2}
    assert h.undo({"n": 2}) is None  # only two kept
    h.push({"n": 9}, "new")
    assert not h.can_redo
