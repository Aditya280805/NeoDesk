"""Constrain generated citations to the one already captured chain snapshot."""
from typing import Literal
from pydantic import create_model,Field

def bind_chain_answer(contract,snapshot):
    identity=snapshot.get('snapshot_id') if isinstance(snapshot,dict) else None
    if not isinstance(identity,str) or not identity or 'snapshot_ids' not in contract.model_fields:
        return contract
    return create_model('BoundChainAnswer',__base__=contract,
        snapshot_ids=(list[Literal[identity]],Field(min_length=1,max_length=1)))
