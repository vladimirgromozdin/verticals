"""The check inside a source document (docs/design/sources.md): what it may say, its one hash, and the document that
carries it. Pure: no connection, no clock, no network. `core/sources.py` keeps the answers; `verticals/sources/` runs
the checks.

A source is a document under `sources/`. Its body has five plain sections and, in the one called "How it is checked",
a fenced block marked `check` written as JSON:

    ```check
    {"kind": "cmd", "where": "here", "argv": ["df", "-k", "/"], "parse": "(\\d+)%", "max": 90}
    ```

JSON because it is the plainest block to read, write and check. The app's editor sets a fenced block quietly, never edits
it and writes it back exactly as it was (`web/src/lib/bodyMarkdown.ts`), so a save of the words around it never changes
the check or its hash. The block is the only copy of the check; the table beside it keeps answers, never a second check.

Six kinds are the agent's: `http`, `mcp`, `cmd`, `file`, `dns` and `servers`. A seventh, `connections`, is written only
by the app. `servers` is for a source the morning report reads through Claude Code's own servers (a claude.ai connector, a
plugin): their sign-in is Claude Code's, so the app asks Claude Code whether they answer instead of calling them itself.
Any of the six may also say `reads`: the tools of the owner's other MCP servers that read this source for the morning report,
each as Claude Code names it (`mcp__chat__list_messages`). They sit in the block so the one Approve covers them: the hash
below changes with them, and the morning turn calls a source's tools only while that hash is the approved one.
Unknown fields are refused, so a typo cannot quietly drop a limit. Every kind the agent writes is gated: each reaches
something (an address, a server, a program, a file, a name resolver) and can carry something out or bring something in, so
each runs only once the owner has approved the exact check, which is the hash below (`Check.hash`). Only the app's own
`connections` check runs without it.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
import shlex
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from verticals.core.errors import ValidationError

PREFIX = "sources/"
KINDS = ("http", "mcp", "cmd", "file", "dns", "servers")
APP_KINDS = ("connections",)
# Every check the agent writes reaches something, even a name lookup (the name it is given goes to a resolver), so each runs
# only once the owner has approved the exact check (its hash). Only the app's own `connections` check runs without approval.
GATED = frozenset(KINDS)
# The kinds that read this Mac itself, so they always run here.
ON_THIS_MAC = frozenset({"cmd", "file", "servers"})
WHERES = ("here", "anywhere")

# The reading verbs the tool of an `mcp` check may start with, plus the words a health tool uses. The app calls that one
# tool every hour with no model and the owner approved it, so a name that reads is a safety net under the Approve. It is not
# how the morning turn judges a tool: that turn calls the tools a source's `reads` names and asks for any other.
READ_VERBS = frozenset({
    "get", "list", "search", "fetch", "read", "retrieve", "find", "query", "lookup", "show", "describe", "inspect",
    "whoami", "health", "status", "ping", "check",
})

SECTIONS: tuple[tuple[str, str], ...] = (
    ("gives", "What it gives the report"),
    ("how", "How to read it"),
    ("since", "Since when"),
    ("check", "How it is checked"),
    ("fixes", "Fixes the agent may make alone"),
)
NO_FIXES = "None. Anything else stays red."

MAX_URL = 2048
MAX_READS = 40
MAX_ARGV = 32
MAX_ARG = 2048
MAX_PATTERN = 300
MAX_SAY = 120
MAX_EXPECT = 20

# Per kind: the fields it takes (in the order a block is written), the ones it must have, and what an omitted one means.
_FIELDS: dict[str, tuple[str, ...]] = {
    "http": ("url", "status", "expect", "value", "min", "max", "say", "timeout", "reads"),
    "mcp": ("url", "tool", "args", "expect", "value", "min", "max", "say", "timeout", "reads"),
    "cmd": ("argv", "exit", "parse", "min", "max", "say", "timeout", "reads"),
    "file": ("path", "max_age_hours", "last_line", "reads"),
    "dns": ("host", "reads"),
    "servers": ("reads",),
    "connections": (),
}
_REQUIRED = {"http": ("url",), "mcp": ("url", "tool"), "cmd": ("argv",), "file": ("path",), "dns": ("host",),
             "servers": ("reads",), "connections": ()}
_DEFAULTS: dict[str, dict[str, Any]] = {
    "http": {"status": 200, "timeout": 10},
    "mcp": {"args": {}, "timeout": 15},
    "cmd": {"exit": 0, "timeout": 20},
    "file": {},
    "dns": {},
    "servers": {},
    "connections": {},
}
_MAX_TIMEOUT = {"http": 30, "mcp": 30, "cmd": 60}
_HOST_RE = re.compile(r"^[A-Za-z0-9._:\-\[\]]{1,253}$")
# A tool as Claude Code names it, `mcp__<server>__<tool>`: what the morning turn is allowed to call (`reads` below). The
# server's name has no double underscore in it, so the first `__` after the prefix ends it.
_TOOL_RE = re.compile(r"^mcp__([A-Za-z0-9][A-Za-z0-9_.\-]{0,80}?)__([A-Za-z0-9][A-Za-z0-9_.\-]{0,120})$")
# Verticals itself is never a source of its own report: a tool of this server named here would be a write allowed by the
# line of a document, past the owner's Approve of the tools it names. The gateway refuses it again when it reads them.
_OWN_SERVERS = ("verticals",)


def _bad(field: str, message: str) -> ValidationError:
    return ValidationError(f"check: {message}", field=f"check.{field}")


def _control(text: str) -> bool:
    return any(ord(ch) < 0x20 or 0x7F <= ord(ch) <= 0x9F for ch in text)


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _tidy(value: float) -> int | float:
    """A whole number stays an int, so `20` and `20.0` are one check."""
    return int(value) if isinstance(value, float) and value.is_integer() else value


def reads_only(tool: str) -> bool:
    """A tool name that starts with a reading verb: `get_status`, `list-events`, `searchThreads`."""
    first = re.split(r"[-_]|(?<=[a-z])(?=[A-Z])", tool)[0].lower()
    return first in READ_VERBS


def reading_tools(raw: object) -> list[str]:
    """The tools a source names for reading it in the morning, checked: a list of Claude Code's tool names, each once, none
    of Verticals' own (a source cannot hand the morning turn a write of the board)."""
    if not isinstance(raw, list) or not raw or len(raw) > MAX_READS:
        raise _bad("reads", f"reads must be a list of 1 to {MAX_READS} tools, each written mcp__<server>__<tool>")
    tools: list[str] = []
    for tool in raw:
        found = _TOOL_RE.match(tool) if isinstance(tool, str) else None
        if found is None:
            raise _bad("reads", f"{tool!r} is not a tool written mcp__<server>__<tool>")
        if found.group(1).lower().startswith(_OWN_SERVERS):
            raise _bad("reads", f"{tool!r} is a tool of Verticals itself: a source names the tools of other servers")
        if tool not in tools:
            tools.append(tool)
    return tools


