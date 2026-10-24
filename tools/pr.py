#!/usr/bin/env python3
"""Open a pull request the way .agents/skills/verticals-pr says: the form first (`tools/pr_rules.py`, the same check GitHub
runs), then a second agent reads the diff and the text against the skill, and only on a pass `gh pr create`.

    python3 tools/pr.py --title "fix(web): keep the subtask caret beside its title" --body-file pr.md [--draft]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pr_rules  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / ".agents/skills/verticals-pr/SKILL.md"
ROLE = """You are the second reader of a pull request in this repository, before it opens. You did not write it and you
change nothing. Check the diff and the text against every rule of the skill below that code cannot check: code has already
checked the title's format and the sections. Open files with Read, Grep and Glob when the diff is cut or
a claim needs checking. Answer each rule with pass, fail or n/a and one line of why that points at the place. A fail is
something the author can fix; on a matter of taste, pass."""
GITHUB = re.compile(r"github\.com[:/]+([^/]+/[^/]+?)(?:\.git)?/*$")
DIFF_LIMIT = 150_000
REVIEW_SECONDS = 900
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "checks"],
    "properties": {
        "verdict": {"enum": ["pass", "fail"]},
        "checks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["rule", "result", "why"],
                "properties": {
                    "rule": {"type": "string"},
                    "result": {"enum": ["pass", "fail", "n/a"]},
                    "why": {"type": "string"},
                },
            },
        },
    },
}


class Refused(Exception):
    pass


def git(*args: str) -> str:
    done = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
    if done.returncode != 0:
        raise Refused(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout.strip()


def github_repo(remote: str) -> str:
    """A remote's repository on GitHub, as `owner/name`."""
    url = git("remote", "get-url", remote)
    found = GITHUB.search(url)
    if not found:
        raise Refused(f"the remote {remote} is not on GitHub: {url}")
    return found.group(1)


def branch_on_github() -> tuple[str, str]:
    """The repository the PR opens in (origin's) and the branch's name for it, once GitHub holds exactly this commit.
    A branch pushed to a fork goes by `owner:branch`, the way GitHub names a branch of another repository."""
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch in ("main", "HEAD"):
        raise Refused("work on a branch of its own, not on main")
    try:
        git("rev-parse", "--abbrev-ref", "@{u}")
    except Refused:
        raise Refused("push the branch first: git push -u origin HEAD") from None
    if git("rev-parse", "@{u}") != git("rev-parse", "HEAD"):
        raise Refused("GitHub does not have this commit yet: push first")
    name = git("config", f"branch.{branch}.merge").removeprefix("refs/heads/")
    base, pushed = github_repo("origin"), github_repo(git("config", f"branch.{branch}.remote"))
    return base, name if pushed.lower() == base.lower() else f"{pushed.split('/')[0]}:{name}"


def review(title: str, body: str) -> dict:
    """The second agent's verdict and its answer rule by rule."""
    exe = shutil.which("claude")
    if exe is None:
        raise Refused("the second reading needs Claude Code (`claude`) on this machine")
    diff = git("diff", "origin/main...HEAD")
    if len(diff) > DIFF_LIMIT:
        diff = diff[:DIFF_LIMIT] + "\n[the diff goes on: read the files themselves]"
    prompt = "\n\n".join([
        ROLE,
        SKILL.read_text(),
        f"# The pull request\n\nTitle: {title}\n\nText:\n{body}",
        f"Commits:\n{git('log', '--format=%h %s', 'origin/main..HEAD')}",
        f"Files:\n{git('diff', '--stat', 'origin/main...HEAD')}",
        f"Diff against main:\n{diff}",
    ])
    try:
        done = subprocess.run(
            [exe, "-p", "--output-format", "json", "--no-session-persistence", "--strict-mcp-config",
             "--mcp-config", '{"mcpServers":{}}', "--tools", "Read,Grep,Glob", "--json-schema", json.dumps(SCHEMA)],
            input=prompt, cwd=REPO, capture_output=True, text=True, timeout=REVIEW_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise Refused(f"the second reading gave no answer in {REVIEW_SECONDS // 60} minutes") from None
    try:
        answer = json.loads(done.stdout)
    except ValueError:
        answer = {}
    output = answer.get("structured_output") or {}
    if answer.get("is_error") or not output.get("checks"):
        raise Refused(f"the second reading did not answer: {(answer.get('result') or done.stderr or done.stdout)[:300]}")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--title", required=True)
    parser.add_argument("--body-file", required=True, type=Path)
    parser.add_argument("--draft", action="store_true")
    args = parser.parse_args()
    try:
        body = args.body_file.read_text()
        repo, head = branch_on_github()
        git("fetch", "-q", "origin", "main")
        form = pr_rules.problems(args.title, body)
        if form:
            raise Refused("the form:\n" + "\n".join(f"  - {problem}" for problem in form))
        reading = review(args.title, body)
    except (Refused, OSError) as exc:
        print(f"Not opened. {exc}", file=sys.stderr)
        return 1
    for check in reading["checks"]:
        print(f"{check['result']:>4}  {check['rule']}: {check['why']}")
    if reading.get("verdict") == "fail" or any(check["result"] == "fail" for check in reading["checks"]):
        print("Not opened: fix what failed, push and run this again.", file=sys.stderr)
        return 1
    opened = subprocess.run(
        ["gh", "pr", "create", "--repo", repo, "--base", "main", "--head", head, "--title", args.title,
         "--body-file", str(args.body_file), *(["--draft"] if args.draft else [])],
        cwd=REPO, capture_output=True, text=True,
    )
    if opened.returncode != 0:
        print(f"gh pr create: {opened.stderr.strip()}", file=sys.stderr)
        return 1
    print(opened.stdout.strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
