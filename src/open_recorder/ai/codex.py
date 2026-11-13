"""Codex (`codex exec`), on the user's own ChatGPT subscription."""
from __future__ import annotations

import json

from ..logs import log
from .base import (TIMEOUT_SECONDS, AIError, LimitReached, NotInstalled, NotSignedIn, Provider, Unavailable,
                   content_file, is_limit, resets_at, run_cli, unescape, workdir)
from .schema import prune, strict

EFFORTS = ("minimal", "low", "medium", "high", "xhigh")
DISABLED_FEATURES = ("shell_tool", "unified_exec", "multi_agent", "image_generation", "apps", "plugins",
                     "browser_use", "computer_use", "in_app_browser", "view_image", "hooks", "goals",
                     "skill_search", "tool_suggest", "sleep_tool")
AUTH_HINTS = ("401", "unauthorized", "not logged in", "log in again", "sign in again", "refresh token",
              "refresh_token", "token_expired", "invalid_grant", "please run codex login", "authentication")


def effort_for(effort: str) -> str:
    value = (effort or "").strip().lower()
    if value == "max":
        return "xhigh"
    return value if value in EFFORTS else "medium"


def events(stdout: str):
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            yield event


class Codex(Provider):
    name = "codex"
    label = "Codex"
    command = "codex"
    install_hint = "Install the Codex CLI, then sign in with your ChatGPT account."
    install_url = "https://developers.openai.com/codex/cli"
    login_hint = "Open a terminal, run codex login, and sign in with your ChatGPT account."
    api_credentials = ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL", "CODEX_ACCESS_TOKEN")

    def build(self, system: str, schema: dict, model: str = "", effort: str = "") -> list[str]:
        exe = self.binary()
        if not exe:
            raise NotInstalled(f"Codex is not installed. {self.install_hint}")
        schema_file = content_file("codex-schema", json.dumps(strict(schema), sort_keys=True), ".json")
        system_file = content_file("codex-system", system)
        cmd = [exe, "exec", "--json", "--skip-git-repo-check", "--sandbox", "read-only", "--ephemeral",
               "--ignore-rules", "--color", "never", "--output-schema", str(schema_file),
               "-c", f"model_instructions_file={json.dumps(str(system_file))}",
               "-c", 'web_search="disabled"',
               "-c", f'model_reasoning_effort="{effort_for(effort)}"',
               "-C", str(workdir())]
        for feature in DISABLED_FEATURES:
            cmd += ["--disable", feature]
        if model:
            cmd += ["-m", model]
        return cmd + ["-"]

    def run(self, system, prompt, schema, model="", effort="", timeout=TIMEOUT_SECONDS) -> dict:
        done = run_cli(self.build(system, schema, model, effort), prompt, self.environment(), timeout, "Codex")
        answer, failed, errors = None, None, []
        for event in events(done.stdout):
            kind = event.get("type")
            if kind == "item.completed" and (event.get("item") or {}).get("type") == "agent_message":
                answer = (event.get("item") or {}).get("text")
            elif kind == "turn.failed":
                failed = str((event.get("error") or {}).get("message") or "")
            elif kind == "error":
                errors.append(str(event.get("message") or ""))
            elif kind == "turn.completed":
                usage = event.get("usage") or {}
                log.info(f"AI codex: in {usage.get('input_tokens')} out {usage.get('output_tokens')}")
        if failed is not None or (done.returncode != 0 and answer is None):
            raise self.failure("\n".join([*errors[-2:], failed or "", done.stderr or ""]))
        try:
            output = json.loads(answer or "")
        except ValueError:
            raise self.failure("\n".join([*errors[-2:], done.stderr or "", "The answer was not structured."])) from None
        if not isinstance(output, dict):
            raise Unavailable("Codex answered in the wrong shape. Try again.")
        return unescape(prune(output, schema))

    def failure(self, text: str) -> AIError:
        lower = text.lower()
        if "usage_limit_reached" in lower or is_limit(lower):
            return LimitReached("Your ChatGPT plan has hit its Codex usage limit for now. Try again later.",
                                resets_at(text))
        if any(h in lower for h in AUTH_HINTS):
            return NotSignedIn(f"Codex is not signed in. {self.login_hint}")
        lines = [ln for ln in text.strip().splitlines() if ln.strip()]
        return Unavailable("Codex could not answer" + (f": {lines[-1][:300]}" if lines else "."))
