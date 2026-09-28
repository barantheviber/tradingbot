"""Automatic safety halt: drawdown from peak and losing streak."""

import pytest

from backtest import generate_synthetic_ohlcv
from bot_engine import BotEngine
from config import DEFAULT_SETTINGS, Config
from execution import PaperExecutionClient
from risk_manager import RiskManager
from state_manager import StateManager
from strategy import StrategyParams, compute_indicators


class FakeExchange:
    def __init__(self, df):
        self.df = df
        self.price = float(df["close"].iloc[-1])

    def load_markets(self, reload=False):
        return {}

    def fetch_last_price(self, symbol):
        return self.price

    def fetch_closed_ohlcv(self, symbol, timeframe, limit):
        return self.df.tail(limit).reset_index(drop=True)

    def timeframe_ms(self, tf):
        return 3_600_000


def _state(path):
    s = StateManager(str(path))
    s.seed_default_settings(DEFAULT_SETTINGS)
    s.set_setting("min_confirmations", 2)
    return s


def _signal_candles(state):
    df = generate_synthetic_ohlcv(3000, seed=7)
    ind = compute_indicators(df, StrategyParams.from_settings(state.get_all_settings()))
    return df.iloc[: int(ind.index[ind["long_signal"]][0]) + 1]


def _engine(state, df):
    ex = FakeExchange(df)
    executor = PaperExecutionClient(state, ex, starting_balance=10_000, fee_rate=0.0, slippage_bps=0)
    cfg = Config(symbols=["BTC/USDT"], timeframe="1h", poll_interval_sec=1)
    return BotEngine(cfg, state, ex, executor, RiskManager(state.get_all_settings), sleep_fn=lambda s: None)


def _lose(engine, amount, n=1, qty=1):
    for _ in range(n):
        pos = engine.executor.open_position("ETH/USDT", "long", qty, 100, 1, 200, 1)
        engine.executor.close_position(pos, 100 - amount, "stop_loss")


@pytest.fixture
def state(tmp_path):
    return _state(tmp_path / "t.db")


def test_drawdown_from_peak_halts_new_entries(state):
    state.set_setting("daily_loss_limit_pct", 0.0)  # isolate from the daily limit
    candles = _signal_candles(state)
    engine = _engine(state, candles.iloc[:-1])
    engine.tick()  # peak = 10 000
    _lose(engine, 16, qty=100)  # one trade losing 1 600 -> 16 % drawdown

    engine.exchange.df = candles  # entry signal appears
    engine.tick()
    assert state.get_setting("safety_halt_active") is True
    assert state.get_open_positions() == []
    status = state.get_safety_status("paper")
    assert status["active"] and "drawdown" in status["reason"]
    assert any("Güvenlik durdurması" in e["message"] for e in state.get_events())


def test_losing_streak_halts_and_open_positions_keep_their_stops(state):
    state.set_setting("max_losing_streak_halt", 3)
    engine = _engine(state, generate_synthetic_ohlcv(300))
    _lose(engine, 0.01, n=3)
    held = engine.executor.open_position("BTC/USDT", "long", 1, 100, 95, 120, 1)
    engine.exchange.price = 101
    engine.tick()
    assert state.get_setting("safety_halt_active") is True
    assert "3 losing trades" in state.get_safety_status("paper")["reason"]
    assert state.get_position(held["id"])["status"] == "open"  # nothing force-closed

    engine.exchange.price = 94  # its stop still works while halted
    engine.tick()
    assert state.get_position(held["id"])["exit_reason"] == "stop_loss"


def test_halt_survives_restart_and_blocks_entries(state, tmp_path):
    state.set_setting("max_losing_streak_halt", 2)
    candles = _signal_candles(state)
    engine = _engine(state, candles.iloc[:-1])
    _lose(engine, 0.01, n=2)
    engine.tick()
    assert state.get_setting("safety_halt_active") is True

    restarted_state = StateManager(state.db_path)
    restarted = _engine(restarted_state, candles)
    restarted.run(once=True)
    assert restarted_state.get_open_positions() == []
    assert any("safety halt" in e["message"] for e in restarted_state.get_events())


def test_clearing_resets_peak_and_streak_and_allows_entries(state):
    state.set_setting("max_losing_streak_halt", 2)
    state.set_setting("daily_loss_limit_pct", 0.0)
    candles = _signal_candles(state)
    engine = _engine(state, candles.iloc[:-1])
    engine.tick()
    _lose(engine, 5, n=2)
    engine.tick()
    assert state.get_setting("safety_halt_active") is True

    state.set_setting("safety_halt_active", False)  # user clears it
    engine.exchange.df = candles
    engine.tick()
    status = state.get_safety_status("paper")
    assert not status["active"] and status["reason"] is None
    assert status["losing_streak"] == 0
    assert status["peak_equity"] == pytest.approx(10_000 - 10)
    assert len(state.get_open_positions()) == 1  # entries allowed again


def test_zero_thresholds_disable_the_halt(state):
    state.set_setting("max_drawdown_halt_pct", 0.0)
    state.set_setting("max_losing_streak_halt", 0)
    engine = _engine(state, generate_synthetic_ohlcv(300))
    engine.tick()
    _lose(engine, 30, n=20, qty=10)  # 60 % drawdown, 20 losses in a row
    engine.tick()
    assert state.get_setting("safety_halt_active") is False
