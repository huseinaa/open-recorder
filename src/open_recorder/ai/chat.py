"""One chat turn: the request and the timeline go to the AI, its ops are checked and applied to a
copy of the project. If they do not apply, the AI is told why and gets one more try."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core import OpError, Project, apply
from ..logs import log
from .base import AIError
from .context import SYSTEM, build_prompt
from .router import Router
from .schema import ANSWER_SCHEMA


@dataclass
class Answer:
    reply: str
    project: Project | None          # the edited copy, None when nothing changed
    ops: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    provider: str = ""
    provider_note: str = ""
    before: float = 0.0
    after: float = 0.0


def order_cuts(ops: list[dict]) -> list[dict]:
    """Each run of rippling cut_range ops is applied latest first, so earlier times stay valid
    even when the AI listed them in reading order."""
    out, run = [], []

    def flush():
        out.extend(sorted(run, key=lambda o: -float(o.get("start") or 0)))
        run.clear()

    for o in ops:
        if o.get("op") == "cut_range" and o.get("ripple", True) is not False:
            run.append(o)
        else:
            flush()
            out.append(o)
    flush()
    return out


def ask(router: Router, project: Project, message: str, *, options: dict | None = None, **context) -> Answer:
    prompt = build_prompt(project, message, **context)
    answer, provider, note = router.run(SYSTEM, prompt, ANSWER_SCHEMA, options)
    for attempt in range(2):
        ops = order_cuts([o for o in answer.get("ops") or [] if isinstance(o, dict)])
        reply = str(answer.get("reply") or "").strip()
        if not ops:
            return Answer(reply or "Nothing to change.", None, provider=provider, provider_note=note,
                          before=project.duration, after=project.duration)
        try:
            edited, notes = apply(project, ops)
        except OpError as e:
            log.warning(f"AI ops did not apply ({e}): {ops}")
            if attempt == 1:
                raise AIError(f"The AI's edit could not be applied: {e}. Try asking another way.") from e
            retry = (f"{prompt}\n\nYOUR LAST ANSWER COULD NOT BE APPLIED: {e}\n"
                     "Fix it using only the ids listed above, and answer again.")
            answer, provider, note = router.run(SYSTEM, retry, ANSWER_SCHEMA, options)
            continue
        return Answer(reply, edited, ops, notes, provider, note, project.duration, edited.duration)
    raise AIError("The AI could not make that edit.")
