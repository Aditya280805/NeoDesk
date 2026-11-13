"""Constrain generated citations to the one already captured chain snapshot."""
from typing import Literal
from pydantic import create_model,Field

def bind_chain_answer(contract,snapshot):
    identity=snapshot.get('snapshot_id') if isinstance(snapshot,dict) else None
    if not isinstance(identity,str) or not identity or 'snapshot_ids' not in contract.model_fields:
        return contract
    return create_model('BoundChainAnswer',__base__=contract,
        snapshot_ids=(list[Literal[identity]],Field(min_length=1,max_length=1)))


def bind_specialist_answer(contract, snapshot):
    if 'snapshot_ids' in contract.model_fields:
        return bind_chain_answer(contract, snapshot)
    if not isinstance(snapshot, dict):
        return contract
    fields = {}
    for name, identity in (('evidence_ids', snapshot.get('evidence_id')),
                           ('risk_report_ids', (snapshot.get('risk_report') or {}).get('report_id'))):
        if name in contract.model_fields and identity:
            fields[name] = (list[Literal[str(identity)]], Field(min_length=1, max_length=1))
    return create_model('Bound' + contract.__name__, __base__=contract, **fields) if fields else contract
