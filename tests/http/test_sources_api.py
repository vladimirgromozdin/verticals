"""Sources (docs/design/sources.md) through a real API process: the list the Inbox draws, the owner's Approve, the timer
that runs inside the API and what becomes of it when the API is told to stop. A real uvicorn subprocess, real sockets, no
mocks. The processes here run the timer fast (a tick of one second); the others in this suite leave it at its default."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from tests.http.conftest import REPO_ROOT, TEST_OWNER, TEST_TOKEN, Server, _free_port, _wait_healthy
from verticals.core import source_checks as sc


@contextmanager
def _api(dsn: str, tmp_path: Path, *, tick: str = "1") -> Iterator[tuple[Server, subprocess.Popen]]:
    """A real `python -m verticals.api.app`, its Sources timer ticking every `tick` seconds ("0" is off)."""
    port = _free_port()
    log_path = tmp_path / "api.log"
    env = dict(os.environ)
    env.update(
        VERTICALS_DATABASE_URL=dsn, VERTICALS_TOKEN=TEST_TOKEN, VERTICALS_OWNER=TEST_OWNER, VERTICALS_BIND=f"127.0.0.1:{port}",
        VERTICALS_POOL_MIN="2", VERTICALS_POOL_MAX="10", VERTICALS_LOG_LEVEL="warning", VERTICALS_SOURCES_TICK=tick,
    )
    with open(log_path, "w") as logfile:
        proc = subprocess.Popen([sys.executable, "-m", "verticals.api.app"], cwd=REPO_ROOT, env=env, stdout=logfile,
                                stderr=subprocess.STDOUT, start_new_session=True)
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_healthy(base_url, proc, log_path)
        yield Server(base_url=base_url, token=TEST_TOKEN, dsn=dsn, log_path=log_path), proc
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


@pytest.fixture
def api(f2_dsn: str, tmp_path: Path) -> Iterator[httpx.Client]:
    with _api(f2_dsn, tmp_path) as (server, _):
        with httpx.Client(base_url=server.base_url, headers={"Authorization": f"Bearer {TEST_TOKEN}"}, timeout=30.0) as client:
            yield client


def _source(client: httpx.Client, name: str, raw: dict) -> dict:
    body = sc.build_body(gives="Something.", how="Read it.", since="Every hour.", check=sc.Check.from_dict(raw), fixes=[])
    made = client.post("/api/docs", json={"path": f"sources/{name}.md", "title": name.title(), "body": body})
    assert made.status_code == 201, made.text
    return made.json()


def _listed(client: httpx.Client, doc_id: str) -> dict:
    listed = client.get("/api/sources")
    assert listed.status_code == 200, listed.text
    return {s["id"]: s for s in listed.json()["sources"]}[doc_id]


def _until(client: httpx.Client, doc_id: str, ready: Callable[[dict], bool], seconds: float = 20.0) -> dict:
    deadline = time.monotonic() + seconds
    seen: dict = {}
    while time.monotonic() < deadline:
        seen = _listed(client, doc_id)
        if ready(seen):
            return seen
        time.sleep(0.2)
    raise AssertionError(f"the source never got there; last seen: {seen}")


def test_the_list_is_behind_the_token(api: httpx.Client) -> None:
    assert httpx.get(f"{api.base_url}/api/sources").status_code == 401
    assert httpx.post(f"{api.base_url}/api/sources/ABCDEFGH/approve", json={"check_hash": "0" * 64}).status_code == 401
    assert api.get("/api/sources").json() == {"sources": []}


def test_a_name_lookup_waits_for_approval_like_every_check_and_turns_green_within_seconds_of_it(api: httpx.Client) -> None:
    made = _source(api, "host", {"kind": "dns", "host": "localhost"})
    first = _listed(api, made["id"])
    assert first["path"] == "sources/host.md" and first["kind"] == "dns" and first["where"] == "anywhere"
    assert first["summary"] == "Looks up localhost every hour and wants it to resolve."
    assert "excerpt" in first and first["excerpt"].startswith("## What it gives the report")
    assert (first["status"], first["why"], first["needs_approval"]) == ("grey", "waiting", True)
    time.sleep(2.5)  # the timer looks twice
    assert _listed(api, made["id"])["checked_at"] is None, "a name lookup nobody approved is never made"
    approved = api.post(f"/api/sources/{made['id']}/approve", json={"check_hash": first["check_hash"]})
    assert approved.status_code == 200 and approved.json()["approved"] is True
    green = _until(api, made["id"], lambda s: s["status"] == "ok")
    assert green["detail"].startswith("resolves to ") and green["checked_at"] and green["ms"] is not None


def test_a_command_waits_for_approval_through_the_route_and_runs_within_seconds_of_it(api: httpx.Client) -> None:
    made = _source(api, "disk", {"kind": "cmd", "argv": ["/bin/echo", "disk 71% used"], "parse": r"(\d+)%", "max": 90})
    waiting = _listed(api, made["id"])
    assert (waiting["status"], waiting["why"], waiting["needs_approval"]) == ("grey", "waiting", True)
    time.sleep(2.5)  # the timer looks twice
    assert _listed(api, made["id"])["why"] == "waiting", "an unapproved command is never run"

    wrong = api.post(f"/api/sources/{made['id']}/approve", json={"check_hash": "0" * 64})
    assert wrong.status_code == 409 and wrong.json()["error"] == "revision_mismatch"
    assert api.post(f"/api/sources/{made['id']}/approve", json={"check_hash": "short"}).status_code == 422
    assert api.post(f"/api/sources/{made['id']}/approve", json={"check_hash": "0" * 64, "extra": 1}).status_code == 422
    assert api.post("/api/sources/ZZZZZZZZ/approve", json={"check_hash": "0" * 64}).status_code == 404

    approved = api.post(f"/api/sources/{made['id']}/approve", json={"check_hash": waiting["check_hash"]})
    assert approved.status_code == 200 and approved.json()["approved"] is True
    green = _until(api, made["id"], lambda s: s["status"] == "ok", seconds=10)
    assert (green["value"], green["detail"]) == (71.0, "71 from '71%'")


def test_a_check_changed_after_approval_waits_for_the_owner_again(api: httpx.Client) -> None:
    raw = {"kind": "cmd", "argv": ["/bin/echo", "hi"]}
    made = _source(api, "greet", raw)
    api.post(f"/api/sources/{made['id']}/approve", json={"check_hash": _listed(api, made["id"])["check_hash"]})
    _until(api, made["id"], lambda s: s["status"] == "ok")

    body = sc.set_section(made["body"], "check", sc.render_block(sc.Check.from_dict({**raw, "argv": ["/bin/echo", "bye"]})))
    saved = api.patch(f"/api/docs/{made['id']}", json={"expected_revision": made["revision"], "body": body})
    assert saved.status_code == 200
    changed = _listed(api, made["id"])
    assert (changed["status"], changed["why"], changed["approved"]) == ("grey", "waiting", False)
    time.sleep(2.5)
    assert _listed(api, made["id"])["why"] == "waiting", "the new text is not run on the old approval"
    stale = api.post(f"/api/sources/{made['id']}/approve", json={"check_hash": _listed(api, made["id"])["check_hash"]})
    assert stale.status_code == 200


class _Counting(BaseHTTPRequestHandler):
    hits = 0

    def do_GET(self) -> None:  # noqa: N802
        type(self).hits += 1
        body = json.dumps({"status": "ok"}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


def test_an_address_waits_for_approval_through_the_route_and_is_asked_only_after_it(api: httpx.Client) -> None:
    handler = type("Handler", (_Counting,), {"hits": 0})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        made = _source(api, "up", {"kind": "http", "url": f"http://127.0.0.1:{server.server_address[1]}/up", "expect": {"status": "ok"}})
        waiting = _listed(api, made["id"])
        assert (waiting["status"], waiting["why"], waiting["needs_approval"]) == ("grey", "waiting", True)
        assert waiting["summary"].startswith("Asks http://127.0.0.1:")
        time.sleep(2.5)  # the timer looks twice
        assert handler.hits == 0 and _listed(api, made["id"])["why"] == "waiting", "an address nobody approved is never asked"

        approved = api.post(f"/api/sources/{made['id']}/approve", json={"check_hash": waiting["check_hash"]})
        assert approved.status_code == 200 and approved.json()["approved"] is True
        green = _until(api, made["id"], lambda s: s["status"] == "ok", seconds=10)
        assert green["detail"] == 'HTTP 200, status="ok"' and handler.hits >= 1
    finally:
        server.shutdown()
        server.server_close()


def test_a_document_with_no_check_is_not_listed_and_every_check_waits_for_approval(api: httpx.Client) -> None:
    plain = api.post("/api/docs", json={"path": "sources/notes.md", "title": "Notes", "body": "Nothing to check yet."}).json()
    assert plain["id"] not in {s["id"] for s in api.get("/api/sources").json()["sources"]}, "a plain document, not a source"
    assert api.post(f"/api/sources/{plain['id']}/approve", json={"check_hash": "0" * 64}).status_code == 422
    web = _source(api, "web", {"kind": "http", "url": "http://127.0.0.1:9/never"})
    tool = _source(api, "tool", {"kind": "mcp", "url": "http://127.0.0.1:9/mcp", "tool": "get_status"})
    name = _source(api, "name", {"kind": "dns", "host": "localhost"})
    for source in (web, tool, name):
        seen = _listed(api, source["id"])
        assert (seen["status"], seen["why"], seen["needs_approval"]) == ("grey", "waiting", True), source["path"]
    # Approved, a name lookup answers; the rest are never asked.
    assert api.post(f"/api/sources/{name['id']}/approve", json={"check_hash": _listed(api, name["id"])["check_hash"]}).status_code == 200
    _until(api, name["id"], lambda s: s["status"] == "ok")
    # The row puts what needs a look first: what waits for the owner, then what answers.
    order = [s["path"] for s in api.get("/api/sources").json()["sources"]]
    assert "sources/notes.md" not in order
    assert order.index("sources/web.md") < order.index("sources/name.md")
    assert order.index("sources/tool.md") < order.index("sources/name.md")
    assert _listed(api, web["id"])["checked_at"] is None, "the address that waited was never asked"


def test_with_the_timer_off_nothing_is_ever_checked(f2_dsn: str, tmp_path: Path) -> None:
    with _api(f2_dsn, tmp_path, tick="0") as (server, _):
        with httpx.Client(base_url=server.base_url, headers={"Authorization": f"Bearer {TEST_TOKEN}"}, timeout=30.0) as client:
            made = _source(client, "host", {"kind": "dns", "host": "localhost"})
            approved = client.post(f"/api/sources/{made['id']}/approve", json={"check_hash": _listed(client, made["id"])["check_hash"]})
            assert approved.status_code == 200
            time.sleep(2.5)
            assert (_listed(client, made["id"])["why"], _listed(client, made["id"])["checked_at"]) == ("new", None)


def test_stopping_the_api_ends_the_timer_and_a_command_it_is_running(f2_dsn: str, tmp_path: Path) -> None:
    # A length no other run of this test has, so `pgrep` finds this command and no other (S-112 runs the suite inside itself).
    length = f"{20 + secrets.randbelow(9)}.{secrets.randbelow(10**6):06d}"
    running = ["pgrep", "-f", f"sleep {length}"]
    with _api(f2_dsn, tmp_path) as (server, proc):
        with httpx.Client(base_url=server.base_url, headers={"Authorization": f"Bearer {TEST_TOKEN}"}, timeout=30.0) as client:
            made = _source(client, "slow", {"kind": "cmd", "argv": ["/bin/sleep", length], "timeout": 40})
            client.post(f"/api/sources/{made['id']}/approve", json={"check_hash": _listed(client, made["id"])["check_hash"]})
            deadline = time.monotonic() + 10
            while subprocess.run(running, capture_output=True).returncode != 0:
                assert time.monotonic() < deadline, "the timer never started the command"
                time.sleep(0.1)
        started = time.monotonic()
        proc.terminate()
        proc.wait(timeout=8)
        assert time.monotonic() - started < 6, "the API ends promptly, the timer with it"
    # The lifespan kills the command's group and waits for it before it ends, so it is gone as the API is. The poll is for
    # the machine, not for the app: a few seconds of slack for the process table, never a fixed pause.
    deadline = time.monotonic() + 5
    while subprocess.run(running, capture_output=True).returncode == 0:
        assert time.monotonic() < deadline, "the command outlived the API"
        time.sleep(0.05)


def test_the_list_carries_the_tools_that_read_each_source_and_where_the_last_report_stopped(api: httpx.Client) -> None:
    """For the morning report (docs/design/morning-quality.md): `reads` is in the check the owner approves, `cutoff` is the end
    of the source's window in the report before the day asked for."""
    reads = ["mcp__chat__list_messages", "mcp__chat__unread_summary"]
    made = _source(api, "team-chat", {"kind": "dns", "host": "localhost", "reads": reads})
    plain = _source(api, "mail", {"kind": "dns", "host": "localhost"})
    report = ("Not checked yet: a second agent is reading it against the sources.\n\n## Sources\n\nTimes in Europe/Berlin.\n\n"
              "| Source | Window | Read | Tasks | Inbox | Done | Put off | Context | Gap |\n| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
              "| [Team chat](doc:sources/team-chat.md) | 2026-10-10 07:00 – 2026-10-11 06:58 | 3 | 3 | 0 | 0 | 0 | 0 | 0 |\n")
    assert api.post("/api/docs", json={"path": "reports/morning/2026-10-11.md", "title": "Morning report — 11 October 2026",
                                         "body": report}).status_code == 201
    listed = {s["id"]: s for s in api.get("/api/sources", params={"day": "2026-10-12"}).json()["sources"]}
    assert listed[made["id"]]["reads"] == reads and listed[made["id"]]["cutoff"] == "2026-10-11T06:58:00+02:00"
    assert listed[plain["id"]]["reads"] == [] and listed[plain["id"]]["cutoff"] is None
    # The report of the same day is not the one before it.
    again = {s["id"]: s for s in api.get("/api/sources", params={"day": "2026-10-11"}).json()["sources"]}
    assert again[made["id"]]["cutoff"] is None
    assert api.get("/api/sources", params={"day": "yesterday"}).status_code == 422
