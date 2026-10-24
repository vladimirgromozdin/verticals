"""What the chat tells its agent about the app's reports (docs/design/bug-reports.md, desktop/chat/prompt-report.md), and how it
finds the checkout of Verticals' source that a pull request needs. Sample folders only, made under a scratch directory."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _chat():
    spec = importlib.util.spec_from_file_location("verticals_desktop_chat_reports", ROOT / "desktop" / "chat" / "chat.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _prompt(args) -> str:
    """The prompt Claude is told, inline or, where the system caps a command line, in the file it is handed."""
    if "--append-system-prompt" in args:
        return args[args.index("--append-system-prompt") + 1]
    return Path(args[args.index("--append-system-prompt-file") + 1]).read_text(encoding="utf-8")


def _checkout(path: Path, name: str = "verticals") -> Path:
    """A folder that is a checkout of Verticals' source as far as the chat can tell: a git repository with the project's
    pyproject.toml and the desktop launcher in it."""
    (path / ".git").mkdir(parents=True)
    (path / "desktop").mkdir()
    (path / "desktop" / "launcher.py").write_text("")
    (path / "pyproject.toml").write_text(f'[project]\nname = "{name}"\nversion = "0.1.0"\n')
    return path


def _without_the_variable(chat, check, **env):
    """`check()` with VERTICALS_SOURCE out of the environment and `env` in it, and the environment as it was after."""
    kept = {name: os.environ.pop(name, None) for name in ("VERTICALS_SOURCE", *env)}
    os.environ.update(env)
    try:
        return check()
    finally:
        for name, value in kept.items():
            os.environ.pop(name, None)
            if value is not None:
                os.environ[name] = value


def test_the_prompt_says_what_a_report_is_and_how_a_design_and_its_pull_request_go(scratch_dir: Path) -> None:
    prompt = " ".join(_chat().report_prompt(None, False, home=scratch_dir, code_root=scratch_dir / "nowhere").split())
    assert prompt.startswith("## Reports from the app")
    # What a report is, and not to read it: its pictures are inside the text.
    assert "a document under reports/bugs/ or reports/requests/" in prompt
    # Reading a report is cheap, because its pictures come as placeholders; keeping them in a saved text keeps the pictures.
    assert "each comes as [picture 1], [picture 2] and so on, never its data" in prompt
    assert "keep those lines where they are and the pictures stay" in prompt and "take one out and the picture goes" in prompt
    assert "Never read a report" not in prompt and "doc_get" in prompt
    # A bug has the logs, a request none: the agent is told which is which, and that either holds the words and the pictures.
    assert "A bug is something that went wrong" in prompt and "a request is something that could be better" in prompt
    assert "and holds none" in prompt
    # Improve it: one design document in plain words, saved and linked to the report's task, then two lines saying it waits.
    assert '"Improve it" asks for a design' in prompt and "design/<short-name>.md" in prompt
    assert "link it to the report's task with doc_link" in prompt and "answer in two short lines that you are waiting" in prompt
    assert "If the task already has a design document, change that one" in prompt
    # The person comments and presses Check again; only once they agree is the change made, with tests first, in a checkout.
    assert "presses Check again" in prompt and "Only once they agree" in prompt
    assert "on a new branch" in prompt and "tests first" in prompt and "see them fail" in prompt
    assert "open a pull request the way the checkout's AGENTS.md says" in prompt and "so it joins the task's links" in prompt
    # Without what it needs it says so and stops: the task and its documents stay, only the pull request waits.
    assert "only the pull request waits" in prompt


def test_the_reports_come_in_every_turn_but_the_unattended_morning_one() -> None:
    chat = _chat()
    chat.JsonProcess, chat.which = _Proc, lambda provider: "claude"
    host = types.SimpleNamespace(claude_config=lambda session_id=None: Path("mcp.json"), workdir=Path("."))
    for settings, wanted in (({"permission": "manual"}, True), ({"permission": "board"}, True), ({"sources": "connected"}, False)):
        agent = chat.ClaudeAgent(host, _Session(), chat.clean_settings(settings), None)
        prompt = _prompt(agent.proc.args)
        assert ("## Reports from the app" in prompt) is wanted, settings
    assert "## Reports from the app" in chat.codex_instructions(chat.clean_settings({"provider": "codex"}))
    assert "## Reports from the app" not in chat.codex_instructions(chat.clean_settings({"provider": "codex", "sources": "connected"}))


class _Proc:
    def __init__(self, args, cwd, env, handle, exited):
        self.args = args

    def send(self, message):
        pass


class _Session:
    def emit(self, event):
        pass


def test_the_checkout_is_found_from_the_persons_word_then_the_code_then_the_usual_folders(scratch_dir: Path) -> None:
    chat = _chat()
    home = scratch_dir / "home"
    state = scratch_dir / "state"
    state.mkdir()
    nowhere = scratch_dir / "nowhere"

    def found(**kw):
        return _without_the_variable(chat, lambda: chat.find_source(state, home, code_root=kw.get("code_root", nowhere)))

    assert found() is None
    # The folders people clone into.
    usual = _checkout(home / "Developer" / "verticals")
    assert found() == usual
    # The repository the gateway runs from, when it is one, comes before them.
    code = _checkout(scratch_dir / "run-from-here")
    assert found(code_root=code) == code
    # The person's word for it comes first: `source` in the app's config.json (nothing else of that file is read) ...
    elsewhere = _checkout(scratch_dir / "elsewhere" / "any name")
    (state / "config.json").write_text(json.dumps({"token": "t-not-read", "password": "p-not-read", "source": str(elsewhere)}))
    assert found(code_root=code) == elsewhere
    # ... and VERTICALS_SOURCE before that.
    named = _checkout(scratch_dir / "named")
    os.environ["VERTICALS_SOURCE"] = str(named)
    try:
        assert chat.find_source(state, home, code_root=code) == named
    finally:
        del os.environ["VERTICALS_SOURCE"]
    # A folder that is not Verticals' source is not a checkout, whatever it is called or holds.
    (state / "config.json").write_text(json.dumps({"source": str(_checkout(scratch_dir / "other", name="something-else"))}))
    assert found() == usual
    (state / "config.json").write_text("not json")
    assert found() == usual
    assert not chat.is_checkout(scratch_dir / "missing") and not chat.is_checkout(scratch_dir / "other" / ".git")


def test_the_prompt_says_where_the_checkout_is_or_that_there_is_none(scratch_dir: Path) -> None:
    chat = _chat()
    home = scratch_dir / "home"
    home.mkdir()
    nowhere = scratch_dir / "nowhere"
    none = _without_the_variable(chat, lambda: chat.report_prompt(None, False, home=home, code_root=nowhere))
    assert "No checkout of Verticals' source was found on this Mac. Ask where it is; if there is none, say the pull request must wait." in none
    checkout = _checkout(home / "verticals")
    there = _without_the_variable(chat, lambda: chat.report_prompt(None, False, home=home, code_root=nowhere))
    assert f"The source of Verticals on this Mac is a git checkout at {checkout}." in there and "No checkout" not in there


def test_shaping_skills_are_named_only_when_this_mac_has_them_and_the_agent_can_use_them(scratch_dir: Path) -> None:
    chat = _chat()
    home = scratch_dir / "home"
    nowhere = scratch_dir / "nowhere"
    generic = "Use the skills you have for shaping and design, if there are any."

    def prompt(full: bool) -> str:
        return " ".join(_without_the_variable(chat, lambda: chat.report_prompt(None, full, home=home, code_root=nowhere)).split())

    # None here: generic words, and no name in the public repository's text.
    assert generic in prompt(True)
    for folder, name, with_file in ((".claude/skills", "team-shaping", True), (".agents/skills", "shaping", True),
                                    (".claude/skills", "shaping-notes", False), (".claude/skills", "typography", True)):
        (home / folder / name).mkdir(parents=True)
        if with_file:
            (home / folder / name / "SKILL.md").write_text("---\nname: x\n---\n")
    assert chat.shaping_skills(home) == ["shaping", "team-shaping"]
    # Named for an agent with its own tools, in the words the skill folder gives; not for one that has no tools to use them with.
    assert "Use these skills for it: shaping, team-shaping." in prompt(True) and generic not in prompt(True)
    assert generic in prompt(False) and "team-shaping" not in prompt(False)


def test_shaping_skills_come_from_the_folders_agents_env_picks(scratch_dir: Path) -> None:
    """With `CLAUDE_CONFIG_DIR` and `CODEX_HOME` set, the agents' skills are in those folders, not in `~/.claude` and `~/.codex`."""
    chat = _chat()
    home, claude, codex = scratch_dir / "home", scratch_dir / "claude", scratch_dir / "codex"
    for folder, name in ((home / ".claude", "work-shaping"), (home / ".agents", "shaping"), (claude, "team-shaping"),
                         (codex, "codex-shaping")):
        (folder / "skills" / name).mkdir(parents=True)
        (folder / "skills" / name / "SKILL.md").write_text("---\nname: x\n---\n")
    found = _without_the_variable(chat, lambda: chat.shaping_skills(home), CLAUDE_CONFIG_DIR=str(claude), CODEX_HOME=str(codex))
    assert found == ["codex-shaping", "shaping", "team-shaping"]
