"""Fresh read-only specialists; capability filtering remains server-side."""
from agno.agent import Agent

from app.terminal.agent_registry import register_agent
from app.terminal.agent_scope import report_scope, specialist_scope
from app.terminal.options_model import build_model
from app.terminal.options_snapshot import OptionsContext


def _build(agent_id, config, tools, scope, *, snapshot=None):
    if scope.agent_id != agent_id:
        raise ValueError('Specialist scope does not match agent')
    if scope.scope in ('strategy', 'scan', 'alert', 'backtest'):
        expected = report_scope(scope.scope, scope.stored_context['report_id'])
    else:
        context = OptionsContext(underlying=scope.stored_context.get('underlying', 'NIFTY'),
                                 exchange=scope.stored_context.get('exchange', 'NSE'),
                                 expiry=scope.stored_context.get('expiry')) if scope.scope == 'chain' else None
        expected = specialist_scope(scope.scope, context)
    if scope != expected:
        raise ValueError('Specialist contract does not match trusted scope')
    tool_list = list(tools) if isinstance(tools, (list, tuple)) else [tools]
    from .bound_chain_answer import bind_chain_answer
    output_schema=bind_chain_answer(scope.output_contract,snapshot) if scope.scope=='chain' else scope.output_contract
    return Agent(name=agent_id, model=build_model(config), tools=tool_list,
                 tool_call_limit=2, output_schema=output_schema,
                 telemetry=False, markdown=False, instructions=list(scope.instructions))


@register_agent('options_trading_analysis')
def build_options_trading_agent(config, snapshot, tools, *, scope):
    return _build('options_trading_analysis', config, tools, scope, snapshot=snapshot)


@register_agent('portfolio_analysis')
def build_portfolio_analysis_agent(config, snapshot, tools, *, scope):
    return _build('portfolio_analysis', config, tools, scope, snapshot=snapshot)


@register_agent('portfolio_risk')
def build_portfolio_risk_agent(config, snapshot, tools, *, scope):
    return _build('portfolio_risk', config, tools, scope, snapshot=snapshot)
