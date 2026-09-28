"""Regression tests for the overnight safety review findings."""

import ccxt
import pandas as pd
import pytest

from backtest import generate_synthetic_ohlcv
from bot_engine import BotEngine
from config import DEFAULT_SETTINGS, Config
from exchange_client import AmbiguousOrderError, ExchangeClient, OrderNotPlaced
from execution import LiveExecutionClient, PaperExecutionClient
from risk_manager import RiskManager
from state_manager import StateManager
from strategy import StrategyParams, compute_indicators


@pytest.fixture
def state(tmp_path):
    s = StateManager(str(tmp_path / "t.db"))
    s.seed_default_settings(DEFAULT_SETTINGS)
    s.set_setting("exchange_stop_enabled", False)
    return s


class FakeLive:
    """ExchangeClient stand-in for LiveExecutionClient."""

    def __init__(self, contract_size=1.0, exchange_id="bybit"):
        self.exchange_id = exchange_id
        self.size = contract_size
        self.market_orders = []
        self.next_error = None
        self.lookup = None  # order dict | OrderNotPlaced | AmbiguousOrderError
        self.balance = {"total": {"USDT": 1000.0}, "free": {"USDT": 1000.0}}
        self.stops = []

    def contract_size(self, symbol):
        return self.size

    def amount_to_precision(self, symbol, amount):
        return round(amount, 8)

    def market_limits(self, symbol):
        return {"min_amount": 1 if self.size != 1 else None, "min_cost": None}

    def create_market_order(self, symbol, side, amount, params=None):
        self.market_orders.append((side, amount))
        if self.next_error is not None:
            err, self.next_error = self.next_error, None
            raise err
        return {"id": str(len(self.market_orders)), "average": 100.0, "filled": amount, "status": "closed",
                "fee": {"cost": 0.0, "currency": "USDT"}}

    def resolve_order(self, symbol, cid, since_ms):
        if isinstance(self.lookup, Exception):
            raise self.lookup
        return self.lookup

    def fetch_balance(self):
        return self.balance

    def supports_stop_orders(self):
        return True

    def create_stop_order(self, symbol, side, amount, stop_price, params=None):
        self.stops.append((side, amount, stop_price))
        return {"id": f"s{len(self.stops)}"}


def _ambiguous():
    return AmbiguousOrderError("timeout", "BTC/USDT", "tbo123", 1_000)


# ---------------------------------------------------- 4: ambiguous entry
def test_ambiguous_entry_is_booked_with_its_stop_once_found(state):
    state.set_setting("exchange_stop_enabled", True)
    ex = FakeLive()
    live = LiveExecutionClient(state, ex, market_type="swap", fee_rate_estimate=0.0)
    ex.next_error = _ambiguous()
    with pytest.raises(AmbiguousOrderError):
        live.open_position("BTC/USDT", "long", 1.0, 100.0, 95.0, 110.0, 2.0)
    assert state.get_open_positions() == [] and live.has_pending_entry("BTC/USDT")

    ex.lookup = {"id": "9", "average": 100.5, "filled": 1.0, "status": "closed", "fee": {"cost": 0, "currency": "USDT"}}
    live.resolve_pending_orders()
    [pos] = state.get_open_positions()
    assert pos["entry_price"] == pytest.approx(100.5) and pos["stop_loss"] == pytest.approx(95.5)
    assert ex.stops == [("sell", pytest.approx(1.0), pytest.approx(95.5))]  # protected on the exchange
    assert not live.has_pending_entry("BTC/USDT")
    assert len(ex.market_orders) == 1  # never re-sent


def test_ambiguous_entry_confirmed_absent_is_dropped(state):
    ex = FakeLive()
    live = LiveExecutionClient(state, ex, market_type="swap")
    ex.next_error = _ambiguous()
    with pytest.raises(AmbiguousOrderError):
        live.open_position("BTC/USDT", "long", 1.0, 100.0, 95.0, 110.0, 2.0)
    ex.lookup = OrderNotPlaced("absent")
    live.resolve_pending_orders()
    assert not live.has_pending_entry("BTC/USDT") and state.get_open_positions() == []


# ---------------------------------------------------- 5: ambiguous close
def _open_live(state, ex):
    live = LiveExecutionClient(state, ex, market_type="swap", fee_rate_estimate=0.0)
    return live, live.open_position("BTC/USDT", "long", 1.0, 100.0, 95.0, 110.0, 2.0)


def test_ambiguous_close_is_looked_up_not_resent(state):
    ex = FakeLive()
    live, pos = _open_live(state, ex)
    ex.next_error = _ambiguous()
    with pytest.raises(AmbiguousOrderError):
        live.close_position(pos, 105.0, "manual")
    assert state.get_position(pos["id"])["status"] == "open"

    ex.lookup = _ambiguous()  # still unknown: nothing is sent
    with pytest.raises(AmbiguousOrderError):
        live.close_position(pos, 105.0, "manual")
    assert len(ex.market_orders) == 2  # entry + the one unclear exit

    ex.lookup = {"id": "7", "average": 104.0, "filled": 1.0, "status": "closed"}
    closed = live.close_position(pos, 105.0, "manual")
    assert closed["status"] == "closed" and closed["exit_price"] == pytest.approx(104.0)
    assert len(ex.market_orders) == 2


