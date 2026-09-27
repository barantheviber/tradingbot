import pandas as pd
import pytest

from backtest import generate_synthetic_ohlcv
from bot_engine import BotEngine
from config import DEFAULT_SETTINGS, Config
from execution import PaperExecutionClient
from risk_manager import RiskManager
from state_manager import StateManager


@pytest.fixture
def state(tmp_path):
    s = StateManager(str(tmp_path / "t.db"))
    s.seed_default_settings(DEFAULT_SETTINGS)
    return s


def test_paper_open_close_pnl_with_fees(state):
    ex = PaperExecutionClient(state, starting_balance=1_000, fee_rate=0.001, slippage_bps=0)
    pos = ex.open_position("BTC/USDT", "long", 2, 100, stop_loss=95, take_profit=110, atr=2)
    assert pos["entry_price"] == 100 and pos["fees"] == pytest.approx(0.2)
    assert ex.get_equity({"BTC/USDT": 105}) == pytest.approx(1_000 - 0.2 + 10)
    assert ex.get_available_cash({}) == pytest.approx(1_000 - 0.2 - 200)
    closed = ex.close_position(pos, 110, "take_profit")
    assert closed["pnl"] == pytest.approx(20 - 0.2 - 0.22)
    assert ex.get_equity({}) == pytest.approx(1_000 + closed["pnl"])
    stats = ex.performance_summary(1_000)
    assert stats["trades"] == 1 and stats["win_rate_pct"] == 100.0
    assert [t["action"] for t in state.get_trades()] == ["close", "open"]


def test_paper_short_pnl(state):
    ex = PaperExecutionClient(state, starting_balance=1_000, fee_rate=0.0, slippage_bps=0)
    pos = ex.open_position("ETH/USDT", "short", 1, 100, 105, 90, 2)
    assert ex.close_position(pos, 90, "take_profit")["pnl"] == pytest.approx(10)


class FakeExchangeClient:
    """Serves synthetic closed candles; `now` controls which candles are closed."""

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


def _engine(state, df):
    cfg = Config(symbols=["BTC/USDT"], timeframe="1h", poll_interval_sec=1)
    ex = FakeExchangeClient(df)
    executor = PaperExecutionClient(state, ex, starting_balance=10_000, slippage_bps=0)
    return BotEngine(cfg, state, ex, executor, RiskManager(state.get_all_settings), sleep_fn=lambda s: None), ex


def _find_signal_index(df, settings):
    from strategy import StrategyParams, compute_indicators

    ind = compute_indicators(df, StrategyParams.from_settings(settings))
    return int(ind.index[ind["long_signal"]][0])


def test_engine_opens_once_per_candle_and_restores_after_restart(state, tmp_path):
    state.set_setting("min_confirmations", 2)
    df = generate_synthetic_ohlcv(3000, seed=7)
    idx = _find_signal_index(df, state.get_all_settings())
    candles = df.iloc[: idx + 1]

    engine, ex = _engine(state, candles)
    engine.run(once=True)
    open_pos = state.get_open_positions(mode="paper")
    assert len(open_pos) == 1 and open_pos[0]["side"] == "long"
    risk = open_pos[0]["quantity"] * (open_pos[0]["entry_price"] - open_pos[0]["stop_loss"])
    assert risk <= 10_000 * 0.01 + 1e-6

    # same closed candle again -> no new decision, no duplicate
    engine.tick()
    assert len(state.get_open_positions(mode="paper")) == 1

    # "crash" and restart with a fresh engine on the same DB
    state2 = StateManager(state.db_path)
    engine2, _ = _engine(state2, candles)
    engine2.startup()
    assert [p["id"] for p in engine2.executor.open_positions()] == [open_pos[0]["id"]]


def test_engine_stop_loss_and_manual_close(state):
    state.set_setting("min_confirmations", 2)
    df = generate_synthetic_ohlcv(3000, seed=7)
    idx = _find_signal_index(df, state.get_all_settings())
    engine, ex = _engine(state, df.iloc[: idx + 1])
    engine.run(once=True)
    pos = state.get_open_positions(mode="paper")[0]

    ex.price = pos["stop_loss"] * 0.99
    engine.tick()
    closed = state.get_position(pos["id"])
    assert closed["status"] == "closed" and closed["exit_reason"] == "stop_loss"

    pid = engine.executor.open_position("BTC/USDT", "long", 0.01, ex.price, ex.price * 0.9, ex.price * 1.2, 1)["id"]
    state.enqueue_command("close_position", {"position_id": pid})
    engine._process_commands()
    assert state.get_position(pid)["exit_reason"] == "manual"
    assert state.get_pending_commands() == []


def test_kill_switch_blocks_entries(state):
    state.set_setting("min_confirmations", 2)
    state.set_setting("trading_enabled", False)
    df = generate_synthetic_ohlcv(3000, seed=7)
    idx = _find_signal_index(df, state.get_all_settings())
    engine, _ = _engine(state, df.iloc[: idx + 1])
    engine.run(once=True)
    assert state.get_open_positions() == []
    assert any("kill switch" in e["message"] for e in state.get_events())


def test_request_stop_interrupts_sleep(state):
    engine, _ = _engine(state, generate_synthetic_ohlcv(300))
    calls = []

    def fake_sleep(s):
        calls.append(s)
        engine.request_stop("test")

    engine._sleep = fake_sleep
    engine._interruptible_sleep(600)
    assert len(calls) == 1 and calls[0] <= 1.0
