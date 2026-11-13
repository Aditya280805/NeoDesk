from uuid import UUID
import pytest
from pydantic import ValidationError
from app.terminal.agent_scope import PortfolioAnalysisAnswer, PortfolioRiskAnswer
from app.terminal.bound_chain_answer import bind_specialist_answer
from app.terminal.options_agent import OptionsAgent
from app.terminal.agent_harness import HarnessError

EVIDENCE = '11111111-1111-4111-8111-111111111111'
REPORT = '22222222-2222-4222-8222-222222222222'

@pytest.mark.parametrize('contract', [PortfolioAnalysisAnswer, PortfolioRiskAnswer])
def test_bound_citations_reject_other_valid_uuids(contract):
    bound = bind_specialist_answer(contract, {'evidence_id': EVIDENCE, 'risk_report': {'report_id': REPORT}})
    payload = {'answer': 'Evidence explanation', 'evidence_ids': [EVIDENCE]}
    if contract is PortfolioRiskAnswer:
        payload['risk_report_ids'] = [REPORT]
    assert bound.model_validate(payload).answer
    payload['evidence_ids'] = [REPORT]
    with pytest.raises(ValidationError):
        bound.model_validate(payload)
    assert bound.model_json_schema()['properties']['evidence_ids']['items']['const'] == EVIDENCE


def test_schema_failure_diagnostics_do_not_retain_input():
    agent = object.__new__(OptionsAgent)
    try:
        PortfolioAnalysisAnswer.model_validate({'answer': 'private account text', 'evidence_ids': []})
    except ValidationError as error:
        detail = {}
        state, mapped = agent._map_chat_error(error, 'synthetic-run', detail)
    assert state == 'failed'
    assert detail == {'validation_types': ['too_short'], 'failure_reason': 'invalid_schema'}
    assert 'private' not in str(detail)
    assert mapped.headers['X-Options-Error-Code'] == 'invalid_schema'


def test_harness_timeout_is_a_timeout_not_model_configuration_error():
    detail = {}
    state, mapped = object.__new__(OptionsAgent)._map_chat_error(HarnessError('timeout'), 'run', detail)
    assert state == 'timeout' and mapped.status_code == 504
