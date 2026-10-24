"""Running a check (docs/design/sources.md): every kind, each read-only, none of them with a model.

`core/source_checks.py` says what a check may be; `core/sources.py` keeps the answers. This module is the only code that
reaches out: an address, an MCP tool, a command, a file, a host name. It lives beside `core/`, not in it, because `core/`
may not import the MCP client (`tests/static/test_seam.py`).

Every run answers a `Result`: passed or not, one printable line of why, the number worth showing, the milliseconds, and the
raw output the check saw (the command's own words, the page's first lines) for the agent's run-once to put beside the
number. A check that cannot run is a check that failed: "no answer", never an exception.

How a run is held in:

  * **A deadline.** Each run happens in its own daemon thread and is abandoned when its time is up, so a stuck name lookup
    cannot hold the timer or the shutdown. No database connection is held while a check runs (the caller's business).
  * **A command is an argv list**, never a shell line, run in the home folder with a cleaned environment (the PATH the app
    gives its agents, HOME, locale): `VERTICALS_TOKEN` and the database address never reach it. It runs in a process
    group of its own, which is killed, and waited for, at the deadline, when the output runs over, and on shutdown: the
    stop reaches the command in a tenth of a second, `run_check` does not return until it is gone, and `kill_live` is the
    net under that for any group still standing when the app closes.
  * **A file is read only under the home folder**, symlinks resolved first, and only a regular file; its last line only.
  * **An address is asked with GET**, no redirects, no cookies, 1 MB of answer at most.
  * **An MCP check calls one tool**, over streamable HTTP, whose name starts with a reading verb
    (`core/source_checks.py::reads_only`).
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Collection, Mapping, Sequence
from http.client import HTTPConnection, HTTPSConnection
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from verticals import host
from verticals.core.source_checks import Check, reading_servers
from verticals.core.sources import Result, one_line

MAX_OUTPUT = 256 * 1024     # what a command may print before it is stopped
MAX_BODY = 1024 * 1024      # what an address may answer with
RAW = 2000                  # how much of what a check saw goes back to the agent
GRACE = 2                   # seconds past a check's own timeout before its thread is given up on
STOP_GRACE = 3.0            # how long a stop waits for a running command's group to be killed and reaped
POLL = 0.1                  # how often a running command is asked whether the app is closing
FILE_TAIL = 8192

# Where the app's agents find their programs: `desktop/chat/chat.py::child_env` adds these three after the PATH it was
# given, because an app opened from the Dock has a short PATH. The same three here, so `claude` is found the same way.
EXTRA_PATH = (".local/bin", "/opt/homebrew/bin", "/usr/local/bin")
# What a command is given from the app's environment. Nothing else: the app's own token and database address stay out.
KEEP_ENV = ("HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", *host.KEEP_ENV)
# What `claude` is also given, to keep the owner's sign-in (the same list as `chat.py::ENV_KEEP`).
CLAUDE_ENV = ("CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
              "CLAUDE_CODE_USE_FOUNDRY")


def num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.2f}".rstrip("0").rstrip(".")


def shown(text: str, limit: int = RAW) -> str:
    """What a check saw, cut for the agent: printable, at most `limit` characters."""
    clean = "".join(ch if ch.isprintable() or ch in "\n\t" else " " for ch in text)
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"


def dig(data: Any, path: str) -> Any:
    """`a.b.0.c` in a JSON answer: keys of objects and indexes of lists; nothing found is None."""
    for part in path.split("."):
        if isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        elif isinstance(data, dict):
            data = data.get(part)
        else:
            return None
    return data


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        try:
            found = float(value.strip().replace(",", "."))
        except ValueError:
            return None
        return found if math.isfinite(found) else None
    return None


def _within(value: float, fields: Mapping[str, Any]) -> str | None:
    """Why a number is outside its limits, or None."""
    if "min" in fields and value < fields["min"]:
        return f"under the limit {num(fields['min'])}"
    if "max" in fields and value > fields["max"]:
        return f"over the limit {num(fields['max'])}"
    return None


def _words(fields: Mapping[str, Any], value: float | None, plain: str, problem: str | None = None) -> str:
    """The line an answer says: the check's own sentence (`say`, with {v} for the number) when it has one, and when the
    number is outside its limits, which limit, so a failing line never hides why it fails."""
    if value is not None and "say" in fields:
        return fields["say"].replace("{v}", num(value)) + (f", {problem}" if problem else "")
    return plain


# --- the environment a command runs in ------------------------------------------------------------------------------


def search_path(base: str | None, home: Path) -> str:
    """The PATH given, then the three places the app's agents also look."""
    parts = [p for p in (base or "").split(os.pathsep) if p]
    for extra in EXTRA_PATH:
        full = str(home / extra) if not extra.startswith("/") else extra
        if full not in parts:
            parts.append(full)
    return os.pathsep.join(parts)


