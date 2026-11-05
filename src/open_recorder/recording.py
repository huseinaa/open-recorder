"""A recording on disk: its segments while it runs, the one video pair it becomes at stop, and the
recovery of whatever a crash left behind.

Every recording is saved as a pair with the same id:
  screen_<id>.mp4   the screen (no audio, unless the camera is off: then the voice is here)
  camera_<id>.mp4   the webcam + the mic (the voice)

Each Pause ends a segment. Stop joins the segments into ONE pair with no re-encode. The camera
starts 0.3 to 0.5 s before the screen and the gap changes every segment, so each one is measured,
and the screen parts are placed so the whole recording carries one exact `screen_offset` tag
(seconds to add to a camera time to get the same moment in the screen file).

Crash safety: segments are written as .mkv in <output>/.recording/ while recording, flushed about
every second, and a manifest (<id>.json) beside them says what belongs together. If the recorder,
ffmpeg or the PC dies, the next open joins whatever was recorded into a normal pair."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

import psutil

from . import ffmpeg
from .logs import log


class Recording:
    def __init__(self, parts_dir: Path, screen_on=True, camera_on=True, mic_on=True, rid=None):
        self.parts_dir = parts_dir
        self.id = rid or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.toggles = {"screen_on": screen_on, "camera_on": camera_on, "mic_on": mic_on}
        self.segments: list[dict] = []  # {"id", "screen": Path|None, "camera": Path|None, "offset": float|None}
        self.manifest = parts_dir / f"{self.id}.json"
        self.written: list[Path] = []

    @property
    def voice_in_screen(self) -> bool:
        t = self.toggles
        return t["screen_on"] and t["mic_on"] and not t["camera_on"]

    def next_segment(self) -> tuple[Path | None, Path | None]:
        sid = datetime.now().strftime("%Y%m%d_%H%M%S")
        while any(seg["id"] == sid for seg in self.segments):  # paused and resumed inside one second
            sid = sid[:-2] + f"{int(sid[-2:]) + 1:02d}"
        seg = {"id": sid, "offset": None,
               "screen": self.parts_dir / f"{sid}_screen.mkv" if self.toggles["screen_on"] else None,
               "camera": self.parts_dir / f"{sid}_camera.mkv" if self.toggles["camera_on"] else None}
        self.segments.append(seg)
        self.save()
        return seg["screen"], seg["camera"]

    def set_offset(self, outputs, offset: float | None) -> None:
        for seg in self.segments:
            if (seg["screen"], seg["camera"]) == tuple(outputs):
                seg["offset"] = offset
        self.save()

    def save(self) -> None:
        """Rewritten (temp file + rename) at every change, so a crash always leaves a description
        of what is on disk."""
        data = {"id": self.id, "toggles": self.toggles,
                "segments": [{"id": s["id"], "offset": s["offset"],
                              "screen": s["screen"].name if s["screen"] else None,
                              "camera": s["camera"].name if s["camera"] else None} for s in self.segments]}
        tmp = self.manifest.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, self.manifest)

    @classmethod
    def load(cls, manifest: Path) -> "Recording":
        data = json.loads(manifest.read_text(encoding="utf-8"))
        rec = cls(manifest.parent, rid=data["id"], **data.get("toggles", {}))
        for s in data["segments"]:
            rec.segments.append({"id": s["id"], "offset": s.get("offset"),
                                 "screen": manifest.parent / s["screen"] if s.get("screen") else None,
                                 "camera": manifest.parent / s["camera"] if s.get("camera") else None})
        return rec

    def files(self) -> list[Path]:
        return [p for s in self.segments for p in (s["screen"], s["camera"]) if p]

    def delete(self) -> None:
        for p in self.files():
            p.unlink(missing_ok=True)
        self.manifest.unlink(missing_ok=True)

    @staticmethod
    def _remux(mkv: Path, mp4: Path, voice_offset: float | None = None) -> float | None:
        """mkv -> mp4, stream copy. With voice_offset (camera off, voice in the screen file), the
        audio is moved onto the screen's clock: ffmpeg had started each input at 0 on its own."""
        if voice_offset is None:
            cmd = [ffmpeg.FFMPEG, "-y", "-v", "error", "-i", str(mkv), "-map", "0", "-c", "copy", str(mp4)]
        else:
            audio_in = (["-ss", f"{-voice_offset:.3f}"] if voice_offset < 0
                        else ["-itsoffset", f"{voice_offset:.3f}"]) + ["-i", str(mkv)]
            cmd = [ffmpeg.FFMPEG, "-y", "-v", "error", "-i", str(mkv), *audio_in,
                   "-map", "0:v", "-map", "1:a?", "-c", "copy", str(mp4)]
        ffmpeg.run(cmd)
        # a segment cut short by a crash can make ffmpeg complain at the end and still write a good
        # file, so the file itself is the test, not the exit code
        return ffmpeg.duration_of(mp4) if mp4.exists() and mp4.stat().st_size > 1000 else None

    def finalize(self, out_dir: Path) -> tuple[float, list[str]]:
        """Join every segment into one pair in out_dir, no re-encode. Returns (seconds, problems).
        The segments and the manifest are deleted only when everything was written."""
        parts, temps, problems = [], [], []
        for seg in self.segments:
            entry = {"offset": seg["offset"]}
            for kind in ("screen", "camera"):
                mkv = seg[kind]
                if not mkv or not mkv.exists() or mkv.stat().st_size < 1000:
                    continue
                mp4 = mkv.with_suffix(".part.mp4")
                temps.append(mp4)
                voice = seg["offset"] if kind == "screen" and self.voice_in_screen else None
                d = self._remux(mkv, mp4, voice)
                if d:
                    entry[kind], entry["d_" + kind] = mp4, d
                else:
                    problems.append(f"{mkv.name} could not be read")
            if "screen" in entry or "camera" in entry:
                parts.append(entry)
        total = 0.0
        if not parts:
            problems.append("nothing was recorded")
        kinds = [k for k in ("screen", "camera") if any(k in p for p in parts)]
        # one exact screen_offset for the whole recording: screen part i starts at
        # Tc_i + o_1 - o_i, where Tc_i is where camera part i starts and o_i its measured offset
        synced = len(kinds) == 2 and all("screen" in p and "camera" in p for p in parts)
        o1 = next((p["offset"] for p in parts if p["offset"] is not None), None) if synced else None
        for kind in kinds:
            mine = [p for p in parts if kind in p]
            lines = []
            for i, p in enumerate(mine):
                lines.append("file '" + p[kind].as_posix().replace("'", "'\\''") + "'")
                if kind == "screen" and o1 is not None and i < len(mine) - 1:
                    oi = p["offset"] if p["offset"] is not None else o1
                    on = mine[i + 1]["offset"] if mine[i + 1]["offset"] is not None else o1
                    slot = p["d_camera"] + oi - on
                    if slot < p["d_screen"]:
                        log.info(f"SAVE {self.id}: part {i + 1} screen slot {slot:.3f} s < its length "
                                 f"{p['d_screen']:.3f} s, using the length (sync off by {p['d_screen'] - slot:.3f} s)")
                        slot = p["d_screen"]
                    lines.append(f"duration {slot:.3f}")
            lst = self.parts_dir / f"{self.id}_{kind}.txt"
            lst.write_text("\n".join(lines) + "\n", encoding="utf-8")
            temps.append(lst)
            dst = out_dir / f"{kind}_{self.id}.mp4"
            tags = ["-metadata", f"screen_offset={o1}"] if kind == "screen" and o1 is not None else []
            r = ffmpeg.run([ffmpeg.FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                            "-map", "0", "-c", "copy", *tags, "-movflags", "+faststart+use_metadata_tags", str(dst)])
            d = ffmpeg.duration_of(dst) if dst.exists() else None
            if d:
                self.written.append(dst)
                total = max(total, d)
                log.info(f"SAVED {dst.name} ({dst.stat().st_size / 1e6:.1f} MB, {d:.1f} s, {len(mine)} part(s)"
                         + (f", screen_offset {o1:+.3f} s)" if tags else ")"))
            else:
                problems.append(f"{dst.name} could not be written: "
                                f"{r.stderr.decode('utf-8', 'replace')[-200:].strip()}")
        for p in temps:
            p.unlink(missing_ok=True)
        if not problems:
            self.delete()
        else:
            for msg in problems:
                log.warning(f"SAVE PROBLEM {self.id}: {msg} (segments kept in .recording)")
        return total, problems


