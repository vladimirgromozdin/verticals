"""Windows: the same names as posix.py, done the way Windows needs."""
from __future__ import annotations

import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable

__all__ = [
    "EXE", "PG_BIN_DIRS", "PG_HINT", "NPM", "SERVICE_ENV", "KEEP_ENV", "NEW_GROUP", "BACKGROUND",
    "UVICORN_LOOP", "DROPPED_CONNECTION", "COMMAND_LINE_MAX",
    "venv_python", "python312", "port_free", "postgres_options", "pg_env", "spawn_service", "stop_tree", "kill_tree",
    "on_close", "ensure_utf8", "OutputReader",
]

# ---------------------------------------------------------------- where things are

EXE = ".exe"
# The EDB installer's default, then the EDB binaries zip unpacked without admin rights.
PG_BIN_DIRS = [str(Path(os.environ[var]) / sub)
               for var, sub in (("ProgramFiles", "PostgreSQL/16/bin"), ("LOCALAPPDATA", "Programs/PostgreSQL/16/bin"))
               if os.environ.get(var)]
PG_HINT = r"install it, or unpack its binaries into %LOCALAPPDATA%\Programs\PostgreSQL\16"
NPM = shutil.which("npm") or "npm"  # npm.cmd: a bare "npm" is not found without a shell


def venv_python(venv: Path) -> Path:
    return venv / "Scripts" / "python.exe"


def python312() -> str | None:
    """This Python if it is 3.12, else the one the py launcher knows: Windows has no `python3.12` on PATH."""
    if sys.version_info[:2] == (3, 12):
        return sys.executable
    if shutil.which("py"):
        out = subprocess.run(["py", "-3.12", "-c", "import sys; print(sys.executable)"], capture_output=True, text=True)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    return None


# ---------------------------------------------------------------- services

# Source files are UTF-8; Windows would otherwise read them in its ANSI code page.
SERVICE_ENV = {"PYTHONUTF8": "1"}
# Without these a program cannot find its system DLLs, its profile, or a temp folder.
KEEP_ENV = ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "USERPROFILE", "USERNAME", "APPDATA", "LOCALAPPDATA",
            "PROGRAMDATA", "PROGRAMFILES", "TEMP", "TMP")
# A new group also keeps the console's Ctrl-C away from it: the launcher stops it instead.
NEW_GROUP: dict[str, Any] = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
# A console of its own, never shown: this console's Ctrl-C and close would otherwise reach it first and can kill it
# half way (PostgreSQL started by pg_ctl).
BACKGROUND: dict[str, Any] = {"creationflags": subprocess.CREATE_NO_WINDOW}
# uvicorn would pick the Proactor loop, which psycopg's async connection (/api/events) cannot run on.
UVICORN_LOOP = "asyncio:SelectorEventLoop"
# Browsers open spare connections and drop them unused; Windows reports that as a reset, macOS as a plain close.
DROPPED_CONNECTION = (ConnectionResetError, ConnectionAbortedError)
# A command line is at most 32,767 characters; the morning report's prompt alone comes near that.
COMMAND_LINE_MAX: int | None = 32767


def port_free(port: int) -> bool:
    with socket.socket() as sock:
        # No SO_REUSEADDR: here it lets a bind take a port another process holds.
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def postgres_options(port: int, settings: str) -> str:
    # No "-k ''": Windows builds have no Unix socket directory, and '' does not survive the command line.
    return f"-h 127.0.0.1 -p {port} {settings}"


def pg_env() -> dict[str, str]:
    return os.environ.copy()


def spawn_service(name: str, argv: list, *, cwd: Path, env: dict[str, str], logfile: Path) -> subprocess.Popen:
    """A launcher's service: its output goes to its log file, and it runs in a process group of its own."""
    log = open(logfile, "ab")
    return subprocess.Popen([str(a) for a in argv], cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, **NEW_GROUP)


def stop_tree(proc: subprocess.Popen, timeout: float = 10) -> None:
    # No process groups to signal: end the whole tree (npm.cmd -> node, say) by its root.
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    proc.wait()


def kill_tree(proc: subprocess.Popen) -> None:
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)


def on_close(cleanup: Callable[[], None]) -> Any:
    """Closing the console window ends the process without a KeyboardInterrupt, so `finally` never runs. Run the same
    cleanup from the console's close (and logoff, shutdown) event instead; Windows allows it 5 seconds."""
    import ctypes
    from ctypes import wintypes

    def handler(event: int) -> bool:
        if event in (2, 5, 6):  # CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT
            cleanup()
            return True
        return False  # Ctrl-C and Ctrl-Break go on to Python's own handler: KeyboardInterrupt
    routine = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)(handler)
    ctypes.windll.kernel32.SetConsoleCtrlHandler(routine, True)
    return routine  # the caller keeps it alive; a collected callback would crash the process


def ensure_utf8() -> None:
    """Every file the app reads is UTF-8, and so is everything the agents say; Windows would read them in its ANSI code
    page. The mode can only be set at start, so run this script again with it, and end with it."""
    if sys.flags.utf8_mode:
        return
    child = subprocess.Popen([sys.executable, "-X", "utf8", *sys.argv])
    while True:
        try:
            sys.exit(child.wait())
        except KeyboardInterrupt:
            pass  # the console's Ctrl-C reaches the child too; it stops everything, then this ends with it


class OutputReader:
    """A command's output, read in chunks with a timeout: `read` answers None when nothing came in time, b"" at the end.
    A pipe cannot be selected on here, so a daemon thread reads it into a queue."""

    def __init__(self, stream: Any) -> None:
        self.stream = stream
        self.chunks: queue.SimpleQueue[bytes] = queue.SimpleQueue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        try:
            while data := os.read(self.stream.fileno(), 65536):
                self.chunks.put(data)
        except (OSError, ValueError):  # closed under it when the command is ended
            pass
        self.chunks.put(b"")

    def read(self, timeout: float) -> bytes | None:
        try:
            return self.chunks.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        pass
