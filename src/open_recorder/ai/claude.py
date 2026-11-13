"""Claude Code (`claude -p`), on the user's own Claude subscription."""
from __future__ import annotations

import json

from ..logs import log
from .base import (TIMEOUT_SECONDS, AIError, LimitReached, NotInstalled, NotSignedIn, Provider, Unavailable,
                   content_file, is_limit, resets_at, run_cli, unescape)

AUTH_HINTS = ("/login", "not logged in", "invalid api key", "invalid bearer", "authentication", "oauth",
              "please run claude login")


class Claude(Provider):
    name = "claude"
    label = "Claude"
    command = "claude"
    install_hint = "Install Claude Code, then sign in with your Claude account."
    install_url = "https://docs.claude.com/en/docs/claude-code/setup"
    login_hint = "Open a terminal, run claude, and sign in with your Claude account."
    api_credentials = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

    def build(self, system: str, schema: dict, model: str = "", effort: str = "") -> list[str]:
        exe = self.binary()
        if not exe:
            raise NotInstalled(f"Claude Code is not installed. {self.install_hint}")
        cmd = [exe, "-p", "--output-format", "json", "--json-schema", json.dumps(schema),
               "--system-prompt-file", str(content_file("claude-system", system)),
               # text in, structured text out: no tools, no MCP servers, no skills, nothing saved
               "--tools", "", "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"]
        if model:
            cmd += ["--model", model]
        if effort:
            cmd += ["--effort", effort]
        return cmd

    def run(self, system, prompt, schema, model="", effort="", timeout=TIMEOUT_SECONDS) -> dict:
        done = run_cli(self.build(system, schema, model, effort), prompt, self.environment(), timeout, "Claude")
        try:
            result = json.loads(done.stdout)
        except ValueError:
            raise self.failure(done.stdout, done.stderr) from None
        output = result.get("structured_output") if isinstance(result, dict) else None
        if done.returncode != 0 or result.get("is_error") or not isinstance(output, dict):
            raise self.failure(str(result.get("result") or ""), done.stderr)
        usage = result.get("usage") or {}
        log.info(f"AI claude: in {usage.get('input_tokens')} out {usage.get('output_tokens')}")
        return unescape(output)

    def failure(self, stdout: str, stderr: str) -> AIError:
        raw = f"{stdout}\n{stderr}"
        text = raw.lower()
        if is_limit(text):  # first: a limit message can mention the account it belongs to
            return LimitReached("Your Claude plan has hit its usage limit for now. Try again later.", resets_at(raw))
        if any(h in text for h in AUTH_HINTS):
            return NotSignedIn(f"Claude Code is not signed in. {self.login_hint}")
        detail = (stderr or stdout).strip().splitlines()
        return Unavailable("Claude could not answer" + (f": {detail[-1][:300]}" if detail else "."))