def reading_servers(tools: Iterable[str]) -> frozenset[str]:
    """The servers a list of `mcp__<server>__<tool>` names reaches, each written as in those names."""
    return frozenset(found.group(1) for tool in tools if (found := _TOOL_RE.match(tool)))


def is_source_path(path: str) -> bool:
    return path.startswith(PREFIX) and path.endswith(".md")


def is_local_host(host: str) -> bool:
    """An address that only this Mac or its own network can reach: such a check must run here, never from a cloud."""
    name = host.lower().strip("[]")
    if name == "localhost" or name.endswith((".localhost", ".local", ".lan", ".internal")):
        return True
    try:
        return not ipaddress.ip_address(name).is_global
    except ValueError:
        return "." not in name


def _text(raw: Mapping[str, Any], field: str, *, limit: int) -> str:
    value = raw[field]
    if not isinstance(value, str) or not value.strip():
        raise _bad(field, f"{field} must be a non-empty string")
    if len(value) > limit:
        raise _bad(field, f"{field} must be at most {limit} characters")
    if _control(value):
        raise _bad(field, f"{field} must carry no control characters")
    return value


def _url(raw: Mapping[str, Any]) -> str:
    value = _text(raw, "url", limit=MAX_URL)
    if re.search(r"\s", value):
        raise _bad("url", "url must carry no spaces")
    try:
        parts = urlsplit(value)
    except ValueError:  # an unclosed or bad `[...]` host
        raise _bad("url", "url has an invalid host") from None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise _bad("url", "url must start with http:// or https:// and name a host")
    if parts.username is not None or parts.password is not None:
        raise _bad("url", "url must not carry a user name or password: a document is not a place for secrets")
    try:
        parts.port  # noqa: B018 - reading it validates it
    except ValueError:
        raise _bad("url", "url has an invalid port") from None
    return value


