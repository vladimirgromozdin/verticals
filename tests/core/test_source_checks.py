"""The check inside a source document (docs/design/sources.md, `core/source_checks.py`): every kind and what each may
say, the one hash the owner approves, the fenced block that carries it, and the sections around it. Pure: no database."""

from __future__ import annotations

import pytest

from verticals.core import source_checks as sc
from verticals.core.errors import ValidationError

HTTP = {"kind": "http", "url": "https://example.test/health"}
MCP = {"kind": "mcp", "url": "http://127.0.0.1:9100/mcp", "tool": "get_status"}
CMD = {"kind": "cmd", "argv": ["df", "-k", "/"], "parse": r"(\d+)%", "max": 90}
FILE = {"kind": "file", "path": "~/logs/sync.log", "max_age_hours": 2, "last_line": "^OK"}
DNS = {"kind": "dns", "host": "example.test"}


def _check(raw: dict) -> sc.Check:
    return sc.Check.from_dict(raw)


def _refused(raw: dict, field: str) -> str:
    with pytest.raises(ValidationError) as caught:
        sc.Check.from_dict(raw)
    assert caught.value.detail["field"] == f"check.{field}"
    return caught.value.message


def test_each_kind_reads_with_its_defaults_filled_in() -> None:
    assert _check(HTTP).fields == {"url": "https://example.test/health", "status": 200, "timeout": 10}
    assert _check(MCP).fields == {"url": "http://127.0.0.1:9100/mcp", "tool": "get_status", "args": {}, "timeout": 15}
    assert _check(CMD).fields == {"argv": ["df", "-k", "/"], "exit": 0, "parse": r"(\d+)%", "max": 90, "timeout": 20}
    assert _check(FILE).fields == {"path": "~/logs/sync.log", "max_age_hours": 2, "last_line": "^OK"}
    assert _check(DNS).fields == {"host": "example.test"}


def test_where_follows_what_the_check_reaches() -> None:
    assert _check(CMD).where == "here" and _check(FILE).where == "here"
    assert _check(DNS).where == "anywhere" and _check(HTTP).where == "anywhere"
    # An address on this Mac or its own network can only be reached from here.
    assert _check(MCP).where == "here"
    assert _check({**HTTP, "url": "http://192.168.1.20:8080/up"}).where == "here"
    assert _check({**HTTP, "url": "http://nas.local/up"}).where == "here"
    assert _check({**HTTP, "url": "http://[::1]:8080/up"}).where == "here"
    assert _check({**DNS, "where": "here"}).where == "here"
    assert "must run here" in _refused({**CMD, "where": "anywhere"}, "where")
    assert "must run here" in _refused({**HTTP, "url": "http://localhost:8080/up", "where": "anywhere"}, "where")
    assert "here or anywhere" in _refused({**HTTP, "where": "cloud"}, "where")


def test_a_field_the_kind_does_not_take_is_refused_by_name() -> None:
    assert "takes no field 'max_age'" in _refused({**FILE, "max_age": 3}, "max_age")
    _refused({**DNS, "url": "https://example.test"}, "url")
    _refused({"kind": "ftp", "host": "example.test"}, "kind")
    _refused({"url": "https://example.test"}, "kind")
    _refused({"kind": "http"}, "url")


def test_the_agents_cannot_write_the_apps_own_kind_but_the_app_can() -> None:
    _refused({"kind": "connections"}, "kind")
    app = sc.Check.from_dict({"kind": "connections"}, app=True)
    assert (app.kind, app.where, app.fields, app.gated) == ("connections", "here", {}, False)


def test_a_command_is_a_list_of_words_never_a_shell_line() -> None:
    assert "never a shell line" in _refused({"kind": "cmd", "argv": "df -k /"}, "argv")
    _refused({"kind": "cmd", "argv": []}, "argv")
    _refused({"kind": "cmd", "argv": [""]}, "argv")
    _refused({"kind": "cmd", "argv": ["df", 3]}, "argv")
    _refused({"kind": "cmd", "argv": ["a\x00b"]}, "argv")
    _refused({"kind": "cmd", "argv": ["echo"] * 40}, "argv")


