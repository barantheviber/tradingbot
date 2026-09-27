"""Run the real API on sample data, for developing the mobile / desktop apps.

    python -m api.demo                      # http://127.0.0.1:8765, token demo-token-0123456789
    python -m api.demo --port 9000 --token my-long-dev-token

Nothing here touches an exchange or your bot's database: state lives in an
in-memory SQLite database, candles are synthetic, and a small loop plays the
bot's part (heartbeat, a log line now and then, and marking queued close
commands done). The routes, auth and validation are exactly ``api.server``'s.
"""

from __future__ import annotations

import argparse
import random
import re
import sys
import threading
import time
from typing import Dict

import pandas as pd

from api.server import create_app
from backtest import generate_synthetic_ohlcv
from config import DEFAULT_SETTINGS, Config
from risk_manager import unrealized_pnl
from state_manager import StateManager

DEMO_TOKEN = "demo-token-0123456789"
SYMBOLS = {"BTC/USDT": 65_000.0, "ETH/USDT": 3_200.0}
STARTING_EQUITY = 10_000.0
TICK_SEC = 2.0
_TF_MS = {"s": 1_000, "m": 60_000, "h": 3_600_000, "d": 86_400_000, "w": 604_800_000, "M": 2_592_000_000}


def timeframe_ms(timeframe: str) -> int:
    m = re.match(r"^(\d+)([smhdwM])$", timeframe)
    return int(m.group(1)) * _TF_MS[m.group(2)] if m else 3_600_000


def synthetic_candles(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    """Deterministic random walk per symbol/timeframe whose last candle is the current one."""
    tf = timeframe_ms(timeframe)
    seed = sum(map(ord, symbol + timeframe))
    df = generate_synthetic_ohlcv(limit, seed=seed, start_price=1.0, timeframe_ms=tf)
    scale = SYMBOLS.get(symbol, 100.0) / float(df["close"].iloc[-1])
    for col in ("open", "high", "low", "close"):
        df[col] = df[col] * scale
    last_open = int(time.time() * 1000) // tf * tf
    df["timestamp"] = last_open - (limit - 1 - pd.RangeIndex(limit)) * tf
    return df


class DemoCandles:
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        return synthetic_candles(symbol, timeframe, limit)


def seed_state(state: StateManager, config: Config) -> None:
    state.seed_default_settings(DEFAULT_SETTINGS)
    state.get_or_create_day_start_equity(config.mode, STARTING_EQUITY)
    rng = random.Random(1)
    for i in range(8):
        symbol = list(SYMBOLS)[i % 2]
        entry = SYMBOLS[symbol] * (1 + rng.uniform(-0.03, 0.03))
        side = "long" if i % 3 else "short"
        qty = round(100.0 / (entry * 0.02), 4)
        pid = state.open_position(symbol=symbol, side=side, quantity=qty, entry_price=entry,
                                  stop_loss=entry * (0.98 if side == "long" else 1.02),
                                  take_profit=entry * (1.04 if side == "long" else 0.96), mode=config.mode,
                                  fees=entry * qty * 0.001)
        pnl = rng.choice([200.0, -100.0, 180.0, -95.0])
        state.mark_position_closed(pid, exit_price=entry * (1 + pnl / (entry * qty)), pnl=pnl,
                                   fees=entry * qty * 0.002, reason="take_profit" if pnl > 0 else "stop_loss")

    btc, eth = SYMBOLS["BTC/USDT"], SYMBOLS["ETH/USDT"]
    pid = state.open_position(symbol="BTC/USDT", side="long", quantity=0.08, entry_price=btc * 0.985,
                              stop_loss=btc * 0.965, take_profit=btc * 1.025, mode=config.mode, fees=5.0,
                              atr_at_entry=btc * 0.01)
    state.update_position(pid, stop_loss=btc * 0.975, highest_price=btc * 1.003)  # trailed once
    state.open_position(symbol="ETH/USDT", side="short", quantity=1.2, entry_price=eth * 1.004,
                        stop_loss=eth * 1.024, take_profit=eth * 0.964, mode=config.mode, fees=3.8,
                        atr_at_entry=eth * 0.012)
    state.set_state("bot_status", {"status": "running", "mode": config.mode})
    state.log_event("INFO", "engine", "Demo bot started (sample data, no exchange)")
    state.log_event("INFO", "signal", "BTC/USDT long signal: 4/4 confirmations", symbol="BTC/USDT")
    state.log_event("WARNING", "risk", "ETH/USDT exposure close to limit", symbol="ETH/USDT")


def _prices() -> Dict[str, float]:
    return {s: p * (1 + random.uniform(-0.002, 0.002)) for s, p in SYMBOLS.items()}


def tick(state: StateManager, config: Config) -> None:
    """One step of the pretend bot."""
    prices = _prices()
    for cmd in state.get_pending_commands():
        if cmd["command"] != "close_position":
            state.complete_command(cmd["id"], "failed", "demo only handles close_position")
            continue
        pos = state.get_position(int(cmd["payload"].get("position_id", 0)))
        if not pos or pos["status"] != "open":
            state.complete_command(cmd["id"], "failed", "position is not open")
            continue
        exit_price = prices[pos["symbol"]]
        pnl = unrealized_pnl(pos["side"], pos["entry_price"], exit_price, pos["quantity"]) - (pos["fees"] or 0)
        state.mark_position_closed(pos["id"], exit_price=exit_price, pnl=pnl, fees=pos["fees"] or 0, reason="manual")
        state.complete_command(cmd["id"], "done", f"demo: closed at {exit_price:.2f}")
        state.log_event("INFO", "command", f"Closed #{pos['id']} on request", symbol=pos["symbol"])

    realized = state.realized_pnl(config.mode) or 0.0
    unreal = sum(unrealized_pnl(p["side"], p["entry_price"], prices[p["symbol"]], p["quantity"]) - (p["fees"] or 0)
                 for p in state.get_open_positions(mode=config.mode))
    state.set_state("heartbeat", {"ts": time.time(), "equity": STARTING_EQUITY + realized + unreal, "prices": prices})
    if random.random() < 0.15:
        symbol = random.choice(list(SYMBOLS))
        state.log_event("INFO", "decision", f"{symbol}: no entry, {random.randint(1, 3)}/4 confirmations",
                        symbol=symbol)


def build(token: str = DEMO_TOKEN):
    config = Config(symbols=list(SYMBOLS), timeframe="1h", api_token=token,
                    paper_starting_balance=STARTING_EQUITY)
    state = StateManager(":memory:")
    seed_state(state, config)
    tick(state, config)
    return config, state, create_app(config, state, candle_factory=DemoCandles)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="tradingbot API on sample data (no exchange, no real DB)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token", default=DEMO_TOKEN)
    args = parser.parse_args(argv)
    if len(args.token) < 16:
        parser.error("--token must be at least 16 characters")

    import uvicorn

    config, state, app = build(args.token)

    def loop() -> None:
        while True:
            time.sleep(TICK_SEC)
            tick(state, config)

    threading.Thread(target=loop, daemon=True).start()
    shown = args.token if args.token == DEMO_TOKEN else "(from --token)"
    print(f"Demo API on http://{args.host}:{args.port}  token: {shown}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, access_log=False, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
