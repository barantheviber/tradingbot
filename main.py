"""Entry point.

    python main.py                 # run the bot (paper mode unless configured otherwise)
    python main.py --once          # a single loop, then exit (smoke test)
    python main.py --show-settings # print live-editable settings from the DB
    python main.py --set risk_per_trade_pct=0.5 --set max_open_positions=2
"""

from __future__ import annotations

import argparse
import json
import sys

from bot_engine import BotEngine
from config import DEFAULT_SETTINGS, legacy_env_warnings, load_config
from exchange_client import ExchangeClient
from execution import build_execution_client
from logging_setup import setup_logging
from risk_manager import RiskManager
from state_manager import LegacyDatabaseError, StateManager


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Modular ccxt trading bot")
    parser.add_argument("--env-file", default=".env", help="Path to the .env file (default: .env)")
    parser.add_argument("--once", action="store_true", help="Run a single loop and exit")
    parser.add_argument("--show-settings", action="store_true", help="Print strategy/risk settings and exit")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                        help="Update a live setting in the DB and exit (repeatable)")
    return parser.parse_args(argv)


def build_engine(config, state: StateManager) -> BotEngine:
    """Wire the engine from a loaded config (shared with local_runtime.py)."""
    # Paper mode never gets API keys: public market data is all it needs.
    exchange = ExchangeClient.from_config(config, public_only=config.paper_trading)
    executor = build_execution_client(config, state, exchange)
    return BotEngine(config, state, exchange, executor, RiskManager(state.get_all_settings))


def main(argv=None) -> int:
    args = parse_args(argv)
    config = load_config(args.env_file)
    log = setup_logging(config.log_dir, config.log_level, secrets=config.secrets())

    for warning in legacy_env_warnings():
        log.warning(f"Config: {warning}")

    try:
        state = StateManager(config.db_path)
    except LegacyDatabaseError as exc:
        log.error(str(exc))
        return 2
    state.seed_default_settings(DEFAULT_SETTINGS)

    if args.show_settings or args.set:
        for item in args.set:
            key, _, value = item.partition("=")
            if key not in DEFAULT_SETTINGS:
                log.error(f"Unknown setting: {key}")
                return 2
            state.set_setting(key.strip(), value.strip())
        print(json.dumps(state.get_all_settings(), indent=2, ensure_ascii=False))
        return 0

    problems = config.validate()
    if problems:
        for p in problems:
            log.error(f"Config error: {p}")
        return 2

    log.info(f"Loaded {config}")
    if not config.paper_trading:
        log.warning("=" * 70)
        log.warning("LIVE TRADING MODE - real orders will be sent to %s%s", config.exchange_id,
                    " (TESTNET)" if config.use_testnet else "")
        log.warning("=" * 70)

    engine = build_engine(config, state)
    engine.install_signal_handlers()
    try:
        engine.run(once=args.once)
    except Exception as exc:
        log.critical(f"Bot terminated: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
