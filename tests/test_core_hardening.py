"""Regression tests for bot core fixes (daily limit snapshot, orphan stops,
order errors, close_all, spot base-asset fees, paper precision)."""

import math

import ccxt
import pytest

from backtest import generate_synthetic_ohlcv
from bot_engine import BotEngine
from config import DEFAULT_SETTINGS, Config
from execution import LiveExecutionClient, PaperExecutionClient
from risk_manager import RiskManager
from state_manager import StateManager
from strategy import StrategyParams, compute_indicators


@pytest.fixture
def state(tmp_path):
    s = StateManager(str(tmp_path / "t.db"))
    s.seed_default_settings(DEFAULT_SETTINGS)
    s.set_setting("min_confirmations", 2)
    return s


class FakeExchange:
    def __init__(self, df):
        self.df = df
        self.price = float(df["close"].iloc[-1])
        self.failing_symbols = set()

    def load_markets(self, reload=False):
        return {}

    def fetch_last_price(self, symbol):
        if symbol in self.failing_symbols:
            raise ccxt.NetworkError("down")
        return self.price

    def fetch_closed_ohlcv(self, symbol, timeframe, limit):
        return self.df.tail(limit).reset_index(drop=True)

    def timeframe_ms(self, tf):
        return 3_600_000


def _signal_candles(state):
    df = generate_synthetic_ohlcv(3000, seed=7)
    ind = compute_indicators(df, StrategyParams.from_settings(state.get_all_settings()))
    idx = int(ind.index[ind["long_signal"]][0])
    return df.iloc[: idx + 1]


def _engine(state, df, symbols=("BTC/USDT",)):
    ex = FakeExchange(df)
    executor = PaperExecutionClient(state, ex, starting_balance=10_000, fee_rate=0.0, slippage_bps=0)
    cfg = Config(symbols=list(symbols), timeframe="1h", poll_interval_sec=1)
    return BotEngine(cfg, state, ex, executor, RiskManager(state.get_all_settings), sleep_fn=lambda s: None), ex


def test_day_start_equity_recorded_without_a_signal(state):
    candles = _signal_candles(state)
    engine, _ = _engine(state, candles.iloc[:-1])  # last row is not a signal
    engine.tick()
    assert state.get_day_start_equity("paper") == pytest.approx(10_000)
    assert state.get_open_positions() == []


def test_losses_before_the_first_signal_count_toward_daily_limit(state):
    candles = _signal_candles(state)
    engine, ex = _engine(state, candles.iloc[:-1])
    engine.tick()  # day starts at 10 000

    pos = engine.executor.open_position("ETH/USDT", "long", 10, 100, 90, 120, 1)
    engine.executor.close_position(pos, 40, "stop_loss")  # -600 = -6 % (limit 5 %)

    ex.df = candles  # now the entry signal appears
    engine.tick()
    assert state.get_open_positions() == []
    assert any("daily loss limit" in e["message"] for e in state.get_events())


def test_stops_enforced_for_symbol_no_longer_configured(state):
    engine, ex = _engine(state, generate_synthetic_ohlcv(300))
    pos = engine.executor.open_position("ETH/USDT", "long", 1, 100, 95, 120, 1)
    ex.price = 94
    engine.tick()
    closed = state.get_position(pos["id"])
    assert closed["status"] == "closed" and closed["exit_reason"] == "stop_loss"


def test_entry_network_error_is_not_retried_on_the_same_candle(state):
    engine, _ = _engine(state, _signal_candles(state))
    calls = []

    def failing_open(*args, **kwargs):
        calls.append(args)
        raise ccxt.RequestTimeout("no answer")

    engine.executor.open_position = failing_open
    engine.tick()
    engine.tick()
    assert len(calls) == 1
    assert any("order status unknown" in e["message"] for e in state.get_events())


def test_close_all_keeps_going_when_one_symbol_fails(state):
    engine, ex = _engine(state, generate_synthetic_ohlcv(300))
    a = engine.executor.open_position("ETH/USDT", "long", 1, 100, 90, 120, 1)
    b = engine.executor.open_position("SOL/USDT", "long", 1, 100, 90, 120, 1)
    ex.failing_symbols.add("ETH/USDT")
    cid = state.enqueue_command("close_all")
    engine._process_commands()
    assert state.get_position(a["id"])["status"] == "open"
    assert state.get_position(b["id"])["status"] == "closed"
    cmd = state.get_command(cid)
    assert cmd["status"] == "failed" and "ETH/USDT" in cmd["note"]


class FakeSpotExchange:
    def __init__(self, free_base=None):
        self.orders = []
        self.free_base = free_base
        self.fill_price = 100.0

    def create_market_order(self, symbol, side, amount, params=None):
        self.orders.append((side, amount))
        fee = {"cost": amount * 0.001, "currency": "BTC"} if side == "buy" else {"cost": 0.1, "currency": "USDT"}
        return {"id": str(len(self.orders)), "average": self.fill_price, "filled": amount, "fee": fee}

    def fetch_balance(self):
        return {"free": {"BTC": self.free_base, "USDT": 1000.0}, "total": {"BTC": self.free_base, "USDT": 1000.0}}

    def amount_to_precision(self, symbol, amount):
        return amount

    def market_limits(self, symbol):
        return {}


def test_live_spot_buy_tracks_quantity_net_of_base_fee(state):
    ex = FakeSpotExchange()
    live = LiveExecutionClient(state, ex, market_type="spot", quote_currency="USDT")
    pos = live.open_position("BTC/USDT", "long", 1.0, 100, 95, 110, 1)
    assert pos["quantity"] == pytest.approx(0.999)
    assert pos["fees"] == pytest.approx(0.1)  # 0.001 BTC at 100

    ex.free_base, ex.fill_price = 0.999, 110.0
    closed = live.close_position(pos, 110, "take_profit")
    assert ex.orders[-1] == ("sell", pytest.approx(0.999))
    # true PnL: sold 0.999 at 110, paid 100 for 1 BTC, 0.1 USDT exit fee
    assert closed["pnl"] == pytest.approx(0.999 * 110 - 100 - 0.1)


def test_live_spot_sell_capped_at_free_balance(state):
    ex = FakeSpotExchange(free_base=0.998)
    live = LiveExecutionClient(state, ex, market_type="spot", quote_currency="USDT")
    pid = state.open_position(symbol="BTC/USDT", side="long", quantity=1.0, entry_price=100, stop_loss=95,
                              take_profit=110, mode="live")
    live.close_position(state.get_position(pid), 100, "manual")
    assert ex.orders[-1] == ("sell", pytest.approx(0.998))


class FakePrecisionExchange:
    def amount_to_precision(self, symbol, amount):
        return math.floor(amount * 1000) / 1000

    def market_limits(self, symbol):
        return {"min_amount": 0.001, "min_cost": 10.0}


def test_paper_rounds_to_exchange_precision_and_limits(state):
    paper = PaperExecutionClient(state, FakePrecisionExchange(), starting_balance=10_000, fee_rate=0.0,
                                 slippage_bps=0)
    pos = paper.open_position("BTC/USDT", "long", 0.12345, 100, 95, 110, 1)
    assert pos["quantity"] == pytest.approx(0.123)
    assert paper.open_position("BTC/USDT", "long", 0.05, 100, 95, 110, 1) is None  # 5 < min cost 10
