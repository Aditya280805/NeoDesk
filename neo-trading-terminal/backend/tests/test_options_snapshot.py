"""Snapshot contract: contradictions and malformed provider values fail closed."""
import pytest

from app.brokers.base_broker import BrokerError
from app.terminal.options_agent import OptionsContext, normalize_snapshot
from test_options_agent import chain


@pytest.mark.parametrize('field,value', [('expiryDt', '05Nov2026'), ('underlying', 'BANKNIFTY'), ('exchange', 'bse_fo')])
def test_provider_identity_contradiction_is_rejected(field, value):
    raw = chain()
    raw['common_data'][field] = value
    with pytest.raises(BrokerError):
        normalize_snapshot(raw, OptionsContext(expiry='29Oct2026'))


@pytest.mark.parametrize('section,value', [('quote', []), ('instrument', 'bad'), ('openInterest', 10)])
def test_nested_malformed_objects_are_provider_errors(section, value):
    raw = chain()
    raw['call'][0][section] = value
    with pytest.raises(BrokerError):
        normalize_snapshot(raw, OptionsContext())


def test_identity_coverage_and_equivalent_expiry_are_explicit():
    result = normalize_snapshot(chain(), OptionsContext(expiry='2026-10-29'))
    assert result['identity_verification'] == {'underlying': False, 'exchange': False, 'expiry': True}
    assert any('identity' in text.lower() for text in result['limitations'])


def test_boolean_and_overflow_totals_are_not_valid_market_numbers():
    raw = chain()
    raw['put'][0]['quote']['ltp'] = True
    with pytest.raises(BrokerError):
        normalize_snapshot(raw, OptionsContext())
    raw = chain()
    for leg in raw['call']:
        leg['openInterest']['current'] = 1e308
    with pytest.raises(BrokerError):
        normalize_snapshot(raw, OptionsContext())


def test_conflicting_provider_expiry_aliases_fail_even_without_selected_expiry():
    raw = chain()
    raw['common_data']['expiry'] = '05Nov2026'
    with pytest.raises(BrokerError):
        normalize_snapshot(raw, OptionsContext())


def test_provider_expiry_alias_is_preserved_for_display():
    raw = chain()
    raw['common_data']['expiry'] = raw['common_data'].pop('expiryDt')
    result = normalize_snapshot(raw, OptionsContext())
    assert result['expiry'] == '29Oct2026'
