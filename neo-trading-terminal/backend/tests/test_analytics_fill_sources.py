from datetime import date
import pytest
from app.terminal.analytics_fill_sources import parse_daily_fills

def fill(**changes):
    return dict(flId='1',flLeg=1,exSeg='nse_cm',tok='1',trnsTp='B',fldQty=2,avgPrc='10.25',flDt='13-Nov-2026',flTm='10:00:00',**changes)

def test_daily_fills_have_exact_turnover_without_invented_fees():
    result=parse_daily_fills({'data':[fill()]},date(2026,11,13))
    assert result['buy_turnover_paise']==2050
    assert result['fees_paise'] is None and result['complete_account_history'] is False

def test_duplicate_and_wrong_day_fills_rejected():
    with pytest.raises(ValueError): parse_daily_fills({'data':[fill(),fill()]},date(2026,11,13))
    with pytest.raises(ValueError): parse_daily_fills({'data':[fill()]},date(2026,11,14))

def test_documented_empty_is_not_transport_failure():
    assert parse_daily_fills({'stat':'Not_Ok','stCode':5203},date(2026,11,13))['fill_count']==0
    with pytest.raises(ValueError): parse_daily_fills({'stat':'Not_Ok','stCode':401},date(2026,11,13))
