from datetime import UTC,datetime

import pytest
from pydantic import ValidationError

from app.terminal.analytics_contracts import AnalyticsEvidence


def evidence():
    return {'tool':AnalyticsEvidence(calculation_version='fixture.1',observed_at=None,retrieved_at=datetime.now(UTC),status='PARTIAL',
        metrics={'pcr_oi':2,'nested':{'loss':10},'missing':None})}


def test_short_choices_resolve_to_exact_captured_scalar_without_model_ids():
    from app.terminal.analytics_selection import bind_choices
    loaded=evidence()
    choices=bind_choices(loaded)
    reference=next(ref for ref,row in choices.payload['claim_choices'].items() if row['path']==['pcr_oi'])
    result=choices.resolve({'interpretation':'Coverage is limited.','claim_refs':[reference],'selected_proposal_ref':None})
    assert result.claims[0].evidence_id==loaded['tool'].evidence_id
    assert result.claims[0].path==('pcr_oi',)
    assert choices.payload['claim_choices'][reference]['value']==2
    assert 'evidence_id' not in choices.payload['claim_choices'][reference]
    assert result.selected_proposal_id is None
    with pytest.raises(ValidationError): choices.resolve({'interpretation':'Limited.','claim_refs':['unbound']})
    with pytest.raises(ValidationError): choices.resolve({'interpretation':'Limited.','selected_proposal_ref':'invented'})


def test_choices_are_bounded_and_reject_model_supplied_values_and_duplicate_refs():
    from app.terminal.analytics_selection import bind_choices
    loaded=evidence()
    loaded['tool']=loaded['tool'].model_copy(update={'metrics':{f'value_{i}':i for i in range(1000)}})
    choices=bind_choices(loaded)
    assert len(choices.payload['claim_choices'])==32
    reference=next(iter(choices.payload['claim_choices']))
    with pytest.raises((ValueError,ValidationError)):
        choices.resolve({'interpretation':'Limited.','claim_refs':[reference,reference]})
    with pytest.raises(ValidationError):
        choices.resolve({'interpretation':'Limited.','claim_refs':[reference],'value':999})


def test_proposal_choice_resolves_only_supplied_candidate():
    from app.terminal.analytics_selection import bind_choices
    from test_analytics_handoff import fixture
    captured,item,proposal=fixture()
    choices=bind_choices(captured.for_role('options_trading_analysis'))
    result=choices.resolve({'interpretation':'Hypothetical proposal.','selected_proposal_ref':'p0'})
    assert result.selected_proposal_id==proposal.proposal_id
    with pytest.raises(ValidationError): choices.resolve({'interpretation':'Limited.','selected_proposal_ref':str(proposal.proposal_id)})
