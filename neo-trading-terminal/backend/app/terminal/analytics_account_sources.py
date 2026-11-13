"""Explicit declared-input adapter; imports never certify account completeness."""
import hashlib
import json
from .analytics_remaining_contracts import CapturedRiskBundle,SourceStamp
from .analytics_remaining_risk import evaluate_remaining_risk

def declared_account_risk(owner,generation,observed_at,positions,reference):
    payload=json.dumps(positions,sort_keys=True,default=str,allow_nan=False)
    bundle=CapturedRiskBundle(owner_id=owner,session_generation=generation,as_of=observed_at,
        positions=tuple(positions),rules=(),fee_schedule=None,account_coverage='partial',
        missing_inputs=('verified_account_inventory','funds','bound_cost_schedule'),
        sources=(SourceStamp(source=reference,revision='declared-account-input.1',observed_at=observed_at,
                             checksum=hashlib.sha256(payload.encode()).hexdigest()),))
    result=evaluate_remaining_risk(bundle)
    result['metrics'].pop('combined_inventory',None)
    result['limitations'].append('User-declared positions only; not authenticated whole-account coverage.')
    return result
