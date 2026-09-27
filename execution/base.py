"""
Common interface shared by paper and live execution clients.

bot_engine.py only ever talks to this interface, so switching between paper
and live trading is a one-line change (see main.py) and both back-ends log
and summarize performance identically.
"""
from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from typing import Optional

from strategy import Side


@dataclass
class ExecutionResult:
    success: bool
    filled_price: Optional[float] = None
    filled_quantity: Optional[float] = None
    order_id: Optional[str] = None
    error: Optional[str] = None
    raw: Optional[dict] = field(default=None, repr=False)


class BaseExecutionClient(abc.ABC):
    """
    Both PaperExecutionClient and LiveExecutionClient implement this same
    surface, so bot_engine.py, the dashboard and the logs behave
    identically regardless of which mode the bot is running in.
    """

    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(f"execution.{name}")

    # -- Order placement -------------------------------------------------
    @abc.abstractmethod
    def open_position(self, symbol: str, side: Side, quantity: float, price: float) -> ExecutionResult:
        """Open a new position at (approximately) `price`."""

    @abc.abstractmethod
    def close_position(self, symbol: str, side: Side, quantity: float, price: float) -> ExecutionResult:
        """Close an existing position at (approximately) `price`."""

    @abc.abstractmethod
    def get_account_equity(self) -> float:
        """Return current total account equity in quote currency."""

    # -- Shared logging/performance-summary interface --------------------
    def log_decision(self, message: str) -> None:
        self.logger.info(message)

    def log_error(self, message: str) -> None:
        self.logger.error(message)

    def performance_summary(self, trades: list) -> dict:
        """
        Given a list of state_manager.TradeRecord, compute a small,
        back-end-agnostic performance summary. Both paper and live use the
        exact same trade history shape, so this method lives once here.
        """
        if not trades:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "avg_pnl": 0.0,
                "best_trade": 0.0,
                "worst_trade": 0.0,
            }
        pnls = [t.pnl for t in trades]
        wins = [p for p in pnls if p > 0]
        return {
            "total_trades": len(trades),
            "win_rate": len(wins) / len(trades) * 100.0,
            "total_pnl": sum(pnls),
            "avg_pnl": sum(pnls) / len(trades),
            "best_trade": max(pnls),
            "worst_trade": min(pnls),
        }