def kill_orphans(parts_dir: Path) -> None:
    """An ffmpeg left behind by a crashed recorder may still be writing into .recording."""
    stopped = []
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            if (p.info["name"] or "").lower().startswith("ffmpeg") and \
                    any(str(parts_dir) in arg for arg in (p.info["cmdline"] or [])):
                p.kill()
                stopped.append(p.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if stopped:
        log.info(f"RECOVER: stopped orphaned ffmpeg {stopped}")
        time.sleep(1)


def recover(parts_dir: Path, out_dir: Path) -> tuple[int, float, int]:
    """Join whatever an unfinished session left in .recording. Returns (recordings, seconds, problems)."""
    if not any(parts_dir.glob("*.mkv")):
        for stale in list(parts_dir.glob("*.json")) + list(parts_dir.glob("*.tmp")):
            stale.unlink(missing_ok=True)
        return 0, 0.0, 0
    kill_orphans(parts_dir)
    recs, known = [], set()
    for mf in sorted(parts_dir.glob("*.json")):
        try:
            rec = Recording.load(mf)
        except (ValueError, KeyError, OSError) as e:
            log.warning(f"RECOVER: unreadable manifest {mf.name}: {e!r}")
            continue
        recs.append(rec)
        known.update(rec.files())
    loose: dict[str, dict] = {}
    for mkv in sorted(parts_dir.glob("*.mkv")):  # parts with no manifest
        if mkv not in known and "_" in mkv.stem:
            sid, kind = mkv.stem.rsplit("_", 1)
            if kind in ("screen", "camera"):
                loose.setdefault(sid, {})[kind] = mkv
    for sid, found in loose.items():
        rec = Recording(parts_dir, "screen" in found, "camera" in found, True, rid=sid)
        rec.segments.append({"id": sid, "offset": None, "screen": found.get("screen"), "camera": found.get("camera")})
        recs.append(rec)
    total, problems = 0.0, 0
    for rec in recs:
        if not any(p.exists() for p in rec.files()):
            rec.manifest.unlink(missing_ok=True)
            continue
        log.info(f"RECOVER {rec.id}: {len(rec.segments)} segment(s)")
        seconds, probs = rec.finalize(out_dir)
        total += seconds
        problems += len(probs)
    return len(recs), total, problems
