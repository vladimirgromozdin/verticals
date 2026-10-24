"""Board startup and source reads do not depend on access to an optional code checkout."""
import json
import threading
from types import SimpleNamespace
import uuid

import pytest

from tests.static.test_agent_code_access import _chat


def configured(tmp_path):
    source = tmp_path / 'selected-checkout'
    (source / '.git').mkdir(parents=True)
    (source / 'desktop').mkdir()
    (source / 'desktop/launcher.py').write_text('')
    (source / 'pyproject.toml').write_text('[project]\nname="verticals"\n')
    state = tmp_path / 'state'
    state.mkdir()
    (state / 'config.json').write_text(json.dumps({'source': str(source)}))
    return source, state


def test_gateway_starts_while_checkout_validation_is_waiting_for_access(tmp_path, monkeypatch):
    module = _chat()
    source, state = configured(tmp_path)
    gate, ready, entered = threading.Event(), threading.Event(), threading.Event()
    original = module.is_checkout
    def waiting(path):
        if path == source:
            entered.set()
            gate.wait(5)
        return original(path)
    monkeypatch.setattr(module, 'is_checkout', waiting)
    hosts = []
    def create():
        hosts.append(module.Chat(state, 'http://127.0.0.1:9/mcp', 'synthetic', watch_every=0))
        ready.set()
    thread = threading.Thread(target=create)
    thread.start()
    try:
        assert ready.wait(1), 'the gateway is waiting for optional checkout access'
        assert not entered.is_set(), 'startup opened the checkout before any code request'
    finally:
        gate.set()
        thread.join(5)
        for host in hosts:
            host.shutdown()


@pytest.mark.parametrize('provider', ['claude', 'codex'])
def test_report_agent_uses_the_private_workspace_and_preserves_code_selection(tmp_path, monkeypatch, provider):
    module = _chat()
    source, state = configured(tmp_path)
    host = module.Chat(state, 'http://127.0.0.1:9/mcp', 'synthetic', watch_every=0)
    host.api = lambda *args: {'sources': []}
    calls = []
    class Process:
        def __init__(self, argv, cwd, *args): calls.append(cwd)
        def request(self, *args, **kwargs): return {'thread': {'id': 'synthetic-thread'}}
        def notify(self, *args): pass
        def send(self, *args): pass
    monkeypatch.setattr(module, 'which', lambda name: name)
    monkeypatch.setattr(module, 'JsonProcess', Process)
    monkeypatch.setattr(module, 'RpcProcess', Process)
    codex = tmp_path / 'codex'
    codex.mkdir()
    (codex / 'config.toml').write_text('')
    monkeypatch.setenv('CODEX_HOME', str(codex))
    checked = []
    def run(argv, *, cwd, **kwargs):
        checked.append(cwd)
        return SimpleNamespace(returncode=0, stdout='[{"name":"verticals_desktop","enabled":true}]')
    monkeypatch.setattr(module.subprocess, 'run', run)
    settings = module.clean_settings({'provider': provider, 'sources': 'connected'})
    session = SimpleNamespace(id=str(uuid.uuid4()), settings=settings, emit=lambda event: None)
    try:
        module.AGENT_CLASSES[provider](host, session, settings, None)
        assert calls == [state / 'chat-workspace']
        assert checked == ([state / 'chat-workspace'] if provider == 'codex' else [])
        assert host.workdir == source, 'ordinary code work must retain the selected checkout'
    finally:
        host.shutdown()


def test_report_resume_does_not_inherit_a_code_checkout(tmp_path, monkeypatch):
    module = _chat()
    source, state = configured(tmp_path)
    host = module.Chat(state, 'http://127.0.0.1:9/mcp', 'synthetic', watch_every=0)
    key = str(uuid.uuid4())
    host.update(key, provider='codex', sessionId='synthetic-thread', cwd=str(source))
    calls = []
    class Agent:
        session_id = 'synthetic-thread'
        def __init__(self, *args, cwd=None, **kwargs): calls.append(cwd)
        def send(self, text): pass
        def close(self): pass
    monkeypatch.setitem(module.AGENT_CLASSES, 'codex', Agent)
    monkeypatch.setattr(host, 'open_answer', lambda *args: None)
    try:
        host.start_turn(host.session(key), 'Read the sources', {}, module.clean_settings({'provider': 'codex', 'sources': 'connected'}))
        assert calls == [state / 'chat-workspace']
        assert host.load()[key]['cwd'] == str(state / 'chat-workspace')
    finally:
        host.shutdown()


def test_source_isolation_check_does_not_read_project_configuration(tmp_path, monkeypatch):
    module = _chat()
    source, state = configured(tmp_path)
    host = module.Chat(state, 'http://127.0.0.1:9/mcp', 'synthetic', watch_every=0)
    codex = tmp_path / 'codex'
    codex.mkdir()
    (codex / 'config.toml').write_text('')
    monkeypatch.setenv('CODEX_HOME', str(codex))
    calls = []
    def run(argv, *, cwd, **kwargs):
        calls.append(cwd)
        return SimpleNamespace(returncode=0, stdout='[{"name":"verticals_desktop","enabled":true}]')
    monkeypatch.setattr(module.subprocess, 'run', run)
    monkeypatch.setattr(module, 'which', lambda name: name)
    try:
        module.codex_args(host, reads={})
        assert calls == [state / 'chat-workspace']
    finally:
        host.shutdown()


@pytest.mark.parametrize('provider', ['claude', 'codex'])
def test_account_probe_uses_the_private_workspace(tmp_path, monkeypatch, provider):
    module = _chat()
    _, state = configured(tmp_path)
    host = module.Chat(state, 'http://127.0.0.1:9/mcp', 'synthetic', watch_every=0)
    calls = []
    class Process:
        def __init__(self, argv, cwd, env, callback, *args):
            calls.append(cwd)
            self.callback = callback
        def request(self, *args, **kwargs): return {'data': []}
        def notify(self, *args): pass
        def send(self, message):
            self.callback({'type': 'control_response', 'response': {
                'request_id': message['request_id'], 'response': {}}})
        def close(self): pass
    monkeypatch.setattr(module, 'which', lambda name: name)
    monkeypatch.setattr(module, 'JsonProcess', Process)
    monkeypatch.setattr(module, 'RpcProcess', Process)
    monkeypatch.setattr(module, 'codex_args', lambda *args, **kwargs: ['codex', 'app-server'])
    try:
        getattr(host, '_probe_' + provider)()
        assert calls == [state / 'chat-workspace']
    finally:
        host.shutdown()


def test_explicit_classifier_prompt_does_not_discover_a_checkout(tmp_path, monkeypatch):
    module = _chat()
    _, state = configured(tmp_path)
    host = module.Chat(state, 'http://127.0.0.1:9/mcp', 'synthetic', watch_every=0)
    class Process:
        def __init__(self, *args): pass
        def send(self, *args): pass
    def unused_prompt(*args, **kwargs):
        pytest.fail('an explicit classifier prompt must not inspect source code')
    monkeypatch.setattr(module, 'JsonProcess', Process)
    monkeypatch.setattr(module, 'report_prompt', unused_prompt)
    monkeypatch.setattr(module, 'which', lambda name: name)
    settings = module.clean_settings({'provider': 'claude'})
    seat = SimpleNamespace(settings=settings, emit=lambda event: None)
    try:
        module.ClaudeAgent(host, seat, settings, None, prompt='Classify a synthetic report')
    finally:
        host.shutdown()
