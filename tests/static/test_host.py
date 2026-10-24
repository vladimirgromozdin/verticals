"""verticals/host: the one place that knows the operating system. Its two halves must name the same things, or code that
works on one system fails on the other with a NameError nobody here would see. Read as files, not imported: windows.py
reads Windows-only constants at import."""

from __future__ import annotations

import ast
from pathlib import Path

HOST = Path(__file__).resolve().parents[2] / "verticals" / "host"
REPO = HOST.parents[1]


def _names(path: Path) -> tuple[list[str], set[str]]:
    """What a module promises in `__all__`, and what it defines at its top level."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    promised: list[str] = []
    defined: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            defined.add(node.name)
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        for target in targets:
            if isinstance(target, ast.Name):
                defined.add(target.id)
                if target.id == "__all__":
                    promised = [elt.value for elt in node.value.elts]
    return promised, defined


def test_both_systems_name_the_same_things() -> None:
    posix, windows = _names(HOST / "posix.py"), _names(HOST / "windows.py")
    assert posix[0] == windows[0], "posix.py and windows.py must list the same __all__, in the same order"
    for name, (promised, defined) in (("posix.py", posix), ("windows.py", windows)):
        missing = [n for n in promised if n not in defined]
        assert not missing, f"{name} promises but does not define: {missing}"


def test_only_host_looks_at_the_system() -> None:
    """Everywhere else asks verticals.host; a check of os.name or sys.platform elsewhere is a platform branch leaking."""
    leaks = []
    for folder in ("verticals", "tools", "desktop"):
        for path in (REPO / folder).rglob("*.py"):
            # Build output (desktop/dist holds a bundled app with Python's own library) is not the repository's code.
            if HOST in path.parents or "dist" in path.relative_to(REPO).parts:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and \
                        (node.value.id, node.attr) in {("os", "name"), ("sys", "platform")}:
                    leaks.append(f"{path.relative_to(REPO)}:{node.lineno}")
    assert not leaks, f"ask verticals.host instead: {leaks}"