def clean_env(base: Mapping[str, str], home: Path, *, also: Sequence[str] = ()) -> dict[str, str]:
    env = {k: base[k] for k in (*KEEP_ENV, *also) if k in base}
    env.setdefault("HOME", str(home))
    env["PATH"] = search_path(base.get("PATH"), home)
    return env


def find_exe(name: str, *, home: Path | None = None, path: str | None = None) -> str | None:
    """A program by name, on the PATH with the app's three extra places after it."""
    home = home or Path.home()
    return shutil.which(name, path=search_path(path if path is not None else os.environ.get("PATH"), home))


# --- a command -------------------------------------------------------------------------------------------------------


# The commands running now, by process group: what `kill_live` ends when the app closes. A check's own thread is the first
# to end its command (it sees the stop within `POLL`); this is the net under it, for a thread that is stuck.
_LIVE: dict[int, subprocess.Popen] = {}
_LIVE_LOCK = threading.Lock()


def _end(proc: subprocess.Popen) -> None:
    """Kill a command's whole process group and wait for it: nothing it started in that group outlives it. A command already
    reaped is not signalled (its pid may be someone else's by now)."""
    with _LIVE_LOCK:
        _LIVE.pop(proc.pid, None)
    if proc.returncode is None:
        host.kill_tree(proc)
    if proc.stdout is not None:
        try:
            proc.stdout.close()
        except (OSError, ValueError):
            pass
    proc.wait()


def kill_live() -> int:
    """End every command still running, whole groups, and wait for each. The closing app calls it last, so no command
    outlives it. Returns how many it ended."""
    with _LIVE_LOCK:
        running = list(_LIVE.values())
    for proc in running:
        _end(proc)
    return len(running)


