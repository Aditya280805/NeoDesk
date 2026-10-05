from unittest.mock import MagicMock

import httpx
import pytest
from neo_api_client import NeoAPI
from pydantic import ValidationError

from app.brokers.base_broker import BrokerError
from app.brokers.kotak_neo.kotak_broker import KotakNeoBroker
from app.core.config import Settings


def config(**overrides):
    values = dict(kotak_consumer_key="test-key", kotak_ucc="test-ucc",
                  kotak_mobile_number="+910000000000", kotak_instruments=[
                      {"exchange_segment": "nse_cm", "instrument_token": "1333"}])
    return Settings(_env_file=None, **(values | overrides))


QUOTE = {"exchange_token": "1333", "exchange": "nse_cm", "display_symbol": "HDFCBANK-EQ",
         "ltp": "801.60", "per_change": "1.06", "lstup_time": "1782374657"}


def test_real_sdk_quote_transport_and_cache():
    requests = []

    def respond(request):
        requests.append(request)
        assert request.headers["Authorization"] == "test-key"
        assert "nse_cm|1333" in str(request.url)
        return httpx.Response(200, json=[QUOTE])

    broker = KotakNeoBroker(config(), lambda **kw: NeoAPI(**kw, transport=httpx.MockTransport(respond)))
    try:
        quote = broker.get_quotes()[0]
        assert quote["source"] == "kotak" and quote["ltp"] == 801.6
        assert quote["last_trade_time"] == "1782374657"
        assert broker.get_quotes()[0] == quote
        assert len(requests) == 1
        assert not broker.is_authenticated  # Quotes only need the API token.
    finally:
        broker.close()


@pytest.mark.parametrize("response", [
    {"error": [{"message": "secret-token"}]}, {"Error": "bad response"}, [],
    [QUOTE | {"ltp": "NaN"}], [QUOTE | {"exchange_token": "wrong"}], [QUOTE, QUOTE],
])
def test_bad_quotes_never_become_sample_prices_or_leak_errors(response):
    client = MagicMock()
    client.quotes.return_value = response
    broker = KotakNeoBroker(config(), lambda **kw: client)
    with pytest.raises(BrokerError, match="quotes unavailable") as error:
        broker.get_quotes()
    assert "secret-token" not in str(error.value)


def success(kind):
    return {"data": {"status": "success", "kType": kind, "token": "hidden", "sid": "hidden"}}


def test_login_requires_both_steps_and_discards_session():
    client = MagicMock()
    client.totp_login.return_value = success("View")
    client.totp_validate.return_value = success("Trade")
    broker = KotakNeoBroker(config(), lambda **kw: client)
    broker.login("123456", "123456")
    assert broker.is_authenticated
    client.totp_validate.assert_called_once_with(mpin="123456")
    broker.close()
    assert not broker.is_authenticated
    client.logout.assert_called_once()


@pytest.mark.parametrize("failure", ["totp_login", "totp_validate"])
def test_rejected_login_never_authenticates(failure):
    client = MagicMock()
    client.totp_login.return_value = success("View")
    client.totp_validate.return_value = success("Trade")
    getattr(client, failure).return_value = {"error": "private response"}
    broker = KotakNeoBroker(config(), lambda **kw: client)
    with pytest.raises(BrokerError):
        broker.login("123456", "123456")
    assert not broker.is_authenticated and broker._client is None
    if failure == "totp_login":
        client.totp_validate.assert_not_called()


def test_live_orders_disabled_even_with_live_configuration():
    client = MagicMock()
    broker = KotakNeoBroker(config(trading_mode="live", live_trading_enabled=True), lambda **kw: client)
    with pytest.raises(BrokerError):
        broker.place_order({})
    with pytest.raises(BrokerError):
        broker.cancel_order("123")
    client.place_order.assert_not_called()
    client.cancel_order.assert_not_called()


def test_missing_key_prevents_sdk_creation():
    factory = MagicMock()
    broker = KotakNeoBroker(config(kotak_consumer_key=None), factory)
    with pytest.raises(BrokerError, match="KOTAK_CONSUMER_KEY"):
        broker.get_quotes()
    factory.assert_not_called()


def test_partial_batch_retains_valid_quotes_and_activity_fields():
    client=MagicMock()
    client.quotes.return_value=[QUOTE|{'last_volume':'200','avg_cost':'800'},QUOTE|{'exchange_token':'2885','ltp':'0'}]
    broker=KotakNeoBroker(config(kotak_instruments=[{'exchange_segment':'nse_cm','instrument_token':t} for t in ('1333','2885')]),lambda **kw:client)
    result=broker.get_quotes(strict=False)
    assert len(result)==1 and result[0]['volume']==200 and result[0]['turnover_estimate']==160000


def test_config_rejects_oversize_batches_and_masks_key():
    with pytest.raises(ValidationError):
        config(kotak_instruments=[{"exchange_segment": "nse_cm", "instrument_token": "1333"}] * 51)
    assert "test-key" not in repr(config())


def test_live_quote_failure_http_boundary(monkeypatch, tmp_path):
    from app.terminal.server import create_app
    from fastapi.testclient import TestClient
    app = create_app(config(data_dir=tmp_path, app_password=None, environment='test'))
    monkeypatch.setattr(app.state.market, "quotes", MagicMock(side_effect=BrokerError("Quotes unavailable")))
    response = TestClient(app).get("/api/market/quotes")
    assert response.status_code == 503
    assert response.json() == {"detail": "Quotes unavailable"}
    assert TestClient(app).get("/api/status").json()["mode"] == "paper"