def test_ambiguous_close_confirmed_absent_sends_a_new_exit(state):
    ex = FakeLive()
    live, pos = _open_live(state, ex)
    ex.next_error = _ambiguous()
    with pytest.raises(AmbiguousOrderError):
        live.close_position(pos, 105.0, "manual")
    ex.lookup = OrderNotPlaced("absent")
    assert live.close_position(pos, 105.0, "manual")["status"] == "closed"
    assert len(ex.market_orders) == 3


# ---------------------------------------------------- 6: contract size
def test_futures_orders_are_sent_in_contracts(state):
    state.set_setting("exchange_stop_enabled", True)
    ex = FakeLive(contract_size=0.01)  # e.g. OKX BTC swap: 1 contract = 0.01 BTC
    live = LiveExecutionClient(state, ex, market_type="swap", fee_rate_estimate=0.0)
    pos = live.open_position("BTC/USDT", "long", 0.05, 100.0, 95.0, 110.0, 2.0)
    assert ex.market_orders[0] == ("buy", pytest.approx(5.0))
    assert pos["quantity"] == pytest.approx(0.05)
    assert ex.stops[0][1] == pytest.approx(5.0)
    assert live.open_position("BTC/USDT", "long", 0.005, 100.0, 95.0, 110.0, 2.0) is None  # < 1 contract


# ---------------------------------------------------- 13: equity
@pytest.mark.parametrize("exchange_id,expected", [("binance", 1000.0), ("bybit", 1010.0)])
def test_derivative_equity_counts_unrealized_once(state, exchange_id, expected):
    ex = FakeLive(exchange_id=exchange_id)
    live, _ = _open_live(state, ex)
    assert live.get_equity({"BTC/USDT": 110.0}) == pytest.approx(expected)


# ---------------------------------------------------- engine helpers
class FakeMarket:
    def __init__(self, df, now_ms=None):
        self.df = df
        self.price = float(df["close"].iloc[-1])
        self.now_ms = now_ms
        self.fail_price = False

    def load_markets(self, reload=False):
        return {}

    def fetch_last_price(self, symbol):
        if self.fail_price:
            raise ccxt.NetworkError("down")
        return self.price

    def fetch_closed_ohlcv(self, symbol, timeframe, limit):
        return self.df.tail(limit).reset_index(drop=True)

    def timeframe_ms(self, tf):
        return 3_600_000

    def milliseconds(self):
        return self.now_ms if self.now_ms is not None else int(self.df["timestamp"].iloc[-1]) + 3_600_000 + 5_000


def _signal_candles(state):
    state.set_setting("min_confirmations", 2)
    df = generate_synthetic_ohlcv(3000, seed=7)
    ind = compute_indicators(df, StrategyParams.from_settings(state.get_all_settings()))
    return df.iloc[: int(ind.index[ind["long_signal"]][0]) + 1]


def _paper_engine(state, market, **cfg):
    executor = PaperExecutionClient(state, market, starting_balance=10_000, fee_rate=0.0, slippage_bps=0)
    config = Config(symbols=["BTC/USDT"], timeframe="1h", poll_interval_sec=30, **cfg)
    return BotEngine(config, state, market, executor, RiskManager(state.get_all_settings), sleep_fn=lambda s: None)


def test_fresh_signal_still_enters(state):
    engine = _paper_engine(state, FakeMarket(_signal_candles(state)))
    engine.tick()
    assert len(state.get_open_positions()) == 1


# ---------------------------------------------------- 16: stale signal
def test_signal_on_a_candle_that_closed_hours_ago_is_skipped(state):
    candles = _signal_candles(state)
    market = FakeMarket(candles, now_ms=int(candles["timestamp"].iloc[-1]) + 3_600_000 + 3 * 3_600_000)
    engine = _paper_engine(state, market)
    engine.tick()
    assert state.get_open_positions() == []
    assert any("stale" in e["message"] for e in state.get_events())


# ---------------------------------------------------- 19: stale price
def test_no_trading_on_a_cached_price_when_the_fetch_fails(state):
    market = FakeMarket(_signal_candles(state))
    engine = _paper_engine(state, market)
    engine._last_prices["BTC/USDT"] = market.price  # cached from an earlier tick
    market.fail_price = True
    engine.tick()
    assert state.get_open_positions() == []


# ---------------------------------------------------- 15: failed exit retried
class FlakyPaper(PaperExecutionClient):
    fail_next_close = False

    def _submit_market_order(self, symbol, side, quantity, reference_price, reduce_only=False):
        if reduce_only and self.fail_next_close:
            self.fail_next_close = False
            raise ccxt.NetworkError("down")
        return super()._submit_market_order(symbol, side, quantity, reference_price, reduce_only)


