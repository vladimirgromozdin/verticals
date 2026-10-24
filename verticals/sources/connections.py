"""Which of the agent's MCP servers answer (docs/design/sources.md, "Every connection too"): the app runs
`claude mcp list` with no model and reads one line per server. The document called Connections holds the check
(`{"kind": "connections"}`, written only by the app); this module is what runs it.

The format is the CLI's own (read from its code, version 2.1.282, and from real output):

    Checking MCP server health…

    name: https://host/mcp (HTTP) - ✓ Connected
    name: npx -y some-server - ✓ Connected
    name: https://host/mcp (HTTP) - ! Needs authentication
    name: https://host/mcp (HTTP) - ✗ Failed to connect
    name: .mcp.json server - ⏸ Pending approval (run `claude` to approve)

Read by the words after the last " - ", never by the glyph in front of them: the CLI has drawn the check mark two ways.
A server that fails to connect, needs sign-in or has a tool list that failed counts against the source; a server that is
disabled, rejected or waiting for approval is not in use and does not.

Only the servers the morning report reads count (`only`, as the sources' `reads` write them): a server the report never
calls says nothing about the report. A server it reads counts even when it is off or missing from the list, since the
report cannot read it then. A `servers` check asks the same about the servers of its own source; one pass of the timer
asks the CLI once for all of them (`listed`).

**Codex has no equivalent.** Its documented `mcp list` shows which servers are configured, enabled and signed in, not
whether one answers, so there is nothing to ask it. Only `claude` is asked.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from verticals.core.sources import Result
from verticals.sources.runner import CLAUDE_ENV, clean_env, find_exe, run_argv, search_path, shown

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
SECONDS = 90.0  # a health check starts every stdio server the CLI knows
LABEL = {"failed": "failed to connect", "sign_in": "needs sign-in", "missing": "not set up in Claude Code"}
UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


@dataclass(frozen=True)
class Server:
    name: str
    state: str   # answers, failed, sign_in, off, missing or unknown
    status: str  # the words the CLI used


def tool_name(server: str) -> str:
    """A server's name as Claude Code writes it inside its tools' names: `claude.ai Gmail` is `claude_ai_Gmail`."""
    return UNSAFE.sub("_", server)


def classify(status: str) -> str:
    low = status.lower()
    if "needs authentication" in low:
        return "sign_in"
    if "failed to connect" in low or "connection error" in low or "fetch failed" in low:
        return "failed"
    if any(word in low for word in ("pending approval", "disabled", "rejected", "not configured")):
        return "off"
    if re.search(r"(?<![a-z])connected", low):
        return "answers"
    return "unknown"


def parse(text: str) -> list[Server]:
    """One `Server` for each line of the CLI's list that has a name, a target and a status."""
    servers = []
    for line in re.split(r"\r\n|\r|\n", ANSI.sub("", text)):
        line = line.strip()
        head, _, status = line.rpartition(" - ")
        name, _, target = head.partition(": ")
        if name and target and status.strip():
            servers.append(Server(name=name.strip(), state=classify(status), status=status.strip()))
    return servers


def check(
    agents: Sequence[str],
    *,
    home: Path,
    stop: threading.Event,
    environ: Mapping[str, str],
    path: str | None = None,
    only: Collection[str] | None = None,
    listed: dict | None = None,
) -> Result:
    """Ask each agent in `agents` which of its servers answer; today that is `claude`. `only` narrows the answer to those
    servers, written as in tool names; None is every server in use."""
    if "claude" not in agents:
        return Result(False, "no agent is set up to ask")
    if only is not None and not only:
        return Result(True, "the morning report reads no MCP server", value=0)
    exe = find_exe("claude", home=home, path=path if path is not None else environ.get("PATH"))
    if exe is None:
        return Result(False, "Claude Code was not found on this Mac")
    if listed is not None and "run" in listed:
        code, output, why = listed["run"]
    else:
        env = clean_env(environ, home, also=CLAUDE_ENV)
        if path is not None:
            env["PATH"] = search_path(path, home)
        code, output, why = run_argv([exe, "mcp", "list"], env=env, cwd=home, seconds=SECONDS, stop=stop)
        if listed is not None and why != "stopped":
            listed["run"] = (code, output, why)
    raw = shown(output)
    if why is not None:
        return Result(False, f"claude mcp list: {why}", raw=raw)
    if code != 0:
        return Result(False, f"claude mcp list exited with code {code}", raw=raw)
    found = parse(output)
    none_set_up = "No MCP servers configured" in output or not output.strip()
    if only is not None:
        if not found and not none_set_up:
            return Result(False, "could not read the list from claude", raw=raw)
        named = {tool_name(s.name): s for s in found}
        servers = [named.get(name) or Server(name=name, state="missing", status="") for name in sorted(only)]
    else:
        servers = [s for s in found if s.state != "off"]
    if not servers:
        if none_set_up:
            return Result(True, "no MCP servers are set up", value=0, raw=raw)
        if not found:
            return Result(False, "could not read the list from claude", raw=raw)
        return Result(True, "no MCP server is in use", value=0, raw=raw)
    answering = [s for s in servers if s.state == "answers"]
    down = [s for s in servers if s.state != "answers"]
    # The names of the servers that answer are in the line: the Inbox tells the owner, while they have no source yet, which
    # servers the agent reaches, and the agent reads the same line.
    reached = ", ".join(s.name for s in answering)
    if len(servers) == 1:
        one = servers[0]
        said = "answers" if not down else f"does not answer ({LABEL.get(one.state, shown(one.status, 30))})"
        return Result(not down, f"{one.name} {said}", value=float(len(answering)), raw=raw)
    if not down:
        return Result(True, f"all {len(servers)} answer: {reached}", value=float(len(answering)), raw=raw)
    names = ", ".join(f"{s.name} ({LABEL.get(s.state, shown(s.status, 30))})" for s in down)
    head = f"{len(answering)} of {len(servers)} answer" + (f": {reached}" if reached else "")
    return Result(False, f"{head}; not answering: {names}", value=float(len(answering)), raw=raw)
