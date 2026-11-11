"""
Decorator-based agent factory registry.

Adapted from agent-template/src/core/agents/registry.py, hardened for
NeoDesk's per-request security model.  The registry stores *factories*
(callables that accept config/snapshot/tools and return an Agent), not
live agent instances.  Each factory is invoked fresh per request so that
capability tokens and token budgets are never shared.
"""
from typing import Callable

from agno.agent import Agent
from agno.team import Team

AGENT_REGISTRY: dict[str, Callable[..., Agent | Team]] = {}


def register_agent(name: str):
    """Register an agent factory by name.

    Usage::

        @register_agent("options_chain_monitor")
        def build_chain_agent(config, snapshot, tools, *, scope=None):
            return Agent(...)

    The original function is preserved as ``fn.__wrapped__`` so that
    tests can access it directly when monkeypatching the module-level
    factory reference.
    """
    def decorator(fn: Callable[..., Agent | Team]) -> Callable[..., Agent | Team]:
        if name in AGENT_REGISTRY:
            raise ValueError(f"Duplicate agent registration: '{name}'")
        AGENT_REGISTRY[name] = fn
        fn.__wrapped__ = fn  # keep unwrapped reference for test fixtures
        return fn
    return decorator


def get_agent(name: str) -> Callable[..., Agent | Team]:
    """Look up a registered agent factory by name."""
    if name not in AGENT_REGISTRY:
        raise KeyError(
            f"Agent '{name}' not registered. Available: {list(AGENT_REGISTRY)}"
        )
    return AGENT_REGISTRY[name]


def list_agents() -> list[str]:
    """Return the names of all registered agent factories."""
    return list(AGENT_REGISTRY.keys())
