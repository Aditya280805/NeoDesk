"""Fresh read-only specialists; capability filtering remains server-side."""
from agno.agent import Agent

from app.terminal.agent_registry import register_agent
from app.terminal.agent_scope import report_scope, specialist_scope
from app.terminal.options_model import build_model
from app.terminal.options_snapshot import OptionsContext


def _build(agent_id, config, tools, scope):
    if scope.agent_id != agent_id:
        raise ValueError('Specialist scope does not match agent')
    if scope.scope in ('strategy', 'scan', 'alert', 'backtest'):
        expected = report_scope(scope.scope, scope.stored_context['report_id'])
    else:
        context = OptionsContext.model_validate(scope.stored_context) if scope.scope == 'chain' else None
        expected = specialist_scope(scope.scope, context)
    if scope != expected:
        raise ValueError('Specialist contract does not match trusted scope')
    return Agent(name=agent_id, model=build_model(config), tools=list(tools),
                 tool_call_limit=2, output_schema=scope.output_contract,
                 telemetry=False, markdown=False, instructions=list(scope.instructions))


@register_agent('options_trading_analysis')
def build_options_trading_agent(config, snapshot, tools, *, scope):
    return _build('options_trading_analysis', config, tools, scope)


@register_agent('portfolio_analysis')
def build_portfolio_analysis_agent(config, snapshot, tools, *, scope):
    return _build('portfolio_analysis', config, tools, scope)


@register_agent('portfolio_risk')
def build_portfolio_risk_agent(config, snapshot, tools, *, scope):
    return _build('portfolio_risk', config, tools, scope)
