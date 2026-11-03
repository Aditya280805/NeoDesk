"""Explicit administrator-controlled external MCP connections."""
import json
import os
from contextlib import asynccontextmanager, AsyncExitStack
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    url: str = Field(max_length=2048)
    enabled: bool = False
    allowed_tools: list[str] = Field(min_length=1, max_length=20)
    scopes: list[Literal['chain', 'portfolio']] = Field(min_length=1, max_length=2)
    token_env: str | None = Field(default=None, pattern=r'^[A-Z][A-Z0-9_]{1,127}$')

    @field_validator('url')
    @classmethod
    def secure_url(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('External MCP URL must use HTTPS without credentials, query or fragment')
        return value

    @field_validator('allowed_tools')
    @classmethod
    def tool_names(cls, value):
        import re
        if len(set(value)) != len(value) or any(not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', name) for name in value):
            raise ValueError('Tool names must be unique identifiers')
        return value


class MCPConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    servers: dict[str, ServerConfig] = Field(default_factory=dict, max_length=10)


def load_mcp_config(path: Path):
    import re
    if not path.exists():
        return {}
    if path.stat().st_size > 65536:
        raise ValueError('MCP configuration exceeds size limit')
    servers = MCPConfig.model_validate(json.loads(path.read_text(encoding='utf-8'))).servers
    if any(not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}', name) for name in servers):
        raise ValueError('External MCP server names must be lowercase identifiers')
    return servers


def enabled_servers(servers, scope):
    return {name: server for name, server in servers.items() if server.enabled and scope in server.scopes}


@asynccontextmanager
async def external_tools(path: Path, scope: str):
    from agno.tools.mcp import MCPTools
    servers = enabled_servers(load_mcp_config(path), scope)
    async with AsyncExitStack() as stack:
        tools = []
        for name, server in servers.items():
            token = os.environ.get(server.token_env) if server.token_env else None
            if server.token_env and not token:
                raise ValueError(f'Missing environment credential for external MCP server {name}')
            headers = {'Authorization': f'Bearer {token}'} if token else {}
            client = MCPTools(url=server.url, transport='streamable-http', headers=headers,
                              include_tools=server.allowed_tools, timeout_seconds=10,
                              tool_name_prefix=name)
            tools.append(await stack.enter_async_context(client))
        yield tools
