"""Order execution layer: paper (simulated) and live (exchange) clients."""

from execution.base import BaseExecutionClient, Fill
from execution.live import LiveExecutionClient
from execution.paper import PaperExecutionClient


def build_execution_client(config, state, exchange) -> BaseExecutionClient:
    """Paper unless PAPER_TRADING is explicitly false (and config validated)."""
    if config.paper_trading:
        return PaperExecutionClient(state, exchange, starting_balance=config.paper_starting_balance,
                                    fee_rate=config.paper_fee_rate, slippage_bps=config.paper_slippage_bps)
    return LiveExecutionClient(state, exchange, market_type=config.market_type, quote_currency=config.quote_currency,
                               fee_rate_estimate=config.paper_fee_rate)


__all__ = ["BaseExecutionClient", "Fill", "PaperExecutionClient", "LiveExecutionClient", "build_execution_client"]
