"""Which AI answers: the one the user put first, and the other one when the first is out of
usage, signed out or failing. A provider that hit its limit goes last until it resets."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..logs import log
from .base import AIError, LimitReached, NotInstalled, NotSignedIn, Provider, Unavailable

COOLDOWN = timedelta(minutes=30)


class Router:
    def __init__(self, providers: dict[str, Provider], primary: str = "claude", enabled: set[str] | None = None):
        self.providers = providers
        self.primary = primary if primary in providers else next(iter(providers))
        self.enabled = set(enabled) if enabled is not None else set(providers)
        self.limited_until: dict[str, datetime] = {}

    def order(self, now: datetime | None = None) -> list[str]:
        now = now or datetime.now(timezone.utc)
        names = [self.primary] + [n for n in self.providers if n != self.primary]
        names = [n for n in names if n in self.enabled]
        fresh = [n for n in names if self.limited_until.get(n, now) <= now]
        return fresh + [n for n in names if n not in fresh]

    def run(self, system: str, prompt: str, schema: dict, options: dict[str, dict] | None = None) -> tuple[dict, str, str]:
        """(answer, provider name, note). The note says why the second provider answered, if it did."""
        options = options or {}
        order = self.order()
        if not order:
            raise NotSignedIn("Connect Claude or Codex first.")
        reasons: list[tuple[str, AIError]] = []
        for name in order:
            provider = self.providers[name]
            try:
                answer = provider.run(system, prompt, schema, **options.get(name, {}))
            except LimitReached as e:
                self.limited_until[name] = e.resets_at or datetime.now(timezone.utc) + COOLDOWN
                reasons.append((name, e))
            except (NotInstalled, NotSignedIn, Unavailable) as e:
                reasons.append((name, e))
            else:
                self.limited_until.pop(name, None)
                note = ""
                if reasons:
                    first, why = reasons[0]
                    note = f"{self.providers[first].label} could not answer ({why}), so {provider.label} did."
                return answer, name, note
            log.warning(f"AI {name} failed: {reasons[-1][1]}")
        if all(isinstance(e, LimitReached) for _, e in reasons) and len(reasons) > 1:
            raise LimitReached("Claude and Codex have both hit their usage limits for now. Try again later.")
        raise reasons[0][1]
