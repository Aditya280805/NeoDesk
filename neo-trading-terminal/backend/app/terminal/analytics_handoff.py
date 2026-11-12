"""Server-resolved advisory proposals, carried inside existing role payloads."""
from uuid import UUID, NAMESPACE_URL, uuid5

from .analytics_capture import CapturedAnalytics
from .analytics_contracts import AnalyticsEvidence, StrategyProposal
from .analytics_runtime import TOOLS_BY_ROLE


def resolve_selection(captured, result):
    selected = result.get('selected_proposal_id')
    if selected is None:
        return None
    if result['role'] != 'options_trading_analysis':
        raise ValueError('Only options may originate a strategy proposal')
    original = captured.for_role('options_trading_analysis')
    candidates = []
    for name, payload in result.get('evidence', {}).items():
        item = AnalyticsEvidence.model_validate(payload)
        if name not in original or item != original[name]:
            raise ValueError('Selection must cite unchanged consumed options evidence')
        candidates.extend(item.candidate_proposals)
    matches = [proposal for proposal in candidates if proposal.proposal_id == UUID(str(selected))]
    if len(matches) != 1:
        raise ValueError('Selected proposal is not uniquely bound to consumed evidence')
    return matches[0]


def project_proposal(captured, proposal, role):
    proposal = StrategyProposal.model_validate(proposal)
    if role not in ('portfolio_analysis','portfolio_risk'):
        raise ValueError('Invalid downstream proposal role')
    records, updated = [], []
    for name, payload in captured.evidence_json:
        if name in TOOLS_BY_ROLE[role]:
            item = AnalyticsEvidence.model_validate_json(payload)
            handoff = dict(schema_version='proposal-handoff.1', proposal=proposal.model_dump(mode='json'),
                assessment='CANNOT_ASSESS', basis='hypothetical_increment_only',
                reason='post_proposal_quotes_costs_margin_and_account_aggregation_not_captured')
            identity = uuid5(NAMESPACE_URL,f'{item.evidence_id}:{proposal.proposal_id}:{role}:handoff.1')
            item = item.model_copy(update={'evidence_id':identity,
                'metrics':{**item.metrics,'proposal_handoff':handoff},
                'coverage':{**item.coverage,'proposal_assessment':'unavailable','existing_metrics_basis':'original_capture_before_proposal'},
                'unavailable_reasons':{**item.unavailable_reasons,'post_proposal_assessment':handoff['reason']},
                'limitations':(*item.limitations,'Proposal is hypothetical. Original metrics are not a combined-account or post-proposal assessment.'),
                'status':'PARTIAL', 'source_refs':tuple(dict.fromkeys((*item.source_refs,str(proposal.evidence_id))))})
            payload = item.model_dump_json()
            updated.append(item)
        records.append((name,payload))
    return CapturedAnalytics(captured.owner_id,captured.session_generation,captured.context_json,tuple(records)), tuple(updated)
