from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.terminal import agent_scope as scopes
from app.terminal.options_snapshot import OptionsContext


@pytest.mark.parametrize('scope,agent,tool', [
    ('chain', 'options_trading_analysis', 'get_option_snapshot'),
    ('portfolio', 'portfolio_analysis', 'get_portfolio_analysis_snapshot'),
    ('risk', 'portfolio_risk', 'get_portfolio_risk_report'),
])
def test_specialist_mapping(scope, agent, tool):
    definition = scopes.specialist_scope(scope, OptionsContext() if scope == 'chain' else None)
    assert definition.agent_id == agent
    assert definition.allowed_tool == tool


@pytest.mark.parametrize('kind', ['strategy', 'scan', 'alert', 'backtest'])
def test_reports_belong_to_options_specialist(kind):
    assert scopes.report_scope(kind, uuid4()).agent_id == 'options_trading_analysis'


@pytest.mark.parametrize('scope,context', [('unknown', None), ('chain', None), ('risk', OptionsContext()), ('portfolio', OptionsContext())])
def test_invalid_specialist_context_rejected(scope, context):
    with pytest.raises(ValueError):
        scopes.specialist_scope(scope, context)


def test_analysis_contract_rejects_risk_and_invalid_evidence():
    model = scopes.PortfolioAnalysisAnswer
    assert model(answer=' Evidence ', evidence_ids=[uuid4()]).answer == 'Evidence'
    for fields in [dict(answer=' ', evidence_ids=[uuid4()]),
                   dict(answer='ok', evidence_ids=['invalid']),
                   dict(answer='ok', evidence_ids=[uuid4()], risk_report_ids=[uuid4()]),
                   dict(answer='ok', evidence_ids=[uuid4(), uuid4()])]:
        with pytest.raises(ValidationError):
            model(**fields)


def test_risk_contract_requires_exact_evidence_and_report():
    model = scopes.PortfolioRiskAnswer
    assert model(answer='ok', evidence_ids=[uuid4()], risk_report_ids=[uuid4()])
    for fields in [dict(answer='ok', evidence_ids=[uuid4()]),
                   dict(answer='ok', evidence_ids=[uuid4()], risk_report_ids=[]),
                   dict(answer='ok', evidence_ids=[uuid4()], risk_report_ids=[uuid4()], holdings=[])]:
        with pytest.raises(ValidationError):
            model(**fields)


def test_router_contract_is_closed():
    for scope in ('chain', 'portfolio', 'risk', 'clarify'):
        assert scopes.RouteAnswer(scope=scope).scope == scope
    with pytest.raises(ValidationError):
        scopes.RouteAnswer(scope='execute')
    with pytest.raises(ValidationError):
        scopes.RouteAnswer(scope='risk', tools=['get_portfolio_snapshot'])


@pytest.mark.parametrize('scope', ['chain', 'portfolio', 'risk'])
def test_registered_factories_are_fresh_and_scope_restricted(scope, monkeypatch):
    from agno.models.openai import OpenAIChat
    from app.terminal import specialist_agents
    from app.terminal.agent_registry import get_agent
    monkeypatch.setattr(specialist_agents, 'build_model', lambda config: OpenAIChat(id='test', api_key='synthetic'))
    definition = scopes.specialist_scope(scope, OptionsContext() if scope == 'chain' else None)
    factory = get_agent(definition.agent_id)
    first = factory(None, {}, [], scope=definition)
    second = factory(None, {}, [], scope=definition)
    assert first is not second and first.model is not second.model
    assert first.output_schema is definition.output_contract
    assert first.tools == [] and first.tool_call_limit == 2
    wrong = scopes.specialist_scope('risk' if scope != 'risk' else 'portfolio')
    with pytest.raises(ValueError):
        factory(None, {}, [], scope=wrong)