def test_what_a_number_is_read_with_must_be_a_pattern_with_a_group() -> None:
    _refused({**CMD, "parse": "(unclosed"}, "parse")
    assert "one group" in _refused({**CMD, "parse": r"\d+%"}, "parse")
    _refused({**FILE, "last_line": "["}, "last_line")
    # Limits and a sentence need a number to be about.
    _refused({"kind": "cmd", "argv": ["true"], "max": 3}, "max")
    _refused({"kind": "cmd", "argv": ["true"], "say": "{v}"}, "say")
    _refused({**CMD, "min": 100}, "min")
    _refused({**CMD, "max": True}, "max")
    _refused({**CMD, "max": float("nan")}, "max")


def test_an_address_is_plain_and_carries_no_secret() -> None:
    _refused({**HTTP, "url": "ftp://example.test/x"}, "url")
    _refused({**HTTP, "url": "https:///nohost"}, "url")
    _refused({**HTTP, "url": "https://example.test/a b"}, "url")
    assert "not a place for secrets" in _refused({**HTTP, "url": "https://me:secret@example.test/"}, "url")
    _refused({**HTTP, "url": "https://example.test:99999/"}, "url")
    _refused({**HTTP, "url": "http://[::1"}, "url")
    _refused({**MCP, "url": "http://[not-an-address]/mcp"}, "url")
    _refused({**HTTP, "status": 99}, "status")
    _refused({**HTTP, "status": "200"}, "status")
    _refused({**DNS, "host": "https://example.test/"}, "host")


def test_the_limits_of_time_and_age() -> None:
    _refused({**HTTP, "timeout": 0}, "timeout")
    _refused({**HTTP, "timeout": 31}, "timeout")
    _refused({**CMD, "timeout": 61}, "timeout")
    assert _check({**CMD, "timeout": 30.0}).fields["timeout"] == 30
    _refused({**FILE, "max_age_hours": 0}, "max_age_hours")
    _refused({**FILE, "path": "logs/sync.log"}, "path")
    _refused({"kind": "cmd", "argv": ["true"], "exit": 300}, "exit")


def test_an_mcp_check_may_call_only_a_tool_that_reads() -> None:
    for name in ("get_status", "list-events", "searchThreads", "health", "Ping", "check_sync"):
        assert sc.reads_only(name), name
    for name in ("send_message", "update_status", "delete-event", "createTask", "markRead"):
        assert not sc.reads_only(name), name
    assert "not a reading tool" in _refused({**MCP, "tool": "update_status"}, "tool")


def test_the_hash_is_the_check_and_only_the_check() -> None:
    base = _check(CMD)
    # Key order, spacing and a default written out change nothing.
    same = _check({"timeout": 20, "max": 90, "parse": r"(\d+)%", "argv": ["df", "-k", "/"], "kind": "cmd", "exit": 0})
    assert base.hash == same.hash and len(base.hash) == 64
    # Any change to what runs changes it.
    assert _check({**CMD, "argv": ["df", "-h", "/"]}).hash != base.hash
    assert _check({**CMD, "max": 80}).hash != base.hash
    assert _check({**CMD, "parse": r"(\d+)\s*%"}).hash != base.hash
    assert _check({**CMD, "timeout": 5}).hash != base.hash
    assert _check({**HTTP}).hash != _check({**HTTP, "status": 204}).hash
    # Every check the agent writes is gated, a name lookup too (the name goes to a resolver); only the app's own is not.
    assert all(_check(k).gated for k in (HTTP, MCP, CMD, FILE, DNS))
    assert sc.GATED == set(sc.KINDS) and not sc.Check.from_dict({"kind": "connections"}, app=True).gated


def test_the_block_goes_into_a_document_and_comes_back() -> None:
    body = sc.build_body(gives="Disk space of this Mac.", how="Read the number.", since="Every hour.", check=_check(CMD),
                         fixes=["Empty the Trash with `rm -r ~/.Trash`."])
    assert [line for line in body.split("\n") if line.startswith("## ")] == [f"## {h}" for _, h in sc.SECTIONS]
    assert "```check\n{" in body and sc.parse_check(body) == _check(CMD)
    assert sc.parse_check(body).hash == _check(CMD).hash


