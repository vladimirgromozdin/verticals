"""The desktop's chosen access and source folder reach the actual CLI launch."""

import importlib.util
import json
import os
import sys
from pathlib import Path


def _chat():
    spec = importlib.util.spec_from_file_location('desktop_code_access', Path(__file__).resolve().parents[2] / 'desktop/chat/chat.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_codex_keeps_its_command_tool_while_other_mcp_servers_stay_isolated(tmp_path: Path) -> None:
    chat = _chat()
    home = tmp_path / 'codex-home'
    home.mkdir()
    (home / 'config.toml').write_text('[mcp_servers.unrelated]\ncommand = "unrelated-server"\n')
    saved = os.environ.get('CODEX_HOME')
    os.environ['CODEX_HOME'] = str(home)
    try:
        state = tmp_path / 'state'
        state.mkdir()
        host = chat.Chat(state, 'http://127.0.0.1:8281/mcp', 'test-only-token')
        args = chat.codex_args(host)
    finally:
        if saved is None:
            os.environ.pop('CODEX_HOME', None)
        else:
            os.environ['CODEX_HOME'] = saved
    assert 'features.shell_tool=false' not in args, 'Full access must retain the command tool'
    assert 'mcp_servers.unrelated.enabled=false' in args


def test_a_configured_checkout_is_the_workspace_for_new_work(tmp_path: Path) -> None:
    chat = _chat()
    source = tmp_path / 'a checkout'
    (source / '.git').mkdir(parents=True)
    (source / 'desktop').mkdir()
    (source / 'desktop/launcher.py').write_text('')
    (source / 'pyproject.toml').write_text('[project]\nname = "verticals"\n')
    state = tmp_path / 'state'
    state.mkdir()
    (state / 'config.json').write_text(json.dumps({'source': str(source)}))
    host = chat.Chat(state, 'http://127.0.0.1:8281/mcp', 'test-only-token')
    assert host.workdir == source
