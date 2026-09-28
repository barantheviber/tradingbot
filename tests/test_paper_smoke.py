"""The real-exchange paper smoke run (scripts/paper_smoke.py), offline: a fake
ccxt exchange stands in for the network so the script's own checks and the
LocalRuntime path it drives are covered by CI."""

import importlib.util
import math
import time
from pathlib import Path

import ccxt
import pytest

from backtest import generate_synthetic_ohlcv
from execution import PaperExecutionClient
from state_manager import StateManager

ROOT = Path(__file__).resolve().parents[1]


def _load_script():
    spec = importlib.util.spec_from_file_location("paper_smoke", ROOT / "scripts" / "paper_smoke.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeCcxtExchange:
    """Enough of a ccxt exchange for the bot: markets, time, candles, tickers.
    Swap markets are in contracts of 0.01 base with a whole-contract step."""

    id = "smokefake"
    has = {"fetchTime": True, "fetchOHLCV": True, "fetchTicker": True}

    def __init__(self, params=None):
        self.params = params or {}
        self.market_type = (self.params.get("options") or {}).get("defaultType", "spot")

    def load_markets(self, reload=False):
        return {"BTC/USDT": {}, "BTC/USDT:USDT": {}}

    def market(self, symbol):
        if symbol.endswith(":USDT"):
            return {"contract": True, "contractSize": 0.01, "limits": {"amount": {"min": 1}, "cost": {}}}
        return {"contract": False, "limits": {"amount": {"min": 0.00001}, "cost": {"min": 5.0}}}

    def amount_to_precision(self, symbol, amount):
        step = 1.0 if symbol.endswith(":USDT") else 0.00001
        steps = math.floor(amount / step + 1e-9)
        if steps <= 0:
            raise ccxt.InvalidOrder("amount below precision")
        return str(round(steps * step, 8))

    def price_to_precision(self, symbol, price):
        return str(round(price, 2))

    def milliseconds(self):
        return int(time.time() * 1000)

    def fetch_time(self):
        return self.milliseconds()

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
        tf_ms = int(ccxt.Exchange.parse_timeframe(timeframe) * 1000)
        limit = min(limit or 100, 300)  # a per-request cap, so the bot has to page
        now_open = self.milliseconds() // tf_ms * tf_ms
        end = now_open if since is None else min(now_open, since + (limit - 1) * tf_ms)
        start = end - (limit - 1) * tf_ms
        df = generate_synthetic_ohlcv(2000, seed=3)
        rows = []
        for i, ts in enumerate(range(start, end + 1, tf_ms)):
            r = df.iloc[(ts // tf_ms) % len(df)]
            rows.append([ts, float(r.open), float(r.high), float(r.low), float(r.close), float(r.volume)])
        return rows

    def fetch_ticker(self, symbol):  # the close of the forming candle, so price and ATR agree
        return {"last": self.fetch_ohlcv(symbol, "1h", limit=1)[-1][4]}


@pytest.fixture
def fake_exchange(monkeypatch):
    monkeypatch.setattr(ccxt, "smokefake", FakeCcxtExchange, raising=False)
    for key in ("API_KEY", "API_SECRET", "API_PASSWORD", "PAPER_TRADING", "EXCHANGE_ID", "MARKET_TYPE", "SYMBOLS",
                "TIMEFRAME", "POLL_INTERVAL_SEC", "DB_PATH", "LOG_DIR", "LOG_LEVEL", "PAPER_STARTING_BALANCE",
                "API_PORT", "API_TOKEN"):
        monkeypatch.delenv(key, raising=False)  # the script sets them; monkeypatch restores them afterwards


@pytest.mark.parametrize("market_type,symbols", [("spot", "BTC/USDT"), ("swap", "BTC/USDT:USDT")])
def test_smoke_run_passes_against_a_working_exchange(fake_exchange, tmp_path, market_type, symbols):
    smoke = _load_script()
    args = smoke.parse_args(["--exchange", "smokefake", "--market-type", market_type, "--symbols", symbols,
                             "--timeframe", "1h", "--poll", "1", "--start-timeout", "60",
                             "--workdir", str(tmp_path)])
    report = smoke.run(args)
    assert report.problems == []
    trades = StateManager(str(tmp_path / "bot.db")).get_closed_positions(mode="paper")
    assert len(trades) == 1 and trades[0]["exit_reason"] == "manual"
    if market_type == "swap":  # whole contracts of 0.01 BTC
        contracts = trades[0]["quantity"] / 0.01
        assert contracts >= 1 and contracts == pytest.approx(round(contracts))


def test_smoke_run_reports_a_bot_that_cannot_reach_the_exchange(fake_exchange, tmp_path, monkeypatch):
    def down(self, *a, **k):
        raise ccxt.NetworkError("unreachable")

    monkeypatch.setattr(FakeCcxtExchange, "fetch_ticker", down)
    smoke = _load_script()
    args = smoke.parse_args(["--exchange", "smokefake", "--symbols", "BTC/USDT", "--timeframe", "1h", "--poll", "1",
                             "--start-timeout", "5", "--workdir", str(tmp_path)])
    report = smoke.run(args)
    assert report.problems and "timed out" in report.problems[0]


# --------------------------------------------- paper sizing on contract markets
class ContractPrecision:
    def amount_to_precision(self, symbol, amount):
        return float(math.floor(amount + 1e-9))  # whole contracts

    def contract_size(self, symbol):
        return 0.01

    def market_limits(self, symbol):
        return {"min_amount": 1, "min_cost": None}


def test_paper_rounds_swap_quantities_in_contracts(tmp_path):
    state = StateManager(str(tmp_path / "t.db"))
    paper = PaperExecutionClient(state, ContractPrecision(), fee_rate=0.0, slippage_bps=0)
    # 0.0231 BTC = 2.31 contracts -> 2 contracts = 0.02 BTC (not 0 contracts, not 0.0231)
    pos = paper.open_position("BTC/USDT:USDT", "long", 0.0231, 43_210, 40_000, 50_000, 100)
    assert pos["quantity"] == pytest.approx(0.02)
    # the minimum is one contract = 0.01 BTC
    assert paper.open_position("BTC/USDT:USDT", "long", 0.005, 43_210, 40_000, 50_000, 100) is None


def test_reroute_changes_hosts_for_ci_only(monkeypatch):
    import exchange_client

    monkeypatch.setattr(exchange_client.ExchangeClient, "__init__", exchange_client.ExchangeClient.__init__)
    _load_script().reroute_public_hosts(["api.binance.com=data-api.binance.vision"], "", True)
    ex = exchange_client.ExchangeClient("binance").exchange
    assert ex.urls["api"]["public"] == "https://data-api.binance.vision/api/v3"
    assert ex.options["fetchMarkets"]["types"] == ["spot"]
