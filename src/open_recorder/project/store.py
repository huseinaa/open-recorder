"""A project on disk: <folder>/.openrecorder/ holds project.json, the chat, transcripts and
caches. The recordings themselves stay loose in the folder, where the recorder writes them."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from ..core import Project
from ..logs import log

META = ".openrecorder"


@dataclass(frozen=True)
class ProjectFiles:
    folder: Path

    @property
    def meta(self) -> Path:
        return self.folder / META

    @property
    def project(self) -> Path:
        return self.meta / "project.json"

    @property
    def cache(self) -> Path:
        return self.meta / "cache"

    @property
    def transcripts(self) -> Path:
        return self.meta / "transcripts"

    @property
    def chat(self) -> Path:
        return self.meta / "chat.json"

    @property
    def exports(self) -> Path:
        return self.folder / "Exports"


def is_project(folder: Path) -> bool:
    return ProjectFiles(Path(folder)).project.exists()


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def load(folder: Path, name: str | None = None) -> Project:
    """The project in this folder, or a new empty one named after the folder."""
    files = ProjectFiles(Path(folder))
    if files.project.exists():
        try:
            return Project.from_dict(json.loads(files.project.read_text(encoding="utf-8")))
        except (ValueError, OSError, TypeError, KeyError) as e:
            broken = files.project.with_suffix(".broken.json")
            log.warning(f"PROJECT {files.project} could not be read ({e!r}), kept as {broken.name}")
            try:
                os.replace(files.project, broken)
            except OSError:
                pass
    return Project(name=name or Path(folder).name or "Untitled")


def save(folder: Path, project: Project) -> None:
    _write_json(ProjectFiles(Path(folder)).project, project.to_dict())


def load_chat(folder: Path) -> list[dict]:
    path = ProjectFiles(Path(folder)).chat
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_chat(folder: Path, messages: list[dict]) -> None:
    _write_json(ProjectFiles(Path(folder)).chat, messages[-200:])
