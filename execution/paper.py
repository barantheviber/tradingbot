"""
Simulated execution: no real orders are ever sent. Fills happen instantly
at the requested price (optionally nudged by a configurable slippage bps
value) and the account balance is tracked purely in memory / SQLite via
state_manager, never on the exchange.
"""
from __future__ import annotations

from execution.base import BaseExecutionClient, ExecutionResult
from strategy import Side


class PaperExecutionClient(BaseExecutionClient):
    def __init__(self, starting_balance: float, slippage_bps: float = 2.0):
        super().__init__(name="paper")
        self._balance = starting_balance
        self.slippage_bps = slippage_bps

    def _apply_slippage(self, price: float, side: Side, closing: bool) -> float:
        """
        Slippage always works against the trader: entries fill slightly
        worse, exits fill slightly worse.
        """
        factor = self.slippage_bps / 10_000.0
        # Opening a long or closing a short means buying -> price nudges up.
        buying = (side == Side.LONG and not closing) or (side == Side.SHORT and closing)
        return price * (1 + factor) if buying else price * (1 - factor)

    def open_position(self, symbol: str, side: Side, quantity: float, price: float) -> ExecutionResult:
        fill_price = self._apply_slippage(price, side, closing=False)
        self.log_decision(
            f"[PAPER] Opening {side.value} {quantity:.8f} {symbol} @ {fill_price:.8f}"
        )
        return ExecutionResult(
            success=True,
            filled_price=fill_price,
            filled_quantity=quantity,
            order_id=f"paper-{symbol}-{side.value}-{fill_price:.2f}",
        )

    def close_position(self, symbol: str, side: Side, quantity: float, price: float) -> ExecutionResult:
        fill_price = self._apply_slippage(price, side, closing=True)
        self.log_decision(
            f"[PAPER] Closing {side.value} {quantity:.8f} {symbol} @ {fill_price:.8f}"
        )
        return ExecutionResult(
            success=True,
            filled_price=fill_price,
            filled_quantity=quantity,
            order_id=f"paper-close-{symbol}-{side.value}-{fill_price:.2f}",
        )

    def get_account_equity(self) -> float:
        return self._balance

    def apply_realized_pnl(self, pnl: float) -> None:
        """Called by bot_engine after a position closes, to keep the paper
        balance in sync with realized PnL."""
        self._balance += pnl

    def set_balance(self, balance: float) -> None:
        """Used on startup to restore the last known paper balance."""
        self._balance = balance
