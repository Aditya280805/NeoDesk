from datetime import date
import pytest

from app.terminal.analytics_ban_source import parse_ban_publication


def test_official_publication_binds_explicit_trade_date():
    result = parse_ban_publication('Securities in Ban For Trade Date 13-NOV-2026:\n1,KAYNES\n',date(2026,11,13))
    assert result['trade_date'] == '2026-11-13'
    assert result['symbols'] == ['KAYNES']


@pytest.mark.parametrize('body',[
    'Securities in Ban For Trade Date 12-NOV-2026:\n1,KAYNES',
    '1,KAYNES',
    'Securities in Ban For Trade Date 13-NOV-2026:\n1,KAYNES\n1,OTHER',
    'Securities in Ban For Trade Date 13-NOV-2026:\n2,KAYNES',
    'Securities in Ban For Trade Date 13-NOV-2026:\n',
])
def test_stale_missing_or_malformed_publication_is_unavailable(body):
    with pytest.raises(ValueError):
        parse_ban_publication(body,date(2026,11,13))
