"""Entry points the Android app's BotService calls through Chaquopy.

The phone runs the same bot and API as the desktop app (local_runtime.LocalRuntime);
the app's screens talk to the API on 127.0.0.1. The service passes the user's setup as
JSON. Only a fixed set of variables is accepted and paper mode is always forced, so the
phone app cannot switch to live trading.
"""

from __future__ import annotations

import json
import os
ALLOWED = {"EXCHANGE_ID", "MARKET_TYPE", "SYMBOLS", "TIMEFRAME", "PAPER_STARTING_BALANCE", "API_PORT", "API_TOKEN"}
# Everything config.py reads; cleared first so nothing left over from an earlier start leaks in.
CONFIG_NAMES = {
    "SYMBOLS", "EXCHANGE_ID", "MARKET_TYPE", "USE_TESTNET", "API_KEY", "API_SECRET", "API_PASSWORD",
    "PAPER_TRADING", "LIVE_TRADING_CONFIRM", "TIMEFRAME", "OHLCV_LIMIT", "POLL_INTERVAL_SEC", "DB_PATH",
    "LOG_DIR", "LOG_LEVEL", "PAPER_STARTING_BALANCE", "PAPER_FEE_RATE", "PAPER_SLIPPAGE_BPS", "MAX_RETRIES",
    "RETRY_BASE_DELAY", "RETRY_MAX_DELAY", "API_HOST", "API_PORT", "API_TOKEN", "API_CORS_ORIGINS",
}

_runtime = None


def apply_env(config_json: str) -> None:
    env = json.loads(config_json).get("env", {})
    unknown = set(env) - ALLOWED
    if unknown:
        raise ValueError(f"Unsupported settings: {', '.join(sorted(unknown))}")
    for name in CONFIG_NAMES:
        os.environ.pop(name, None)
    for key, value in env.items():
        os.environ[key] = str(value)
    os.environ.update(PAPER_TRADING="true", API_HOST="127.0.0.1", DB_PATH="data/tradingbot.db", LOG_DIR="logs")


def start(data_dir: str, config_json: str) -> None:
    """Start the bot and the API in background threads; raises with a readable message."""
    global _runtime
    if _runtime is not None and _runtime.running:
        return
    apply_env(config_json)
    os.makedirs(data_dir, exist_ok=True)
    os.chdir(data_dir)
    from local_runtime import LocalRuntime

    _runtime = LocalRuntime(env_file="")
    _runtime.start()


def stop(timeout: float = 60.0) -> None:
    if _runtime is not None:
        _runtime.stop(timeout)


def status() -> str:
    if _runtime is None:
        return json.dumps({"running": False, "error": None, "started_at": None})
    return json.dumps(_runtime.status())