def test_a_block_the_editor_touched_still_reads() -> None:
    block = '```check \n\n{\n  "kind": "dns",\n\n  "host": "example.test"\n}\n\n```'
    assert sc.parse_check("## How it is checked\n" + block + "\n\nMore text.").fields == {"host": "example.test"}


def test_no_block_and_a_broken_block_say_which_it_is() -> None:
    with pytest.raises(ValidationError) as none:
        sc.parse_check("## How it is checked\nNothing here.")
    assert none.value.detail["missing"] is True and none.value.detail["field"] == "check"
    with pytest.raises(ValidationError) as broken:
        sc.parse_check("```check\n{not json}\n```")
    assert "not valid JSON" in broken.value.message and "missing" not in broken.value.detail
    with pytest.raises(ValidationError):
        sc.parse_check('```check\n["kind", "dns"]\n```')
    # Only a block marked `check` counts; the first one wins.
    with pytest.raises(ValidationError):
        sc.parse_check('```json\n{"kind": "dns", "host": "example.test"}\n```')
    first = sc.parse_check('```check\n{"kind": "dns", "host": "a.test"}\n```\n```check\n{"kind": "dns", "host": "b.test"}\n```')
    assert first.fields["host"] == "a.test"


def test_one_section_is_replaced_and_the_owners_words_around_it_stay() -> None:
    body = sc.build_body(gives="Old.", how="Read it.", since="Monday.", check=_check(DNS), fixes=[])
    body = body.replace("## Since when\nMonday.", "## Since when\nMonday.\n\nThe owner added this line.")
    changed = sc.set_section(body, "gives", "The calendar of the coming week.")
    assert "## What it gives the report\nThe calendar of the coming week.\n" in changed
    assert "Old." not in changed and "The owner added this line." in changed
    assert sc.section_text(changed, "how") == "Read it."
    assert sc.section_text(changed, "fixes") == sc.NO_FIXES
    swapped = sc.set_section(changed, "check", sc.render_block(_check(CMD)))
    assert sc.parse_check(swapped) == _check(CMD) and swapped.count("```check") == 1
    assert changed.endswith("\n") and not changed.endswith("\n\n")


def test_a_missing_section_is_added_at_the_end() -> None:
    assert sc.set_section("", "since", "Monday.") == "## Since when\nMonday.\n"
    added = sc.set_section("Words the owner wrote.\n", "fixes", sc.fixes_text(["Restart it."]))
    assert added == "Words the owner wrote.\n\n## Fixes the agent may make alone\n- Restart it.\n"
    assert sc.section_text(added, "gives") is None


def test_the_owner_reads_what_will_run_before_approving_it() -> None:
    assert _check(CMD).summary() == "Runs df -k / on this Mac every hour and wants exit code 0 and a number of at most 90."
    assert _check(HTTP).summary() == "Asks https://example.test/health every hour and wants HTTP 200."
    assert "status to be \"ok\"" in _check({**HTTP, "expect": {"status": "ok"}}).summary()
    assert _check(FILE).summary() == (
        "Reads ~/logs/sync.log on this Mac every hour and wants it changed within the last 2 hours and a last line "
        "that matches ^OK.")
    assert _check(DNS).summary() == "Looks up example.test every hour and wants it to resolve."
    assert _check(MCP).summary() == "Calls the tool get_status of http://127.0.0.1:9100/mcp every hour."
    # What the tool is sent is part of what is approved, so it is in the words.
    sent = _check({**MCP, "args": {"scope": "all", "limit": 5}}).summary()
    assert sent == 'Calls the tool get_status of http://127.0.0.1:9100/mcp with {"scope": "all", "limit": 5} every hour.', sent


def test_a_file_name_comes_from_the_title() -> None:
    assert sc.slug("Calendar, next week") == "calendar-next-week"
    assert sc.slug("   ") == "source" and sc.slug("Почта") == "source"
    assert sc.is_source_path("sources/calendar.md") and not sc.is_source_path("reports/morning/2026-10-11.md")
    assert not sc.is_source_path("sources/notes.txt")


