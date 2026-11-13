"""Turn a project into one ffmpeg command. Pure: no files are touched here, so the whole graph is
unit-tested. The runner writes the masks and the graph file, then runs it.

How the picture is built: a black canvas, then every lane from the bottom up, each clip trimmed
by input seeking (-ss/-t), scaled into its box, cut to its mask, and laid over the canvas from its
start to its end. A blur clip blurs what is already drawn inside its box. The sound of every clip
is delayed to its start and mixed."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..core import Clip, Media, Project
from .masks import MaskSpec

GRAPH_TOKEN = "{GRAPH}"


@dataclass
class Plan:
    args: list[str]               # the ffmpeg command, GRAPH_TOKEN where the graph file goes
    graph: str
    masks: list[MaskSpec] = field(default_factory=list)
    duration: float = 0.0


@dataclass
class Layer:
    scale: str
    w: int
    h: int
    x: int
    y: int


def even(v: float) -> int:
    return max(2, int(round(v / 2)) * 2)


def place(clip: Clip, media: Media, cw: int, ch: int) -> Layer:
    """The clip's box on a cw × ch canvas, and the scale that fills (cover) or fits (contain) it."""
    t = clip.transform
    bx, by = round(t.x * cw), round(t.y * ch)
    bw, bh = even(t.w * cw), even(t.h * ch)
    if t.fit == "cover" or not (media.width and media.height):
        return Layer(f"scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh}", bw, bh, bx, by)
    s = min(bw / media.width, bh / media.height)
    sw, sh = even(media.width * s), even(media.height * s)
    return Layer(f"scale={sw}:{sh}", sw, sh, bx + (bw - sw) // 2, by + (bh - sh) // 2)


def blur_box(clip: Clip, cw: int, ch: int) -> tuple[int, int, int, int]:
    """The blur box in pixels, kept inside the canvas (crop cannot reach outside it)."""
    t = clip.transform
    x0, y0 = max(0, round(t.x * cw)), max(0, round(t.y * ch))
    x1, y1 = min(cw, round((t.x + t.w) * cw)), min(ch, round((t.y + t.h) * ch))
    w, h = even(max(2, x1 - x0)), even(max(2, y1 - y0))
    return min(x0, cw - w), min(y0, ch - h), w, h


def build(project: Project, out: Path, video_args: list[str], masks_dir: Path,
          ffmpeg_exe: str = "ffmpeg", audio_bitrate: str = "192k") -> Plan:
    cw, ch = project.sequence.size
    fps = project.sequence.fps
    total = project.duration
    if total <= 0:
        raise ValueError("there is nothing on the timeline to export")

    inputs: list[list[str]] = []
    chains = [f"color=c=black:s={cw}x{ch}:r={fps}:d={total:.3f},format=yuv420p[base]"]
    sounds: list[str] = []
    masks: list[MaskSpec] = []
    base, n = "base", 0

    def add_input(args: list[str]) -> int:
        inputs.append(args)
        return len(inputs) - 1

    for lane in reversed(project.lanes):  # bottom lane first: the top lane is drawn last
        for clip in sorted(lane.clips, key=lambda c: c.start):
            dur, s, e = clip.duration, clip.start, clip.end
            if dur <= 0:
                continue
            when = f"enable='between(t,{s:.3f},{e:.3f})'"
            if lane.kind == "blur":
                if lane.hidden:
                    continue
                x, y, w, h = blur_box(clip, cw, ch)
                chains.append(f"[{base}]split=2[k{n}a][k{n}b];"
                              f"[k{n}b]crop={w}:{h}:{x}:{y},gblur=sigma={clip.strength / 2:.1f}[k{n}c];"
                              f"[k{n}a][k{n}c]overlay={x}:{y}:{when}[b{n}]")
                base, n = f"b{n}", n + 1
                continue
            m = project.media.get(clip.media)
            if m is None:
                continue
            video = lane.kind == "video" and clip.video and m.has_video and not lane.hidden
            sound = clip.audio and m.has_audio and not lane.muted
            if not (video or sound):
                continue
            if m.kind == "image":
                idx = add_input(["-loop", "1", "-framerate", str(fps), "-t", f"{dur:.3f}", "-i", m.path])
            else:
                idx = add_input(["-ss", f"{clip.src_in:.3f}", "-t", f"{dur:.3f}", "-i", m.path])
            if video:
                layer = place(clip, m, cw, ch)
                v = f"[{idx}:v]setpts=PTS-STARTPTS,fps={fps},{layer.scale},setsar=1,format=rgba"
                t = clip.transform
                if t.mask in ("circle", "square"):
                    spec = MaskSpec(t.mask, layer.w, layer.h, round(t.radius, 3))
                    if spec not in masks:
                        masks.append(spec)
                    midx = add_input(["-loop", "1", "-t", f"{dur:.3f}", "-i", str(masks_dir / spec.name)])
                    v += f"[c{n}];[{midx}:v]format=gray[m{n}];[c{n}][m{n}]alphamerge"
                if t.opacity < 0.999:
                    v += f",colorchannelmixer=aa={t.opacity:.3f}"
                chains.append(f"{v},setpts=PTS+{s:.3f}/TB[v{n}]")
                chains.append(f"[{base}][v{n}]overlay=x={layer.x}:y={layer.y}:eof_action=pass:{when}[b{n}]")
                base = f"b{n}"
            if sound:
                delay = int(round(s * 1000))
                chains.append(f"[{idx}:a]asetpts=PTS-STARTPTS,aresample=48000,"
                              f"aformat=sample_fmts=fltp:channel_layouts=stereo,volume={clip.volume:.3f},"
                              f"adelay={delay}:all=1[a{n}]")
                sounds.append(f"[a{n}]")
            n += 1

    chains.append(f"[{base}]format=yuv420p[vout]")
    if len(sounds) > 1:
        chains.append(f"{''.join(sounds)}amix=inputs={len(sounds)}:normalize=0:dropout_transition=0,"
                      f"apad,atrim=0:{total:.3f}[aout]")
    elif sounds:
        chains.append(f"{sounds[0]}apad,atrim=0:{total:.3f}[aout]")
    else:
        chains.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{total:.3f}[aout]")

    args = [ffmpeg_exe, "-hide_banner", "-y", "-nostdin"]
    for item in inputs:
        args += item
    args += ["-filter_complex_script", GRAPH_TOKEN, "-map", "[vout]", "-map", "[aout]", *video_args,
             "-c:a", "aac", "-b:a", audio_bitrate, "-t", f"{total:.3f}", "-movflags", "+faststart",
             "-progress", "pipe:1", "-nostats", str(out)]
    return Plan(args=args, graph=";\n".join(chains), masks=masks, duration=total)
