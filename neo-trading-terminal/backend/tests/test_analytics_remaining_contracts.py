from datetime import UTC,datetime
import pytest
from app.terminal.analytics_remaining_contracts import CapturedRiskBundle,SourceStamp

def bundle(**changes):
    return CapturedRiskBundle(**(dict(owner_id=7,session_generation='session',as_of=datetime.now(UTC),positions=(),rules=(),fee_schedule=None,account_coverage='partial',missing_inputs=('positions',),sources=())|changes))

def test_bundle_rejects_naive_time():
    with pytest.raises(ValueError): bundle(as_of=datetime(2026,11,13))

def test_bundle_rejects_unknown_fields():
    with pytest.raises(ValueError): bundle(raw_account={'secret':'private'})

def test_bundle_requires_positive_owner():
    for owner in (0,True,'7'):
        with pytest.raises(ValueError): bundle(owner_id=owner)

def test_bundle_does_not_promote_partial_coverage():
    assert bundle().account_coverage == 'partial'
    with pytest.raises(ValueError): bundle(account_coverage='complete')

def test_source_rejects_inverted_effective_dates():
    with pytest.raises(ValueError):
        SourceStamp(source='official',revision='v1',observed_at=datetime.now(UTC),effective_from='2026-11-14',effective_until='2026-11-13',checksum='a'*64)
