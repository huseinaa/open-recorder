"""The root folder chosen on first launch: "Record now" saves straight into it, and every project
is a named subfolder of it."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .scan import media_files
from .store import META, is_project, load, save

INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
QUICK_NAME = "Quick takes"


def safe_name(name: str) -> str:
    """A name Windows accepts as a folder: no forbidden characters, no trailing dot or space."""
    clean = INVALID.sub("", name or "").strip().rstrip(". ")
    clean = re.sub(r"\s+", " ", clean)[:80]
    if not clean or clean.upper() in RESERVED:
        clean = f"Project {datetime.now():%Y-%m-%d %H%M}"
    return clean


class Library:
    def __init__(self, root: Path):
        self.root = Path(root)

    def create(self, name: str, aspect: str = "16:9") -> Path:
        """Make <root>/<name>, adding (2), (3)… when the name is taken."""
        base = safe_name(name)
        folder, n = self.root / base, 2
        while folder.exists():
            folder, n = self.root / f"{base} ({n})", n + 1
        folder.mkdir(parents=True)
        project = load(folder, name=folder.name)
        project.sequence.aspect = aspect
        save(folder, project)
        return folder

    def quick(self) -> Path:
        """The root itself, opened as a project for takes made with Record now."""
        if not is_project(self.root):
            project = load(self.root, name=QUICK_NAME)
            project.name = QUICK_NAME
            save(self.root, project)
        return self.root

    def _guard(self, folder: Path) -> Path:
        """Only real projects, and never the root itself (that is Quick takes, your recordings)."""
        folder = Path(folder).resolve()
        if folder == self.root.resolve():
            raise ValueError("Quick takes is your recordings folder, so it can't be renamed or deleted here")
        if not is_project(folder):
            raise ValueError("That folder is not an Open Recorder project")
        return folder

    def rename(self, folder: Path, name: str) -> Path:
        """Rename the project's folder (it stays where it is) and the name saved in it."""
        folder = self._guard(folder)
        target = folder.with_name(safe_name(name))
        if target == folder:
            return folder
        if target.exists() and target.resolve() != folder:
            raise ValueError(f'There is already a folder called "{target.name}" there')
        try:
            folder.rename(target)  # a change of capitals only is fine on Windows too
        except PermissionError:
            raise ValueError("Windows says a file in this project is in use. Close it and try again") from None
        project = load(target)
        project.name = target.name
        save(target, project)
        return target

    def delete(self, folder: Path) -> None:
        """Send the project's folder, takes and all, to the Recycle Bin."""
        from ..win32 import recycle
        folder = self._guard(folder)
        try:
            recycle(folder)
        except OSError:
            raise ValueError("Windows could not move it to the Recycle Bin. "
                             "A file in it may be open somewhere, close it and try again") from None

    def projects(self, extra: list[str] | None = None) -> list[dict]:
        """Projects in the root (and any opened from elsewhere), newest first."""
        found: dict[str, dict] = {}
        candidates = [p for p in self.root.iterdir() if p.is_dir() and p.name != META] if self.root.exists() else []
        candidates += [Path(e) for e in (extra or [])]
        for folder in candidates:
            if folder.exists() and is_project(folder):
                found[str(folder.resolve())] = _summary(folder)
        if self.root.exists() and (is_project(self.root) or media_files(self.root)):
            found[str(self.root.resolve())] = {**_summary(self.root), "name": QUICK_NAME, "quick": True}
        return sorted(found.values(), key=lambda s: s["modified"], reverse=True)


def _summary(folder: Path) -> dict:
    project_file = folder / META / "project.json"
    stamps = [project_file.stat().st_mtime] if project_file.exists() else []
    takes = media_files(folder)
    stamps += [p.stat().st_mtime for p in takes[-5:]]
    modified = max(stamps, default=folder.stat().st_mtime)
    poster = next((p for p in reversed(takes) if p.name.lower().startswith("screen_")), None) or \
        next((p for p in reversed(takes) if p.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm")), None)
    return {"name": folder.name, "path": str(folder.resolve()), "modified": modified,
            "takes": sum(1 for p in takes if not p.name.lower().startswith("camera_")),
            "poster_source": str(poster) if poster else ""}
