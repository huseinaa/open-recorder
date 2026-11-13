"""The AI that edits: Claude Code or Codex, run on the user's own subscription."""
from .base import AIError, LimitReached, NotInstalled, NotSignedIn, Provider, Status, Unavailable
from .chat import Answer, ask
from .claude import Claude
from .codex import Codex
from .router import Router

PROVIDERS = {"claude": Claude(), "codex": Codex()}

__all__ = ["AIError", "Answer", "Claude", "Codex", "LimitReached", "NotInstalled", "NotSignedIn", "PROVIDERS",
           "Provider", "Router", "Status", "Unavailable", "ask"]