def test_failed_trend_flip_exit_is_retried_next_loop(state):
    market = FakeMarket(generate_synthetic_ohlcv(300))
    executor = FlakyPaper(state, market, starting_balance=10_000, fee_rate=0.0, slippage_bps=0)
    engine = BotEngine(Config(symbols=["BTC/USDT"]), state, market, executor, RiskManager(state.get_all_settings),
                       sleep_fn=lambda s: None)
    pos = executor.open_position("BTC/USDT", "long", 1, 100, 50, 500, 1)
    executor.fail_next_close = True
    engine._close(pos, 100, "trend_flip")
    assert state.get_position(pos["id"])["status"] == "open"
    engine._enforce_stops("BTC/USDT", 100)  # price inside the levels: retried because it is pending
    closed = state.get_position(pos["id"])
    assert closed["status"] == "closed" and closed["exit_reason"] == "trend_flip"


# ---------------------------------------------------- 18: trailing window
def test_trailing_ignores_pre_entry_part_of_the_entry_candle(state):
    engine = _paper_engine(state, FakeMarket(generate_synthetic_ohlcv(300)))
    pid = state.open_position(symbol="BTC/USDT", side="long", quantity=1.0, entry_price=100.0, stop_loss=95.0,
                              take_profit=200.0, mode="paper", opened_at="2026-01-01T00:30:00+00:00")
    hour = 3_600_000
    t0 = 1_767_225_600_000  # 2026-01-01T00:00Z
    candles = pd.DataFrame({"timestamp": [t0, t0 + hour], "open": [100, 101], "high": [150.0, 103.0],
                            "low": [99, 100], "close": [101, 102], "volume": [1, 1]})
    engine._update_trailing(state.get_position(pid), candles, hour, 1.0)
    assert state.get_position(pid)["highest_price"] == pytest.approx(103.0)  # not the pre-entry 150


# ---------------------------------------------------- 17: history paging
class CappedExchange:
    has = {}

    def __init__(self, total, cap):
        hour = 3_600_000
        self.rows = [[i * hour, 1, 1, 1, 1, 1] for i in range(total)]
        self.cap = cap

    def load_markets(self, reload=False):
        return {}

    def milliseconds(self):
        return (len(self.rows) + 1) * 3_600_000

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
        rows = self.rows if since is None else [r for r in self.rows if r[0] >= since]
        n = min(limit or self.cap, self.cap)
        return rows[-n:] if since is None else rows[:n]


def test_candle_history_is_paged_past_the_exchange_cap():
    client = ExchangeClient("x", exchange=CappedExchange(total=700, cap=300))
    df = client.fetch_closed_ohlcv("BTC/USDT", "1h", 650)
    assert len(df) == 650 and df["timestamp"].is_monotonic_increasing and df["timestamp"].is_unique


def test_short_history_is_reported_in_the_event_log(state):
    engine = _paper_engine(state, FakeMarket(generate_synthetic_ohlcv(60)))
    engine.tick()
    engine.tick()
    events = [e for e in state.get_events() if "kapanmış mum verdi" in e["message"]]
    assert len(events) == 1


# ---------------------------------------------------- 7 / 8: startup checks
def _live_engine(state, **cfg):
    ex = FakeLive()
    ex.load_markets = lambda reload=False: {}
    live = LiveExecutionClient(state, ex, market_type="spot")
    config = Config(symbols=["BTC/USDT"], paper_trading=False, **cfg)
    return BotEngine(config, state, ex, live, RiskManager(state.get_all_settings), sleep_fn=lambda s: None)


def test_switching_testnet_to_mainnet_with_open_positions_refuses_to_start(state):
    _live_engine(state, use_testnet=True)._check_account_identity()
    state.open_position(symbol="BTC/USDT", side="long", quantity=1, entry_price=100, stop_loss=95,
                        take_profit=110, mode="live")
    with pytest.raises(RuntimeError, match="testnet"):
        _live_engine(state, use_testnet=False)._check_account_identity()


def test_switching_account_without_positions_resets_the_daily_baseline(state):
    _live_engine(state, use_testnet=True)._check_account_identity()
    state.get_or_create_day_start_equity("live", 5_000.0)
    _live_engine(state, use_testnet=False)._check_account_identity()
    assert state.get_day_start_equity("live") is None
    assert state.get_state("live_account").endswith("mainnet")


def test_open_positions_of_the_other_mode_are_warned_about(state):
    state.open_position(symbol="ETH/USDT", side="long", quantity=1, entry_price=100, stop_loss=95,
                        take_profit=110, mode="live")
    engine = _paper_engine(state, FakeMarket(generate_synthetic_ohlcv(300)))
    engine._warn_about_other_mode_positions()
    assert any("LIVE pozisyon" in e["message"] and "ETH/USDT" in e["message"] for e in state.get_events())
