import json
import pytest
from pydantic import ValidationError


def test_mcp_config_requires_https_and_explicit_tools(tmp_path):
    from app.terminal.external_mcp import load_mcp_config
    path = tmp_path / 'mcp.json'
    path.write_text(json.dumps({'servers': {'news': {'url': 'https://news.example/mcp', 'enabled': True,
        'allowed_tools': ['search_news'], 'scopes': ['chain']}}}))
    assert load_mcp_config(path)['news'].allowed_tools == ['search_news']
    path.write_text(json.dumps({'servers': {'bad': {'url': 'http://example.com/mcp', 'enabled': True,
        'allowed_tools': ['search'], 'scopes': ['chain']}}}))
    with pytest.raises(ValidationError):
        load_mcp_config(path)
    path.write_text(json.dumps({'servers': {'bad': {'url': 'https://example.com/mcp', 'enabled': True,
        'allowed_tools': [], 'scopes': ['chain']}}}))
    with pytest.raises(ValidationError):
        load_mcp_config(path)


def test_disabled_and_scope_isolation(tmp_path, monkeypatch):
    from app.terminal.external_mcp import load_mcp_config, enabled_servers
    path = tmp_path / 'mcp.json'
    path.write_text(json.dumps({'servers': {
        'news': {'url': 'https://news.example/mcp', 'enabled': True, 'allowed_tools': ['news'], 'scopes': ['chain'], 'token_env': 'NEWS_TOKEN'},
        'off': {'url': 'https://off.example/mcp', 'enabled': False, 'allowed_tools': ['read'], 'scopes': ['portfolio']}}}))
    monkeypatch.setenv('NEWS_TOKEN', 'very-secret')
    config = load_mcp_config(path)
    assert list(enabled_servers(config, 'chain')) == ['news']
    assert not enabled_servers(config, 'portfolio')
    assert 'very-secret' not in repr(config)


def test_configuration_rejects_embedded_secrets_and_extra_fields(tmp_path):
    from app.terminal.external_mcp import load_mcp_config
    path = tmp_path / 'mcp.json'
    path.write_text(json.dumps({'servers': {'bad': {'url': 'https://user:password@example.com/mcp', 'enabled': True,
        'allowed_tools': ['news'], 'scopes': ['chain']}}}))
    with pytest.raises(ValidationError):
        load_mcp_config(path)


def test_connection_passes_allowlist_and_closes(tmp_path, monkeypatch):
    import asyncio
    from app.terminal.external_mcp import external_tools
    import agno.tools.mcp
    captured = []
    class FakeTools:
        def __init__(self, **kwargs):
            captured.append(kwargs)
            self.closed = False
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            self.closed = True
    monkeypatch.setattr(agno.tools.mcp, 'MCPTools', FakeTools)
    monkeypatch.setenv('NEWS_TOKEN', 'fixture-secret')
    path = tmp_path / 'mcp.json'
    path.write_text(json.dumps({'servers': {'news': {'url': 'https://news.example/mcp', 'enabled': True,
        'allowed_tools': ['read_news'], 'scopes': ['chain'], 'token_env': 'NEWS_TOKEN'}}}))
    async def scenario():
        async with external_tools(path, 'chain') as clients:
            assert len(clients) == 1
            client = clients[0]
            assert captured[0]['include_tools'] == ['read_news']
            assert captured[0]['headers']['Authorization'] == 'Bearer fixture-secret'
            assert captured[0]['tool_name_prefix'] == 'news'
        assert client.closed
    asyncio.run(scenario())