def _pattern(raw: Mapping[str, Any], field: str, *, groups: bool) -> str:
    value = _text(raw, field, limit=MAX_PATTERN)
    try:
        compiled = re.compile(value, re.MULTILINE)
    except re.error as exc:
        raise _bad(field, f"{field} is not a valid pattern: {exc}") from None
    if groups and compiled.groups < 1:
        raise _bad(field, f"{field} must have one group in brackets around the number to read")
    return value


def _normalise(kind: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    allowed = _FIELDS[kind]
    unknown = sorted(set(raw) - {"kind", "where", *allowed})
    if unknown:
        raise _bad(unknown[0], f"{kind} takes no field {unknown[0]!r} (it takes: {', '.join(allowed) or 'none'})")
    for name in _REQUIRED[kind]:
        if name not in raw:
            raise _bad(name, f"{kind} needs {name}")
    out: dict[str, Any] = {}

    if "url" in raw:
        out["url"] = _url(raw)
    if "tool" in raw:
        tool = _text(raw, "tool", limit=200)
        if not reads_only(tool):
            raise _bad("tool", f"tool {tool!r} is not a reading tool: its name must start with one of "
                               f"{', '.join(sorted(READ_VERBS))}")
        out["tool"] = tool
    if "args" in raw:
        if not isinstance(raw["args"], dict):
            raise _bad("args", "args must be an object")
        out["args"] = raw["args"]
    if "argv" in raw:
        argv = raw["argv"]
        if not isinstance(argv, list) or not argv or len(argv) > MAX_ARGV:
            raise _bad("argv", f"argv must be a list of 1 to {MAX_ARGV} words: a command and its arguments, never a "
                               "shell line")
        for word in argv:
            if not isinstance(word, str) or len(word) > MAX_ARG or "\x00" in word:
                raise _bad("argv", f"every word of argv must be a string of at most {MAX_ARG} characters")
        if not argv[0].strip():
            raise _bad("argv", "the first word of argv must name the command")
        out["argv"] = list(argv)
    if "path" in raw:
        path = _text(raw, "path", limit=1024)
        if not (path.startswith("~/") or path.startswith("/")):
            raise _bad("path", "path must start with ~/ or /")
        out["path"] = path
    if "host" in raw:
        host = _text(raw, "host", limit=253)
        if not _HOST_RE.match(host):
            raise _bad("host", "host must be a name or an address, with no scheme and no path")
        out["host"] = host
    if "status" in raw:
        status = raw["status"]
        if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
            raise _bad("status", "status must be an HTTP status code")
        out["status"] = status
    if "exit" in raw:
        code = raw["exit"]
        if isinstance(code, bool) or not isinstance(code, int) or not 0 <= code <= 255:
            raise _bad("exit", "exit must be an exit code, 0 to 255")
        out["exit"] = code
    if "expect" in raw:
        expect = raw["expect"]
        if not isinstance(expect, dict) or len(expect) > MAX_EXPECT:
            raise _bad("expect", f"expect must be an object of at most {MAX_EXPECT} fields, each a path and the value it must have")
        for path, want in expect.items():
            if not isinstance(path, str) or not path or len(path) > 200 or _control(path):
                raise _bad("expect", "every path in expect must be a short string")
            if want is not None and not isinstance(want, (str, int, float, bool)):
                raise _bad("expect", f"the value wanted at {path!r} must be a string, a number, true, false or null")
        out["expect"] = dict(expect)
    if "value" in raw:
        out["value"] = _text(raw, "value", limit=200)
    if "parse" in raw:
        out["parse"] = _pattern(raw, "parse", groups=True)
    if "last_line" in raw:
        out["last_line"] = _pattern(raw, "last_line", groups=False)
    for name in ("min", "max"):
        if name in raw:
            if not _number(raw[name]):
                raise _bad(name, f"{name} must be a number")
            out[name] = _tidy(raw[name])
    if "min" in out and "max" in out and out["min"] > out["max"]:
        raise _bad("min", "min must not be above max")
    if ("min" in out or "max" in out or "say" in raw) and "value" not in out and "parse" not in out:
        raise _bad("min" if "min" in out else "max" if "max" in out else "say",
                   "min, max and say need a value to read (value for http and mcp, parse for cmd)")
    if "say" in raw:
        out["say"] = _text(raw, "say", limit=MAX_SAY)
    if "max_age_hours" in raw:
        hours = raw["max_age_hours"]
        if not _number(hours) or not 0 < hours <= 24 * 365:
            raise _bad("max_age_hours", "max_age_hours must be a number of hours above 0")
        out["max_age_hours"] = _tidy(hours)
    if "reads" in raw:
        out["reads"] = reading_tools(raw["reads"])
    if "timeout" in raw:
        seconds = raw["timeout"]
        if not _number(seconds) or not 0 < seconds <= _MAX_TIMEOUT[kind]:
            raise _bad("timeout", f"timeout must be above 0 and at most {_MAX_TIMEOUT[kind]} seconds")
        out["timeout"] = _tidy(seconds)

    for name, default in _DEFAULTS[kind].items():
        out.setdefault(name, default)
    return {name: out[name] for name in allowed if name in out}


def _default_where(kind: str, fields: Mapping[str, Any]) -> str:
    if kind in ON_THIS_MAC or kind in APP_KINDS:
        return "here"
    if kind in ("http", "mcp"):
        return "here" if is_local_host(urlsplit(fields["url"]).hostname or "") else "anywhere"
    return "anywhere"


@dataclass(frozen=True)
class Check:
    """One check, every default filled in. `fields` is JSON-able and owned by the check: nothing mutates it."""

    kind: str
    where: str
    fields: Mapping[str, Any]

    @classmethod
    def from_dict(cls, raw: object, *, app: bool = False) -> Check:
        """Validate what a block says. `app=True` lets the app's own kind through; an agent never gets it."""
        if not isinstance(raw, dict):
            raise ValidationError("check: the block must be one JSON object", field="check")
        kind = raw.get("kind")
        if kind not in KINDS and not (app and kind in APP_KINDS):
            raise _bad("kind", f"kind must be one of {', '.join(KINDS)}")
        fields = _normalise(kind, raw)
        where = raw.get("where", _default_where(kind, fields))
        if where not in WHERES:
            raise _bad("where", "where must be here or anywhere")
        if where == "anywhere" and _default_where(kind, fields) == "here":
            raise _bad("where", f"this {kind} check reads something only this Mac can reach, so it must run here")
        return cls(kind=kind, where=where, fields=fields)

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "where": self.where, **self.fields}

    @property
    def gated(self) -> bool:
        return self.kind in GATED

    @property
    def hash(self) -> str:
        """The check as the owner approves it: every default filled in, keys sorted, so spacing and key order never
        change it and any real change always does."""
        canonical = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def summary(self) -> str:
        """What the check does, in the words the owner reads before approving it, then the tools the morning report may
        call to read the source, each server once."""
        said = self._what()
        tools = self.fields.get("reads") or []
        if not tools:
            return said
        servers: dict[str, list[str]] = {}
        for tool in tools:
            found = _TOOL_RE.match(tool)
            servers.setdefault(found.group(1), []).append(found.group(2))
        return said + " The morning report may call " + "; ".join(f"{_and(names)} on {name}" for name, names in servers.items()) + "."

    def _what(self) -> str:
        f = self.fields
        wants: list[str] = []
        if self.kind == "http":
            wants.append(f"HTTP {f['status']}")
        elif self.kind == "cmd":
            wants.append(f"exit code {f['exit']}")
        if "value" in f or "parse" in f:
            low, high = f.get("min"), f.get("max")
            if low is not None and high is not None:
                wants.append(f"a number between {low} and {high}")
            elif high is not None:
                wants.append(f"a number of at most {high}")
            elif low is not None:
                wants.append(f"a number of at least {low}")
        for path, want in f.get("expect", {}).items():
            wants.append(f"{path} to be {json.dumps(want, ensure_ascii=False)}")
        if self.kind == "file":
            if "max_age_hours" in f:
                wants.append(f"it changed within the last {f['max_age_hours']} hours")
            if "last_line" in f:
                wants.append(f"a last line that matches {f['last_line']}")
        wanted = _and(wants)
        if self.kind == "http":
            return f"Asks {f['url']} every hour and wants {wanted}."
        if self.kind == "mcp":
            sent = f" with {json.dumps(f['args'], ensure_ascii=False)}" if f.get("args") else ""
            return f"Calls the tool {f['tool']} of {f['url']}{sent} every hour" + (f" and wants {wanted}" if wants else "") + "."
        if self.kind == "cmd":
            return f"Runs {shlex.join(f['argv'])} on this Mac every hour and wants {wanted}."
        if self.kind == "file":
            return f"Reads {f['path']} on this Mac every hour" + (f" and wants {wanted}" if wants else " and wants it to exist") + "."
        if self.kind == "dns":
            return f"Looks up {f['host']} every hour and wants it to resolve."
        if self.kind == "servers":
            names = sorted(reading_servers(f["reads"]))
            return f"Asks Claude Code every hour whether {_and(names)} {'answers' if len(names) == 1 else 'answer'}."
        return "Asks Claude Code every hour which of the MCP servers the morning report reads answer."


