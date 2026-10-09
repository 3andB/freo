"""Acceptance harness must submit the intended form and prove authentication refusal."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import parse_qs
import pytest

spec = importlib.util.spec_from_file_location('accept_install', Path(__file__).resolve().parents[1] / 'scripts/accept-install.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


def test_setup_uses_setup_csrf_not_header_logout(monkeypatch):
    submitted = []
    def fetch(client, request, stage):
        if isinstance(request, str):
            return request, ('<form action="/admin/logout"><input name="csrf" value="logout"></form>'
                             '<form class="login-card" method="post"><input name="csrf" value="setup"></form>')
        submitted.append(parse_qs(request.data.decode()))
        return 'http://example.test/admin', ''
    monkeypatch.setattr(a, 'login_tools', lambda: SimpleNamespace(fetch=fetch))
    a.form(object(), 'http://example.test', '/admin/setup', {'password': 'private-fixture'})
    assert submitted == [{'password': ['private-fixture'], 'csrf': ['setup']}]


@pytest.mark.parametrize('status', [400, 401, 500])
def test_bootstrap_rejection_requires_401(monkeypatch, status):
    def fetch(*args):
        return '', '<form class="login-card"><input name="csrf" value="login"></form>'
    def open_request(*args, **kwargs):
        raise HTTPError('http://example.test/admin/login', status, 'fixture', {}, None)
    monkeypatch.setattr(a, 'login_tools', lambda: SimpleNamespace(fetch=fetch))
    invoke = lambda: a.form(SimpleNamespace(open=open_request), 'http://example.test', '/admin/login', {}, rejected=True)
    if status == 401:
        assert invoke()[0].endswith('/admin/login')
    else:
        with pytest.raises(RuntimeError, match='authentication rejection'):
            invoke()
