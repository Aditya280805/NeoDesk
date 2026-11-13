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


def test_official_fetch_is_bounded_and_records_source_revision():
    import httpx
    from app.terminal.analytics_ban_source import fetch_ban_publication
    def handler(request):
        assert str(request.url) == 'https://nsearchives.nseindia.com/content/fo/fo_secban.csv'
        return httpx.Response(200,text='Securities in Ban For Trade Date 13-NOV-2026:\n1,KAYNES\n')
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = fetch_ban_publication(date(2026,11,13),deadline=__import__('time').monotonic()+5,client=client)
    assert result['provenance'] == 'official_https_fetch'
    assert len(result['checksum']) == 64


def test_expired_deadline_prevents_source_request():
    from app.terminal.analytics_ban_source import fetch_ban_publication
    with pytest.raises(TimeoutError):
        fetch_ban_publication(date(2026,11,13),deadline=0)
