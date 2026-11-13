"""Undo and redo. Each entry is a whole project snapshot taken before a batch of ops, so one AI
answer that made twenty cuts comes back with one Ctrl+Z."""
from __future__ import annotations

import copy


class History:
    def __init__(self, limit: int = 100):
        self.limit = limit
        self._undo: list[tuple[str, dict]] = []
        self._redo: list[tuple[str, dict]] = []

    def push(self, before: dict, label: str) -> None:
        self._undo.append((label, copy.deepcopy(before)))
        if len(self._undo) > self.limit:
            self._undo.pop(0)
        self._redo.clear()

    def undo(self, current: dict) -> tuple[str, dict] | None:
        if not self._undo:
            return None
        label, before = self._undo.pop()
        self._redo.append((label, copy.deepcopy(current)))
        return label, before

    def redo(self, current: dict) -> tuple[str, dict] | None:
        if not self._redo:
            return None
        label, after = self._redo.pop()
        self._undo.append((label, copy.deepcopy(current)))
        return label, after

    def scrub(self, fix) -> None:
        """Change every saved step in place, for example to drop clips whose file was deleted,
        so no undo or redo can bring back something that no longer exists."""
        for stack in (self._undo, self._redo):
            for _, snapshot in stack:
                fix(snapshot)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def labels(self) -> tuple[str | None, str | None]:
        return (self._undo[-1][0] if self._undo else None), (self._redo[-1][0] if self._redo else None)