# --- the tools that read a source in the morning (docs/design/morning-quality.md) --------------------------------------

READS = ["mcp__chat__list_messages", "mcp__chat__unread_summary", "mcp__mail__search_mail"]


def test_a_source_names_the_tools_that_read_it_in_the_block_that_the_owner_approves() -> None:
    with_reads = _check({**DNS, "reads": READS + [READS[0]]})  # a tool named twice is named once
    assert with_reads.fields["reads"] == READS and with_reads.hash != _check(DNS).hash
    # The names count in the hash in their order, so a tool added or taken out asks the owner again.
    assert _check({**DNS, "reads": READS[:2]}).hash != with_reads.hash
    assert _check({**DNS, "reads": READS}).hash == with_reads.hash
    # A check that says nothing about it is the check it always was.
    assert _check(DNS).as_dict() == {"kind": "dns", "where": "anywhere", "host": "example.test"}
    for raw in (HTTP, MCP, CMD, FILE):
        assert _check({**raw, "reads": READS[:1]}).fields["reads"] == READS[:1]
    body = sc.build_body(gives="Chats.", how="Read them.", since="The last report.", check=with_reads, fixes=[])
    assert sc.parse_check(body) == with_reads


def test_the_summary_the_owner_reads_beside_approve_says_which_tools_the_morning_may_call() -> None:
    summary = _check({**DNS, "reads": READS}).summary()
    assert summary == ("Looks up example.test every hour and wants it to resolve. The morning report may call "
                       "list_messages and unread_summary on chat; search_mail on mail.")
    assert "morning report" not in _check(DNS).summary()


def test_a_source_cannot_name_a_tool_of_verticals_or_anything_that_is_not_a_tool() -> None:
    for tool in ("mcp__verticals__delete", "mcp__Verticals__update", "mcp__verticals-desktop__schedule", "mcp__verticals_desktop__create"):
        assert "Verticals itself" in _refused({**DNS, "reads": [tool]}, "reads"), tool
    for bad in ("list_messages", "chat__list_messages", "mcp__chat", "mcp____x", "mcp__chat__*", " mcp__a__b", 7, None):
        assert "mcp__<server>__<tool>" in _refused({**DNS, "reads": [bad]}, "reads"), bad
    assert "list of 1 to" in _refused({**DNS, "reads": "mcp__chat__list_messages"}, "reads")  # one name is not a list
    assert "list of 1 to" in _refused({**DNS, "reads": []}, "reads")
    assert "list of 1 to" in _refused({**DNS, "reads": [f"mcp__s__t{n}" for n in range(sc.MAX_READS + 1)]}, "reads")
    assert len(_check({**DNS, "reads": [f"mcp__s__t{n}" for n in range(sc.MAX_READS)]}).fields["reads"]) == sc.MAX_READS


def test_the_apps_own_check_takes_no_reads() -> None:
    with pytest.raises(ValidationError):
        sc.Check.from_dict({"kind": "connections", "reads": READS[:1]}, app=True)


def test_a_source_read_through_claude_codes_servers_is_checked_by_asking_claude_code() -> None:
    reads = ["mcp__claude_ai_Gmail__search_threads", "mcp__claude_ai_Gmail__get_thread"]
    check = _check({"kind": "servers", "reads": reads})
    assert (check.where, check.gated, check.fields) == ("here", True, {"reads": reads})
    assert check.summary() == ("Asks Claude Code every hour whether claude_ai_Gmail answers. The morning report may call "
                               "search_threads and get_thread on claude_ai_Gmail.")
    assert "needs reads" in _refused({"kind": "servers"}, "reads")
    assert "must run here" in _refused({"kind": "servers", "reads": reads, "where": "anywhere"}, "where")
    _refused({"kind": "servers", "reads": reads, "url": "https://example.test/mcp"}, "url")
    assert sc.reading_servers([*reads, "mcp__icloud-mail__list_messages", "not a tool"]) == {"claude_ai_Gmail", "icloud-mail"}
