from datetime import date
import pytest
from app.terminal.indian_charges import statutory_charges
from app.terminal.quant_attribution import reconcile_trade_inventory_cash
from app.terminal.quant_compliance import aggregate_underlying_compliance

def test_missing_exercise_charge_blocks_total_and_gst():
    result=statutory_charges('option','EXERCISE',1000,date(2026,11,13),brokerage_inr=0)
    assert result['total_paise'] is None and result['gst_paise'] is None

def test_sale_without_opening_inventory_never_creates_profit():
    with pytest.raises(ValueError):
        reconcile_trade_inventory_cash(0,[dict(side='SELL',quantity=1,price=100,fees_paise=0)])

def test_missing_fees_and_mixed_inventory_rejected():
    with pytest.raises(ValueError):
        reconcile_trade_inventory_cash(100,[dict(side='BUY',quantity=1,price=10)])
    with pytest.raises(ValueError):
        reconcile_trade_inventory_cash(100,[dict(contract_id='A',side='BUY',quantity=1,price=10,fees_paise=0),dict(contract_id='B',side='SELL',quantity=1,price=20,fees_paise=0)])

def test_dry_eval_does_not_claim_model_passes():
    from pathlib import Path
    from evals.remaining_live_evals import run_evaluations
    result=run_evaluations(Path(__file__).parents[1]/'evals/analytics_router_remaining.v1.json',dry_run=True)
    assert result['passed_cases']==0 and result['model_evaluated'] is False

def test_incomplete_or_already_aggregated_futeq_is_not_summed():
    positions=[dict(contract_id='A',underlying='ABC'),dict(contract_id='B',underlying='ABC')]
    rules=[dict(contract_id='A',instrument_scope='stock_derivative',ban_active=True,base_futeq=1,current_futeq=2),
           dict(contract_id='B',instrument_scope='stock_derivative',ban_active=True,base_futeq=None,current_futeq=None)]
    result=aggregate_underlying_compliance(positions,rules)
    assert result['underlying_summaries']['ABC']['aggregate_current_futeq'] is None
    for rule in rules:
        rule.update(base_futeq=1,current_futeq=2,futeq_basis='declared_underlying_aggregate')
    result=aggregate_underlying_compliance(positions,rules)
    assert result['underlying_summaries']['ABC']['aggregate_current_futeq'] is None