def run_argv(
    argv: Sequence[str], *, env: Mapping[str, str], cwd: Path, seconds: float, stop: threading.Event,
) -> tuple[int | None, str, str | None]:
    """Run a program to the end: its exit code, what it printed, and why it was stopped if it was ("no answer in 20 s",
    "output over 256 KB", "stopped"). The exit code is None when it was stopped. A stop, a deadline and an output over the
    limit all end the same way: the program's process group is killed and waited for before this returns."""
    if stop.is_set():
        return None, "", "stopped"  # the app is closing: nothing new is started
    try:
        proc = subprocess.Popen(
            list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cwd,
            env=dict(env), **host.NEW_GROUP,  # a group of its own, so `_end` takes everything it started
        )
    except FileNotFoundError:
        return None, "", f"command not found: {argv[0]}"
    except PermissionError:
        return None, "", f"not allowed to run {argv[0]}"
    except OSError as exc:
        return None, "", f"cannot run {argv[0]}: {exc.strerror or exc}"
    with _LIVE_LOCK:
        _LIVE[proc.pid] = proc

    deadline = time.monotonic() + seconds
    chunks: list[bytes] = []
    size = 0
    output = host.OutputReader(proc.stdout)
    try:
        while True:
            if stop.is_set() or proc.returncode is not None:  # told to stop, or ended under us by `kill_live`
                _end(proc)
                return None, "", "stopped"
            left = deadline - time.monotonic()
            if left <= 0:
                _end(proc)
                return None, b"".join(chunks).decode("utf-8", "replace"), f"no answer in {num(seconds)} s"
            try:
                data = output.read(min(left, POLL))
            except (OSError, ValueError):  # its output was closed under us: the command was ended elsewhere
                _end(proc)
                return None, "", "stopped"
            if data is None:
                continue
            if not data:
                break
            size += len(data)
            if size > MAX_OUTPUT:
                _end(proc)
                return None, b"".join(chunks).decode("utf-8", "replace"), f"output over {MAX_OUTPUT // 1024} KB"
            chunks.append(data)
        proc.stdout.close()
        # Its output is over; it may still be running (it closed its output and carried on). The wait is a poll, so a stop or
        # the deadline ends it too.
        while proc.poll() is None:
            if stop.is_set():
                _end(proc)
                return None, "", "stopped"
            if time.monotonic() >= deadline:
                _end(proc)
                return None, b"".join(chunks).decode("utf-8", "replace"), f"no answer in {num(seconds)} s"
            time.sleep(0.02)
        return proc.returncode, b"".join(chunks).decode("utf-8", "replace"), None
    finally:
        output.close()
        with _LIVE_LOCK:
            _LIVE.pop(proc.pid, None)
        if proc.returncode is None and proc.poll() is None:
            _end(proc)


def _cmd(fields: Mapping[str, Any], *, home: Path, stop: threading.Event, environ: Mapping[str, str]) -> Result:
    argv = list(fields["argv"])
    env = clean_env(environ, home)
    if "/" not in argv[0] and os.sep not in argv[0]:
        found = shutil.which(argv[0], path=env["PATH"])
        if found is None:
            return Result(False, f"command not found: {argv[0]}")
        argv[0] = found
    code, output, why = run_argv(argv, env=env, cwd=home, seconds=fields["timeout"], stop=stop)
    raw = shown(output)
    if why is not None:
        return Result(False, why, raw=raw)
    want = fields["exit"]
    if code != want:
        return Result(False, f"last exit code {code}" if want == 0 else f"exit code {code}, wanted {want}", raw=raw)
    if "parse" not in fields:
        return Result(True, f"exit code {code}", raw=raw)
    found = re.search(fields["parse"], output, re.MULTILINE)
    if found is None:
        return Result(False, "no number found by the pattern", raw=raw)
    digits = found.group(1) or ""
    value = _number(digits)
    if value is None:
        return Result(False, f"{shown(digits, 30)!r} is not a number", raw=raw)
    problem = _within(value, fields)
    plain = f"{num(value)} from {shown(found.group(0).strip(), 40)!r}" + (f", {problem}" if problem else "")
    return Result(problem is None, _words(fields, value, plain, problem), value=value, raw=raw)


# --- a file ----------------------------------------------------------------------------------------------------------


def _file(fields: Mapping[str, Any], *, home: Path) -> Result:
    raw_path = fields["path"]
    path = home / raw_path[2:] if raw_path.startswith("~/") else Path(raw_path)
    real = Path(os.path.realpath(path))
    if not real.is_relative_to(Path(os.path.realpath(home))):
        return Result(False, "the file is outside the home folder")
    try:
        info = real.stat()
    except FileNotFoundError:
        return Result(False, "file not found")
    except OSError as exc:
        return Result(False, f"cannot read the file: {exc.strerror or exc}")
    if not real.is_file():
        return Result(False, "not a file")
    age = max(0.0, (time.time() - info.st_mtime) / 3600)
    with real.open("rb") as handle:
        handle.seek(max(0, info.st_size - FILE_TAIL))
        tail = handle.read().decode("utf-8", "replace")
    lines = [line for line in tail.splitlines() if line.strip()]
    last = lines[-1].strip() if lines else ""
    raw = shown("\n".join(lines[-5:]))
    facts = [f"{num(round(age, 1))} h old"]
    if "max_age_hours" in fields and age > fields["max_age_hours"]:
        return Result(False, f"{facts[0]}, wanted {num(fields['max_age_hours'])} h at most", value=round(age, 1), raw=raw)
    if "last_line" in fields:
        if not re.search(fields["last_line"], last):
            return Result(False, f"{facts[0]}, last line {shown(last, 60)!r} does not match", value=round(age, 1), raw=raw)
        facts.append(f"last line {shown(last, 60)!r}")
    return Result(True, ", ".join(facts), value=round(age, 1), raw=raw)


