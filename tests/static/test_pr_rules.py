"""How a pull request is opened here (.agents/skills/verticals-pr): the form `tools/pr_rules.py` checks on both sides, the
Claude Code hook that sends `gh pr create` through `tools/pr.py`, and the files that wire them."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIX = "## Bug\n\nIt breaks.\n\n## Fix\n\nIt holds.\n\n## Testing\n\n- ran it"


def _rules():
    spec = importlib.util.spec_from_file_location("verticals_pr_rules", ROOT / "tools" / "pr_rules.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _opener():
    spec = importlib.util.spec_from_file_location("verticals_pr_opener", ROOT / "tools" / "pr.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _gate(event: object) -> subprocess.CompletedProcess:
    raw = event if isinstance(event, str) else json.dumps(event)
    return subprocess.run([sys.executable, str(ROOT / "tools" / "pr_gate.py")], input=raw, capture_output=True, text=True)


def test_a_pr_in_form_passes() -> None:
    rules = _rules()
    title = "fix(web): keep the subtask caret beside its title"
    assert rules.problems(title, FIX) == []
    feature = "feat: pick which part of the version goes up"
    assert rules.problems(feature, "## What\n\nA choice.\n\n## Testing\n\n- ran it") == []
    assert rules.problems("ci(release): bump by choice", FIX) == []


def test_each_break_of_the_form_is_named() -> None:
    rules = _rules()

    def broken(title: str, body: str = FIX) -> str:
        found = rules.problems(title, body)
        assert len(found) == 1, found
        return found[0]

    assert "type(scope): what changes" in broken("Fix the caret")
    assert "at most 72" in broken("fix: " + "x" * 70)
    assert "English" in broken("fix: каретка на месте")
    assert "## Testing" in broken("fix: keep it", FIX.replace("## Testing", "## Checks"))
    assert "## Bug" in broken("fix: keep it", "## What\n\nIt.\n\n## Testing\n\n- ran it")
    assert "## What" in broken("feat: add it", "## Testing\n\n- ran it")


def test_the_hook_sends_a_bare_gh_pr_create_through_tools_pr() -> None:
    refused = _gate({"tool_name": "Bash", "tool_input": {"command": "git push && gh pr create --title t --body b"}})
    assert refused.returncode == 2 and "tools/pr.py" in refused.stderr
    for command in ('python3 tools/pr.py --title "fix: x" --body-file pr.md', 'grep -n "gh pr create" README.md',
                    "gh pr view 64", "gh pr edit 64 --body-file pr.md"):
        assert _gate({"tool_name": "Bash", "tool_input": {"command": command}}).returncode == 0, command
    assert _gate({"tool_name": "Read", "tool_input": {"file_path": "gh pr create"}}).returncode == 0
    assert _gate("not json").returncode == 0


def test_a_branch_pushed_to_a_fork_opens_in_origins_repository_by_owner_and_name(tmp_path: Path) -> None:
    opener = _opener()
    opener.REPO = tmp_path
    for args in (["init", "-q", "-b", "main"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty",
                 "-m", "x"], ["remote", "add", "origin", "https://github.com/Acme/verticals.git"],
                 ["remote", "add", "fork", "git@github.com:someone/verticals.git"], ["switch", "-q", "-c", "fix/caret"]):
        opener.git(*args)
    for remote, head in (("fork", "someone:fix/caret"), ("origin", "fix/caret")):
        opener.git("update-ref", f"refs/remotes/{remote}/fix/caret", "HEAD")
        opener.git("branch", "-q", "--set-upstream-to", f"{remote}/fix/caret")
        assert opener.branch_on_github() == ("Acme/verticals", head)


def test_the_hook_the_check_and_the_skill_are_wired_in() -> None:
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text())
    [entry] = settings["hooks"]["PreToolUse"]
    assert entry["matcher"] == "Bash" and "tools/pr_gate.py" in entry["hooks"][0]["command"]
    assert "python3 tools/pr_rules.py" in (ROOT / ".github" / "workflows" / "pr-rules.yml").read_text()
    opener = (ROOT / "tools" / "pr.py").read_text()
    assert "pr_rules.problems" in opener and ".agents/skills/verticals-pr/SKILL.md" in opener
    assert (ROOT / ".claude" / "skills" / "verticals-pr" / "SKILL.md").read_text().startswith("---\nname: verticals-pr\n")
