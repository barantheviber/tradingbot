"""
Entry point. Wires config -> exchange_client -> state_manager ->
execution client (paper or live, based on PAPER_TRADING) -> bot_engine,
then runs the loop until SIGINT/SIGTERM.
"""
from __future__ import annotations

import logging

from bot_engine import BotEngine, setup_logging
from config import config
from exchange_client import ExchangeClient
from execution.live import LiveExecutionClient
from execution.paper import PaperExecutionClient
from state_manager import StateManager

logger = logging.getLogger(__name__)


def build_execution_client(cfg, exchange_client: ExchangeClient, state: StateManager):
    if cfg.paper_trading:
        starting_balance = state.get_setting(
            "paper_balance", cfg.account.paper_starting_balance
        )
        client = PaperExecutionClient(starting_balance=starting_balance)
        return client
    return LiveExecutionClient(exchange_client, quote_currency=cfg.account.quote_currency)


def main() -> None:
    config.validate()
    setup_logging(config)

    logger.info(
        "Booting trading bot | exchange=%s symbol=%s timeframe=%s paper_trading=%s",
        config.exchange.exchange_id,
        config.trading.symbol,
        config.trading.timeframe,
        config.paper_trading,
    )

    exchange_client = ExchangeClient(config)
    state = StateManager(config.paths.db_path)
    execution_client = build_execution_client(config, exchange_client, state)

    if not config.paper_trading:
        logger.warning(
            "PAPER_TRADING is False - this bot will place REAL orders on %s.",
            config.exchange.exchange_id,
        )

    engine = BotEngine(config, exchange_client, execution_client, state)
    try:
        engine.run_forever()
    finally:
        if isinstance(execution_client, PaperExecutionClient):
            state.set_setting("paper_balance", execution_client.get_account_equity())
        state.close()


if __name__ == "__main__":
    main()