# --- a host name -----------------------------------------------------------------------------------------------------


def _dns(fields: Mapping[str, Any]) -> Result:
    try:
        found = socket.getaddrinfo(fields["host"], None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        return Result(False, f"does not resolve ({exc.strerror or exc})")
    addresses = sorted({str(info[4][0]) for info in found})
    return Result(True, f"resolves to {addresses[0]}", raw="\n".join(addresses))


# --- an address ------------------------------------------------------------------------------------------------------


def _read_data(fields: Mapping[str, Any], data: Any, status_line: str, raw: str) -> Result:
    """What the fields of a JSON answer say, shared by an address and an MCP tool."""
    facts = [status_line]
    for path, want in fields.get("expect", {}).items():
        got = dig(data, path)
        if got != want:
            return Result(False, f"{path} is {json.dumps(got, ensure_ascii=False)}, wanted "
                                 f"{json.dumps(want, ensure_ascii=False)}", raw=raw)
        facts.append(f"{path}={json.dumps(got, ensure_ascii=False)}")
    value = None
    if "value" in fields:
        got = dig(data, fields["value"])
        value = _number(got)
        if value is None:
            return Result(False, f"{fields['value']} is {json.dumps(got, ensure_ascii=False)}, not a number", raw=raw)
        problem = _within(value, fields)
        facts.append(f"{fields['value']}={num(value)}" + (f", {problem}" if problem else ""))
        return Result(problem is None, _words(fields, value, ", ".join(facts), problem), value=value, raw=raw)
    return Result(True, ", ".join(facts), raw=raw)


def _http(fields: Mapping[str, Any]) -> Result:
    parts = urlsplit(fields["url"])
    cls = HTTPSConnection if parts.scheme == "https" else HTTPConnection
    target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    conn = cls(parts.hostname, parts.port, timeout=fields["timeout"])
    try:
        conn.request("GET", target, headers={"User-Agent": "Verticals-source-check", "Accept": "application/json, */*;q=0.5"})
        reply = conn.getresponse()
        body = reply.read(MAX_BODY + 1)[:MAX_BODY]
        status = reply.status
    finally:
        conn.close()
    text = body.decode("utf-8", "replace")
    raw = shown(f"HTTP {status} {reply.reason}\n{text}")
    want = fields["status"]
    if status != want:
        return Result(False, f"HTTP {status}" if want == 200 else f"HTTP {status}, wanted {want}", raw=raw)
    data = None
    if "expect" in fields or "value" in fields:
        try:
            data = json.loads(text)
        except ValueError:
            return Result(False, f"HTTP {status}, the answer is not JSON", raw=raw)
    return _read_data(fields, data, f"HTTP {status}", raw)


# --- an MCP tool -----------------------------------------------------------------------------------------------------


async def _call(fields: Mapping[str, Any]) -> tuple[bool, str, Any]:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    seconds = float(fields["timeout"])
    async with streamable_http_client(fields["url"]) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=seconds) as session:
            await session.initialize()
            result = await session.call_tool(fields["tool"], fields["args"], read_timeout_seconds=seconds)
    text = "".join(getattr(part, "text", "") for part in getattr(result, "content", None) or [])
    data = getattr(result, "structured_content", None)
    if data is None:
        try:
            data = json.loads(text)
        except ValueError:
            data = None
    return bool(getattr(result, "is_error", False)), text, data


