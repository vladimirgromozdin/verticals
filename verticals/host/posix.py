"""macOS and Linux: the same names as windows.py, done the way these systems need."""
from __future__ import annotations

import os
import selectors
import signal
import socket
import subprocess
from pathlib import Path
from typing import Any, Callable

__all__ = [
    "EXE", "PG_BIN_DIRS", "PG_HINT", "NPM", "SERVICE_ENV", "KEEP_ENV", "NEW_GROUP", "BACKGROUND",
    "UVICORN_LOOP", "DROPPED_CONNECTION", "COMMAND_LINE_MAX",
    "venv_python", "python312", "port_free", "postgres_options", "pg_env", "spawn_service", "stop_tree", "kill_tree",
    "on_close", "ensure_utf8", "OutputReader",
]

# ---------------------------------------------------------------- where things are

EXE = ""  # what an executable's file name ends with
PG_BIN_DIRS = ["/opt/homebrew/opt/postgresql@16/bin", "/usr/local/opt/postgresql@16/bin", "/usr/lib/postgresql/16/bin"]
PG_HINT = "brew install postgresql@16"
NPM = "npm"


def venv_python(venv: Path) -> Path:
    return venv / "bin" / "python"


def python312() -> str | None:
    """A Python 3.12 found the way only this system knows. Here there is none beyond `python3.12` on PATH and uv."""
    return None


# ---------------------------------------------------------------- services

SERVICE_ENV: dict[str, str] = {}  # what every Python service started by a launcher is also given
KEEP_ENV: tuple[str, ...] = ()  # what a Sources command needs from the environment beyond the common list
NEW_GROUP: dict[str, Any] = {"start_new_session": True}  # Popen arguments: a process group of its own
BACKGROUND: dict[str, Any] = {}  # Popen arguments for a program that must not share this terminal
UVICORN_LOOP = "auto"
DROPPED_CONNECTION: tuple[type[BaseException], ...] = ()  # errors that only mean a browser dropped a spare connection
COMMAND_LINE_MAX: int | None = None  # no command-line limit a prompt comes near


def port_free(port: int) -> bool:
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def postgres_options(port: int, settings: str) -> str:
    """PostgreSQL's options for `pg_ctl -o`: loopback TCP only, no Unix socket."""
    return f"-h 127.0.0.1 -p {port} -k '' {settings}"


def pg_env() -> dict[str, str]:
    # On macOS the postmaster refuses to start without a valid locale in the environment
    # ("postmaster became multithreaded during startup"); apps opened from Finder have none.
    env = os.environ.copy()
    if not env.get("LC_ALL"):
        env["LC_ALL"] = "en_US.UTF-8"
    return env


def spawn_service(name: str, argv: list, *, cwd: Path, env: dict[str, str], logfile: Path) -> subprocess.Popen:
    """A launcher's service: its output goes to its log file, and it runs in a process group of its own."""
    log = open(logfile, "ab")
    return subprocess.Popen([str(a) for a in argv], cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)


def stop_tree(proc: subprocess.Popen, timeout: float = 10) -> None:
    """Stop a process started with NEW_GROUP and everything it started: politely, then for good."""
    os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()


def kill_tree(proc: subprocess.Popen) -> None:
    """End a process started with NEW_GROUP and everything it started, at once."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def on_close(cleanup: Callable[[], None]) -> Any:
    """Run `cleanup` when the terminal window closes. A closing terminal sends SIGHUP here, and the launchers already stop
    on signals; nothing to add."""
    return None


def ensure_utf8() -> None:
    """Make this process read and write files as UTF-8. It already does here."""


class OutputReader:
    """A command's output, read in chunks with a timeout: `read` answers None when nothing came in time, b"" at the end."""

    def __init__(self, stream: Any) -> None:
        self.stream = stream
        self.selector = selectors.DefaultSelector()
        self.selector.register(stream, selectors.EVENT_READ)

    def read(self, timeout: float) -> bytes | None:
        if not self.selector.select(timeout):
            return None
        return os.read(self.stream.fileno(), 65536)

    def close(self) -> None:
        self.selector.close()