def _and(items: Sequence[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


# --- the block in the document ---------------------------------------------------------------------------------------

_BLOCK = re.compile(r"^```check[ \t]*\r?\n(?P<json>.*?)\r?\n[ \t]*```[ \t]*$", re.DOTALL | re.MULTILINE)


def render_block(check: Check) -> str:
    return "```check\n" + json.dumps(check.as_dict(), indent=2, ensure_ascii=False) + "\n```"


def parse_check(body: str, *, app: bool = False) -> Check:
    """The check a document says. Raises `ValidationError` (field `check`) saying why there is none or why it cannot be
    read; the first `check` block wins."""
    match = _BLOCK.search(body or "")
    if match is None:
        raise ValidationError("check: the document has no ```check block yet", field="check", missing=True)
    text = match.group("json").replace(" ", " ")
    try:
        raw = json.loads(text)
    except ValueError as exc:
        raise ValidationError(f"check: the block is not valid JSON ({exc})", field="check") from None
    return Check.from_dict(raw, app=app)


# --- the sections around it ------------------------------------------------------------------------------------------

_HEADING = re.compile(r"^#{1,2} ")


def fixes_text(fixes: Sequence[str]) -> str:
    """The fixes the agent may make alone, one bullet each; none is said in words."""
    kept = [fix.strip() for fix in fixes if fix.strip()]
    return "\n".join(f"- {fix}" for fix in kept) if kept else NO_FIXES


def build_body(*, gives: str, how: str, since: str, check: Check, fixes: Sequence[str] = ()) -> str:
    """A new source document: the five sections in their order. The title is the document's own, not repeated here."""
    parts = {"gives": gives.strip(), "how": how.strip(), "since": since.strip(), "check": render_block(check),
             "fixes": fixes_text(fixes)}
    return "\n\n".join(f"## {heading}\n{parts[key]}" for key, heading in SECTIONS) + "\n"


def set_section(body: str, key: str, text: str) -> str:
    """Replace one section's text and leave the rest of the document as the owner left it. A section that is gone is
    added at the end."""
    heading = dict(SECTIONS)[key]
    lines = (body or "").split("\n")
    start = next((i for i, line in enumerate(lines) if line.strip() == f"## {heading}"), None)
    new = [f"## {heading}", *text.strip().split("\n"), ""]
    if start is None:
        kept = lines[:-1] if lines and lines[-1] == "" else lines
        return "\n".join([*kept, *([""] if kept else []), *new])
    end = next((i for i in range(start + 1, len(lines)) if _HEADING.match(lines[i])), len(lines))
    return "\n".join([*lines[:start], *new, *lines[end:]]).rstrip("\n") + "\n"


def section_text(body: str, key: str) -> str | None:
    heading = dict(SECTIONS)[key]
    lines = (body or "").split("\n")
    start = next((i for i, line in enumerate(lines) if line.strip() == f"## {heading}"), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if _HEADING.match(lines[i])), len(lines))
    return "\n".join(lines[start + 1:end]).strip()


def slug(title: str) -> str:
    """A file name for a title: letters and digits joined by hyphens; `source` when nothing is left."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60].strip("-") or "source"
