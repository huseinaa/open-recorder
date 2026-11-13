"""The AI side without a real AI: fake providers for the router and chat, a fake CLI on PATH for
the Claude and Codex runners."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

from open_recorder.ai import AIError, Claude, Codex, LimitReached, NotSignedIn, Router, Unavailable, ask
from open_recorder.ai.base import Provider, resets_at
from open_recorder.ai.chat import order_cuts
from open_recorder.ai.context import build_prompt, timeline_silences, timeline_words
from open_recorder.ai.schema import ANSWER_SCHEMA, prune, strict
from open_recorder.core import apply


class Fake(Provider):
    def __init__(self, name, answers):
        self.name, self.label, self.answers, self.prompts = name, name.title(), list(answers), []

    def run(self, system, prompt, schema, model="", effort="", timeout=0):
        self.prompts.append(prompt)
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


# ---------- router ----------
def test_router_falls_back_and_says_why():
    a = Fake("claude", [LimitReached("out of usage")])
    b = Fake("codex", [{"reply": "ok", "ops": []}])
    r = Router({"claude": a, "codex": b}, primary="claude")
    answer, name, note = r.run("s", "p", {})
    assert name == "codex" and "out of usage" in note
    assert r.order() == ["codex", "claude"]  # the limited one waits at the back


def test_router_both_limited():
    r = Router({"claude": Fake("claude", [LimitReached("x")]), "codex": Fake("codex", [LimitReached("y")])})
    with pytest.raises(LimitReached, match="both"):
        r.run("s", "p", {})


def test_router_only_enabled():
    r = Router({"claude": Fake("claude", []), "codex": Fake("codex", [])}, enabled=set())
    with pytest.raises(NotSignedIn):
        r.run("s", "p", {})


def test_resets_at():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert resets_at("limit, try again in 2 hours 5 minutes", now) == now + timedelta(hours=2, minutes=5)


# ---------- schema ----------
def test_strict_and_prune_round_trip():
    s = strict(ANSWER_SCHEMA)
    op = s["properties"]["ops"]["items"]
    assert op["additionalProperties"] is False and set(op["required"]) == set(op["properties"])
    assert op["properties"]["t"]["type"] == ["number", "null"]
    raw = {"reply": "done", "ops": [{"op": "split", "t": 3, "clip": None, "mask": None}]}
    assert prune(raw, ANSWER_SCHEMA) == {"reply": "done", "ops": [{"op": "split", "t": 3}]}


# ---------- context ----------
def test_prompt_maps_transcript_and_silences_to_the_timeline(with_recording):
    p, _ = apply(with_recording, [{"op": "cut_range", "start": 1, "end": 2}])
    words = {"camera_1.mp4": {"words": [{"w": "hello", "s": 0.5, "e": 0.9}, {"w": "gone", "s": 1.2, "e": 1.5},
                                        {"w": "world", "s": 2.5, "e": 2.9}]}}
    assert [w for _, _, w in timeline_words(p, words)] == ["hello", "world"]
    assert timeline_words(p, words)[1][0] == pytest.approx(1.5)
    quiet = timeline_silences(p, {"camera_1.mp4": [(3.0, 5.0)]})
    assert quiet == [(pytest.approx(2.0), pytest.approx(4.0))]
    prompt = build_prompt(p, "cut the silences", playhead=1.0, transcripts=words,
                          silences={"camera_1.mp4": [(3.0, 5.0)]})
    assert "world(1.50)" in prompt and "2.00-4.00" in prompt and "FACE + VOICE" in prompt
    assert prompt.rstrip().endswith("cut the silences")


def test_order_cuts_latest_first():
    ops = [{"op": "cut_range", "start": 1, "end": 2}, {"op": "cut_range", "start": 5, "end": 6},
           {"op": "split", "t": 1}, {"op": "cut_range", "start": 0, "end": 0.5}]
    assert [o.get("start") for o in order_cuts(ops)] == [5, 1, None, 0]


# ---------- chat ----------
def test_ask_applies_ops_as_one_copy(with_recording):
    fake = Fake("claude", [{"reply": "Cut two pauses.", "ops": [
        {"op": "cut_range", "start": 2, "end": 3}, {"op": "cut_range", "start": 10, "end": 12}]}])
    answer = ask(Router({"claude": fake}), with_recording, "cut the pauses")
    assert answer.reply == "Cut two pauses." and answer.after == pytest.approx(answer.before - 3)
    assert with_recording.duration == 21  # the original is untouched


def test_ask_retries_once_with_the_error(with_recording):
    fake = Fake("claude", [{"reply": "x", "ops": [{"op": "delete", "clips": ["nope"]}]},
                           {"reply": "fixed", "ops": [{"op": "split", "t": 4}]}])
    answer = ask(Router({"claude": fake}), with_recording, "split")
    assert answer.reply == "fixed" and "COULD NOT BE APPLIED" in fake.prompts[1]


def test_ask_gives_up_after_the_retry(with_recording):
    bad = {"reply": "x", "ops": [{"op": "delete", "clips": ["nope"]}]}
    with pytest.raises(AIError):
        ask(Router({"claude": Fake("claude", [bad, bad])}), with_recording, "x")


def test_ask_with_no_ops(with_recording):
    answer = ask(Router({"claude": Fake("claude", [{"reply": "Which part?", "ops": []}])}), with_recording, "hm")
    assert answer.project is None and answer.reply == "Which part?"


# ---------- the real runners, against a fake CLI ----------
@pytest.fixture
def fake_cli(tmp_path, monkeypatch):
    """Puts claude.cmd and codex.cmd on PATH; they print FAKE_OUT and exit with FAKE_CODE."""
    script = tmp_path / "fake.py"
    script.write_text("import os, sys\nsys.stdin.read()\nsys.stdout.write(os.environ.get('FAKE_OUT', ''))\n"
                      "sys.stderr.write(os.environ.get('FAKE_ERR', ''))\nsys.exit(int(os.environ.get('FAKE_CODE', '0')))\n")
    for name in ("claude", "codex"):
        (tmp_path / f"{name}.cmd").write_text(f'@"{sys.executable}" "{script}" %*\n')
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-be-used")

    def set_out(out="", code=0, err=""):
        monkeypatch.setenv("FAKE_OUT", out)
        monkeypatch.setenv("FAKE_CODE", str(code))
        monkeypatch.setenv("FAKE_ERR", err)
    return set_out


SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


def test_claude_runner(fake_cli):
    fake_cli(json.dumps({"structured_output": {"ok": True}, "usage": {}}))
    c = Claude()
    assert c.run("sys", "hi", SCHEMA) == {"ok": True}
    assert "ANTHROPIC_API_KEY" not in c.environment()
    fake_cli(json.dumps({"is_error": True, "result": "Not logged in · Please run /login"}), code=1)
    with pytest.raises(NotSignedIn):
        c.run("sys", "hi", SCHEMA)
    fake_cli(json.dumps({"is_error": True, "result": "You've hit your usage limit"}), code=1)
    with pytest.raises(LimitReached):
        c.run("sys", "hi", SCHEMA)
    fake_cli("not json", code=1, err="boom")
    with pytest.raises(Unavailable):
        c.run("sys", "hi", SCHEMA)
    assert c.check().state == "error"


def test_codex_runner(fake_cli):
    events = [{"type": "thread.started"},
              {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps({"ok": True})}},
              {"type": "turn.completed", "usage": {}}]
    fake_cli("\n".join(json.dumps(e) for e in events))
    assert Codex().run("sys", "hi", SCHEMA) == {"ok": True}
    assert Codex().check().state == "connected"
    fake_cli(json.dumps({"type": "turn.failed", "error": {"message": "401 Unauthorized"}}), code=1)
    with pytest.raises(NotSignedIn):
        Codex().run("sys", "hi", SCHEMA)


def test_not_installed(monkeypatch):
    monkeypatch.setenv("PATH", "")
    assert Claude().check().state == "not_installed"
