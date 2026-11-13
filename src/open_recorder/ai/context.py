"""What the AI is told: how to edit (the system prompt) and what is on the timeline right now
(the prompt). Pure: transcripts and silences are passed in, already loaded."""
from __future__ import annotations

from ..core import Project
from ..core.timeline import to_timeline

SYSTEM = """You are the editing assistant inside Open Recorder, a screen and webcam recorder with a simple
timeline editor. You change the edit only by returning ops; the app applies them as one step the user
can undo. Reply in the user's language, in one or two short plain sentences that say what you changed.
If the request is unclear or impossible, return no ops and say what you need.

How the timeline works
- Times are timeline seconds unless a field says otherwise. Lanes are listed top first; the top lane is
  drawn over the lanes below it. A recording is two linked clips: the face (camera, with the voice) on
  FACE + VOICE and the screen on SCREEN. Linked clips are cut, moved and deleted together.
- Boxes (x, y, w, h) are fractions of the canvas, 0 to 1, from the top-left corner.

Ops (use only the ids listed in the prompt; never invent a clip, lane or media id)
- cut_range start end [lanes] [ripple=true]: remove that stretch of time from every unlocked lane (or the
  named lanes) and close the gap. The main tool for removing silences, mistakes and retakes.
- split t [clips]; delete clips; ripple_delete clips; trim clip [start] [end]; move clip start [lane]
- add_recording recording [start]; add_clip media [lane] [start] [src_in] [src_out] (src times are in
  the file); add_lane kind [name] [index]; set_lane lane [name] [hidden] [muted] [locked]
- add_blur start end [x y w h] [strength]; set_blur clips strength
- detach_audio clip; set_volume clips volume (1 = normal, 0 = silent)
- set_transform clips [x y w h] [fit] [opacity]; set_mask clips mask (none, circle, square) [radius];
  reset_layout [clips]; set_sequence [aspect] [relayout]; link clips; unlink clips

Rules
- Several cut_range ops: list them from the LATEST start to the EARLIEST, because each cut moves
  everything after it to the left.
- Removing silences or dead air: leave about 0.15 s of air before and after speech, and do not cut a
  pause shorter than 0.4 s unless asked.
- Retakes: when the same sentence is said twice, keep the last complete take unless the user says
  otherwise, and cut the earlier attempt from its first word to the start of the kept take.
- Without a transcript you cannot know the words; you can still cut silences. Say so if it matters.
- A blur is placed where the user describes ("top right") since you cannot see the picture; the user
  can drag it after.
"""


def fmt(t: float) -> str:
    return f"{t:.2f}"


def timeline_words(project: Project, transcripts: dict[str, dict]) -> list[tuple[float, float, str]]:
    """Every transcribed word that is still on the timeline, in timeline time."""
    out = []
    for lane, clip in project.clips():
        if not clip.audio or lane.muted or clip.media not in transcripts:
            continue
        for word in transcripts[clip.media].get("words", []):
            if clip.src_in <= word["s"] < clip.src_out:
                s = to_timeline(clip, word["s"])
                e = to_timeline(clip, min(word["e"], clip.src_out))
                out.append((s, e if e is not None else s, word["w"]))
    return sorted(out)


def timeline_silences(project: Project, silences: dict[str, list]) -> list[tuple[float, float]]:
    found = []
    for lane, clip in project.clips():
        if not clip.audio or lane.muted or clip.media not in silences:
            continue
        for a, b in silences[clip.media]:
            a, b = max(a, clip.src_in), min(b, clip.src_out)
            if b - a > 0.05:
                found.append((to_timeline(clip, a), to_timeline(clip, b)))
    merged: list[list[float]] = []
    for a, b in sorted(found):
        if merged and a <= merged[-1][1] + 0.01:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def transcript_lines(words: list[tuple[float, float, str]], gap: float = 0.7, max_words: int = 14) -> list[str]:
    lines, line = [], []
    for s, e, w in words:
        if line and (s - line[-1][1] > gap or len(line) >= max_words):
            lines.append(line)
            line = []
        line.append((s, e, w))
    if line:
        lines.append(line)
    return [f"[{fmt(ln[0][0])}-{fmt(ln[-1][1])}] " + " ".join(f"{w}({fmt(s)})" for s, _, w in ln) for ln in lines]


def describe_project(project: Project) -> list[str]:
    w, h = project.sequence.size
    out = [f"CANVAS {project.sequence.aspect} ({w}x{h}), {project.sequence.fps} fps. "
           f"LENGTH {fmt(project.duration)}s.", "", "LANES (top first):"]
    for lane in project.lanes:
        flags = [f for f in ("hidden", "muted", "locked") if getattr(lane, f)]
        out.append(f"- {lane.id} \"{lane.name}\" {lane.kind}" + (f" role={lane.role}" if lane.role else "")
                   + (f" [{', '.join(flags)}]" if flags else ""))
        for c in sorted(lane.clips, key=lambda c: c.start):
            t = c.transform
            bits = [f"{fmt(c.start)}-{fmt(c.end)}"]
            if lane.kind == "blur":
                bits.append(f"strength {c.strength:g}")
            else:
                bits.append(f"{c.media} file {fmt(c.src_in)}-{fmt(c.src_out)}")
                bits.append("sound" if c.audio else "no sound")
                if c.volume != 1:
                    bits.append(f"volume {c.volume:g}")
            bits.append(f"box {t.x:.2f},{t.y:.2f},{t.w:.2f},{t.h:.2f}" + (f" mask {t.mask}" if t.mask != "none" else ""))
            if c.link:
                bits.append(f"link {c.link}")
            out.append(f"    {c.id}: " + ", ".join(bits))
    out += ["", "MEDIA:"]
    for m in project.media.values():
        what = f"{m.kind} {fmt(m.duration)}s" if m.kind != "image" else "image"
        rec = f", recording {m.recording} ({m.role})" if m.recording else ""
        out.append(f"- {m.key}: {what}{rec}")
    return out


def build_prompt(project: Project, message: str, *, playhead: float = 0.0, selection: list[str] | None = None,
                 transcripts: dict[str, dict] | None = None, silences: dict[str, list] | None = None,
                 history: list[dict] | None = None) -> str:
    out = describe_project(project)
    out += ["", f"PLAYHEAD {fmt(playhead)}s." + (f" SELECTED: {', '.join(selection)}" if selection else "")]
    words = timeline_words(project, transcripts or {})
    out += ["", "TRANSCRIPT (timeline seconds, each word with its start):" if words else
            "TRANSCRIPT: none (no transcription engine, or not transcribed yet)."]
    out += transcript_lines(words)
    quiet = timeline_silences(project, silences or {})
    if quiet:
        out += ["", "SILENCES on the voice (timeline seconds):",
                ", ".join(f"{fmt(a)}-{fmt(b)}" for a, b in quiet)]
    if history:
        out += ["", "EARLIER IN THIS CHAT:"]
        for turn in history[-6:]:
            out.append(f"{turn.get('role', 'user')}: {turn.get('text', '')[:400]}")
    out += ["", "USER REQUEST:", message.strip()]
    return "\n".join(out)