def _leaf(exc: BaseException) -> BaseException:
    """The error inside a group of errors: the transport raises its failures wrapped in a task group's."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def _mcp(fields: Mapping[str, Any]) -> Result:
    try:
        failed, text, data = asyncio.run(asyncio.wait_for(_call(fields), fields["timeout"]))
    except TimeoutError:
        raise
    except Exception as exc:  # noqa: BLE001 - a server that cannot be reached is the answer
        leaf = _leaf(exc)
        return Result(False, f"no answer ({type(leaf).__name__}: {one_line(leaf, 100)})")
    raw = shown(text or json.dumps(data, ensure_ascii=False, default=str))
    if failed:
        return Result(False, f"the tool reported an error: {shown(text, 80)}", raw=raw)
    return _read_data(fields, data, "answered", raw)


# --- the way in ------------------------------------------------------------------------------------------------------


def _deadline(check: Check) -> float:
    f = check.fields
    if check.kind in ("http", "mcp", "cmd"):
        return float(f["timeout"]) + GRACE
    return 90.0 + GRACE if check.kind in ("connections", "servers") else 10.0


def run_check(
    check: Check,
    *,
    stop: threading.Event | None = None,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
    connections: Sequence[str] = (),
    path: str | None = None,
    servers: Collection[str] | None = None,
    listed: dict | None = None,
) -> Result | None:
    """Run one check and answer. None only when the app stopped first. Never raises: a run that cannot run is a run that
    failed, and says why in one line. `servers` are the ones the Connections check judges (None: every one); `listed`
    keeps one answer of `claude mcp list` for every check of a pass that asks it."""
    stop = stop or threading.Event()
    home = home or Path.home()
    environ = os.environ if environ is None else environ
    started = time.monotonic()
    box: dict[str, Any] = {}

    def work() -> None:
        try:
            if check.kind == "http":
                box["result"] = _http(check.fields)
            elif check.kind == "mcp":
                box["result"] = _mcp(check.fields)
            elif check.kind == "cmd":
                box["result"] = _cmd(check.fields, home=home, stop=stop, environ=environ)
            elif check.kind == "file":
                box["result"] = _file(check.fields, home=home)
            elif check.kind == "dns":
                box["result"] = _dns(check.fields)
            else:
                from verticals.sources import connections as agents

                asked, only = (("claude",), reading_servers(check.fields["reads"])) if check.kind == "servers" else (
                    connections, servers)
                box["result"] = agents.check(asked, home=home, stop=stop, environ=environ, path=path, only=only,
                                             listed=listed)
        except BaseException as exc:  # noqa: BLE001 - whatever went wrong is the answer
            box["error"] = exc

    thread = threading.Thread(target=work, name="source-check", daemon=True)
    thread.start()
    limit = time.monotonic() + _deadline(check)
    while thread.is_alive():
        if stop.is_set():
            if check.kind in ("cmd", "connections", "servers"):
                # The check's own thread ends its command within `POLL`, the whole group killed and reaped; waiting for it is
                # what makes "stopped" mean "gone". An address or a lookup cannot be cut short and is simply let go.
                thread.join(STOP_GRACE)
            return None
        if time.monotonic() >= limit:
            return Result(False, f"no answer in {num(limit - started)} s", ms=int((time.monotonic() - started) * 1000))
        thread.join(min(0.1, max(0.0, limit - time.monotonic())))
    if stop.is_set():
        return None  # whatever it found while the app was closing is not an answer: it must never count as a failure
    ms = int((time.monotonic() - started) * 1000)
    if "error" in box:
        exc = box["error"]
        if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
            return Result(False, f"no answer in {num(float(check.fields.get('timeout', _deadline(check))))} s", ms=ms)
        if isinstance(exc, OSError):
            return Result(False, f"no answer ({one_line(exc.strerror or type(exc).__name__, 80)})", ms=ms)
        return Result(False, f"{type(exc).__name__}: {one_line(exc, 120)}", ms=ms)
    result: Result = box["result"]
    return Result(result.ok, one_line(result.detail), result.value, ms, result.raw)

