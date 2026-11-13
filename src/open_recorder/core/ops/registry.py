"""The edit language. Every change to a project, from a click in the timeline or from the AI, is
an op: a dict like {"op": "split", "t": 12.5}. apply() runs a batch on a copy and returns the new
project, so a bad op in the middle of a batch leaves the original untouched."""
from __future__ import annotations

import inspect
from typing import Callable

from ..model import Project

OPS: dict[str, Callable] = {}


class OpError(ValueError):
    """An op that cannot be applied: unknown name, missing clip, impossible values."""


def op(name: str):
    def register(fn):
        OPS[name] = fn
        return fn
    return register


def describe() -> dict[str, list[str]]:
    """op name → its argument names, for the AI prompt and the docs."""
    return {name: [p for p in inspect.signature(fn).parameters if p != "p"] for name, fn in OPS.items()}


def apply(project: Project, ops: list[dict]) -> tuple[Project, list[str]]:
    p = Project.from_dict(project.to_dict())
    notes: list[str] = []
    for i, raw in enumerate(ops):
        if not isinstance(raw, dict) or "op" not in raw:
            raise OpError(f"op {i + 1} is not an object with an 'op' name")
        name = raw["op"]
        fn = OPS.get(name)
        if fn is None:
            raise OpError(f"unknown op '{name}'")
        args = {k: v for k, v in raw.items() if k != "op" and v is not None}
        allowed = set(inspect.signature(fn).parameters) - {"p"}
        unknown = set(args) - allowed
        if unknown:
            raise OpError(f"{name}: unknown argument(s) {', '.join(sorted(unknown))}")
        try:
            note = fn(p, **args)
        except OpError:
            raise
        except (TypeError, ValueError, KeyError) as e:
            raise OpError(f"{name}: {e}") from e
        if note:
            notes.append(note)
    return p, notes
