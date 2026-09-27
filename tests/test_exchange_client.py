import ccxt
import pytest

from exchange_client import ExchangeClient, backoff_delay


class FakeExchange:
    def __init__(self, errors, result="ok"):
        self.errors = list(errors)
        self.calls = 0
        self.result = result

    def fetch_ticker(self, symbol):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return {"last": 42.0}

    def create_order(self, *args, **kwargs):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return {"id": "1"}

    def amount_to_precision(self, symbol, amount):
        return str(amount)

    def load_markets(self, reload=False):
        return {}


def _client(errors, max_retries=3):
    sleeps = []
    fake = FakeExchange(errors)
    client = ExchangeClient("binance", exchange=fake, max_retries=max_retries, base_delay=0.1, max_delay=1.0,
                            sleep_fn=sleeps.append)
    return client, fake, sleeps


def test_retries_network_errors_then_succeeds():
    client, fake, sleeps = _client([ccxt.NetworkError("x"), ccxt.RateLimitExceeded("y"), ccxt.DDoSProtection("z")])
    assert client.fetch_last_price("BTC/USDT") == 42.0
    assert fake.calls == 4 and len(sleeps) == 3
    assert all(0 < s <= 1.0 for s in sleeps)


def test_does_not_retry_auth_or_funds_errors():
    for err in (ccxt.AuthenticationError("bad key"), ccxt.InsufficientFunds("no money")):
        client, fake, sleeps = _client([err])
        with pytest.raises(type(err)):
            client.fetch_ticker("BTC/USDT")
        assert fake.calls == 1 and sleeps == []


def test_gives_up_after_max_retries():
    client, fake, sleeps = _client([ccxt.RequestTimeout("t")] * 10, max_retries=2)
    with pytest.raises(ccxt.RequestTimeout):
        client.fetch_ticker("BTC/USDT")
    assert fake.calls == 3 and len(sleeps) == 2


def test_order_not_blindly_retried_on_timeout():
    client, fake, _ = _client([ccxt.RequestTimeout("t")])
    client._markets_loaded = True
    with pytest.raises(ccxt.RequestTimeout):
        client.create_market_order("BTC/USDT", "buy", 1.0)
    assert fake.calls == 1


def test_order_retried_on_rate_limit():
    client, fake, _ = _client([ccxt.RateLimitExceeded("slow down")])
    client._markets_loaded = True
    assert client.create_market_order("BTC/USDT", "buy", 1.0)["id"] == "1"
    assert fake.calls == 2


def test_backoff_grows_and_is_capped():
    hi = lambda a, b: b  # noqa: E731 - take the ceiling of the jitter range
    assert [backoff_delay(i, 1.0, 10.0, rng=hi) for i in range(6)] == [1, 2, 4, 8, 10, 10]
    lo = lambda a, b: a  # noqa: E731
    assert backoff_delay(3, 1.0, 10.0, rng=lo) == 0.5
