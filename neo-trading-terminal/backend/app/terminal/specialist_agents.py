"""Fresh read-only specialists; capability filtering remains server-side."""
from agno.agent import Agent

from app.terminal.agent_registry import register_agent
from app.terminal.agent_scope import report_scope, specialist_scope
from app.terminal.options_model import build_model
from app.terminal.options_snapshot import OptionsContext


def _build(agent_id, config, tools, scope, *, snapshot=None, stream: bool = False, parse_response: bool | None = None):
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
    agent_kwargs = {}
    if stream:
        agent_kwargs['stream'] = True
        agent_kwargs['stream_events'] = True
        agent_kwargs['parse_response'] = False if parse_response is None else parse_response
    elif parse_response is not None:
        agent_kwargs['parse_response'] = parse_response

    instructions = list(scope.instructions)
    if isinstance(snapshot, dict):
        if 'snapshot_id' in snapshot:
            snap_id = str(snapshot['snapshot_id'])
            instructions.append(f"MANDATORY CITATION: The current snapshot_id is exactly '{snap_id}'. You MUST set snapshot_ids to ['{snap_id}']. Do NOT use any contract_id, leg identifier, or other value.")
        if 'evidence_id' in snapshot:
            ev_id = str(snapshot['evidence_id'])
            instructions.append(f"MANDATORY CITATION: The current evidence_id is exactly '{ev_id}'. You MUST set evidence_ids to ['{ev_id}'].")
        if 'risk_report' in snapshot and isinstance(snapshot['risk_report'], dict) and 'report_id' in snapshot['risk_report']:
            rr_id = str(snapshot['risk_report']['report_id'])
            instructions.append(f"MANDATORY CITATION: The current risk report_id is exactly '{rr_id}'. You MUST set risk_report_ids to ['{rr_id}'].")
        if 'report_id' in snapshot and scope.scope in ('strategy', 'scan', 'alert', 'backtest'):
            rep_id = str(snapshot['report_id'])
            instructions.append(f"MANDATORY CITATION: The current report_id is exactly '{rep_id}'. You MUST set report_ids to ['{rep_id}'].")

    from .bound_chain_answer import bind_specialist_answer
    output_schema=bind_specialist_answer(scope.output_contract,snapshot)
    return Agent(name=agent_id, model=build_model(config), tools=tool_list,
                 tool_call_limit=2, output_schema=output_schema,
                 telemetry=False, markdown=False, instructions=instructions,
                 **agent_kwargs)


@register_agent('options_trading_analysis')
def build_options_trading_agent(config, snapshot, tools, *, scope, stream: bool = False, parse_response: bool | None = None):
    return _build('options_trading_analysis', config, tools, scope, snapshot=snapshot, stream=stream, parse_response=parse_response)


@register_agent('portfolio_analysis')
def build_portfolio_analysis_agent(config, snapshot, tools, *, scope, stream: bool = False, parse_response: bool | None = None):
    return _build('portfolio_analysis', config, tools, scope, snapshot=snapshot, stream=stream, parse_response=parse_response)


@register_agent('portfolio_risk')
def build_portfolio_risk_agent(config, snapshot, tools, *, scope, stream: bool = False, parse_response: bool | None = None):
    return _build('portfolio_risk', config, tools, scope, snapshot=snapshot, stream=stream, parse_response=parse_response)
