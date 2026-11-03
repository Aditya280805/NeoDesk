import json
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.terminal.portfolio_contracts import (
    PortfolioIssue, PortfolioRow, PortfolioSection, PortfolioSnapshot,
    SectionObservation, ValueProvenance, parse_decimal, serialize_snapshot,
)


def test_decimal_missing_zero_invalid_and_signed_values():
    for value in (None, '', '  '):
        assert parse_decimal(value) is None
    assert parse_decimal('0') == Decimal('0')
    assert str(parse_decimal('0.10')) == '0.10'
    assert parse_decimal('-2', allow_negative=True) == Decimal('-2')
    for value in (True, False, 'NaN', 'Infinity', float('nan'), float('inf'), '-2', 'bad', {}, []):
        with pytest.raises(ValueError):
            parse_decimal(value)


def test_snapshot_json_roundtrip_preserves_zero_and_missing():
    now = datetime.now(timezone.utc)
    snapshot = PortfolioSnapshot(
        evidence_id=uuid4(), retrieval_started_at=now,
        retrieval_finished_at=now, source_observed_at=now,
        sections={'holdings': PortfolioSection(state='available', rows=[
            PortfolioRow(row_id='holdings:0', quantity=Decimal('0'), last_price=None)
        ])}, summary={'value': Decimal('0'), 'pnl': None},
    )
    encoded = serialize_snapshot(snapshot)
    wire = json.loads(encoded)
    assert wire['summary'] == {'value': '0', 'pnl': None}
    assert wire['sections']['holdings']['rows'][0]['quantity'] == '0'
    assert wire['sections']['holdings']['rows'][0]['last_price'] is None
    assert PortfolioSnapshot.model_validate_json(encoded) == snapshot
    assert wire['schema_version'] == 'portfolio.v1'
    assert serialize_snapshot(snapshot) == encoded


@pytest.mark.parametrize('value', [True, 'NaN', 'Infinity', float('inf')])
def test_public_numeric_fields_reject_invalid_values(value):
    with pytest.raises(ValidationError):
        PortfolioRow(row_id='positions:0', quantity=value)
    with pytest.raises(ValidationError):
        PortfolioSection(state='available', values={'cash': value})


def test_public_models_reject_raw_payload_and_unknown_issue_codes():
    with pytest.raises(ValidationError):
        PortfolioRow(row_id='holdings:0', raw={'secret': 'value'})
    with pytest.raises(ValidationError):
        PortfolioIssue(code='arbitrary provider exception')
    row = PortfolioRow(row_id='orders:0')
    assert row.side is None
    assert row.identity_verified is None
    assert row.multiplier is None
    assert SectionObservation(raw=object()).raw is not None
    assert ValueProvenance(source='calculated', input_paths=['quantity', 'last_price'],
                           formula_version='holding_value.v1', basis='quantity * last_price')


def test_signed_quantities_and_pnl_preserve_missing_prices():
    row = PortfolioRow(row_id='positions:0', quantity='-2', provider_pnl='-0.10')
    assert row.quantity == Decimal('-2')
    assert row.provider_pnl == Decimal('-0.10')
    assert row.average_price is None
    with pytest.raises(ValidationError):
        PortfolioRow(row_id='positions:0', last_price='-1')


def test_serializer_revalidates_mutated_numeric_containers():
    now = datetime.now(timezone.utc)
    snapshot = PortfolioSnapshot(retrieval_started_at=now, retrieval_finished_at=now,
                                 source_observed_at=now)
    snapshot.summary['bad'] = Decimal('NaN')
    with pytest.raises(ValidationError):
        serialize_snapshot(snapshot)


def test_risk_extensions_preserve_explicit_proof_and_omit_absence():
    row = PortfolioRow(row_id='holdings:0', underlying_key='catalogue:ABC',
                       underlying_identity_basis='verified_catalogue',
                       inventory_coverage='disjoint', inventory_coverage_basis='fixture:lot_ids')
    assert PortfolioRow.model_validate_json(row.model_dump_json()) == row
    empty = PortfolioRow(row_id='holdings:1').model_dump(mode='json')
    assert not {'underlying_key', 'underlying_identity_basis', 'inventory_coverage', 'inventory_coverage_basis'} & empty.keys()
