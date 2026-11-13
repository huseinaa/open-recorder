"""The edit language: apply(project, [{"op": ...}, ...]) → (new project, notes).

Importing this package registers every op."""
from . import adding, edits, lanes, layers  # noqa: F401  (each module registers its ops)
from .registry import OPS, OpError, apply, describe

__all__ = ["OPS", "OpError", "apply", "describe"]
