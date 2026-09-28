"""Simulated execution: fills at the reference price +/- slippage, charges a fee.

Account balance is derived from the database (starting balance + realised
PnL - fees of open positions), so it survives restarts with no extra state.
"""

from __future__ import annotations

import uuid
from typing import Mapping

from execution.base import BaseExecutionClient, Fill, check_market_limits
from risk_manager import unrealized_pnl


class PaperExecutionClient(BaseExecutionClient):
    mode = "paper"

    def __init__(self, state, exchange=None, starting_balance: float = 10_000.0, fee_rate: float = 0.001,
                 slippage_bps: float = 5.0):
        super().__init__(state, exchange)
        self.starting_balance = starting_balance
        self.fee_rate = fee_rate
        self.slippage = slippage_bps / 10_000.0

    def normalize_quantity(self, symbol: str, quantity: float) -> float:
        """Round down to the exchange's amount precision, as the live client does,
        so paper results match what the exchange would accept."""
        if self.exchange is None or not hasattr(self.exchange, "amount_to_precision"):
            return quantity
        try:
            size = self._contract_size(symbol)
            return self.exchange.amount_to_precision(symbol, quantity / size) * size
        except Exception as exc:  # markets unavailable: keep the unrounded size
            self.log.debug("Precision unavailable", extra={"symbol": symbol, "error": str(exc)})
            return quantity

    def check_order_limits(self, symbol: str, quantity: float, price: float):
        if quantity <= 0:
            return False, "quantity below exchange precision"
        if self.exchange is None or not hasattr(self.exchange, "market_limits"):
            return True, "ok"
        try:
            limits = dict(self.exchange.market_limits(symbol))
            if limits.get("min_amount"):  # stated in contracts on futures / swaps
                limits["min_amount"] = float(limits["min_amount"]) * self._contract_size(symbol)
        except Exception:
            return True, "ok"
        return check_market_limits(limits, quantity, price)

    def _submit_market_order(self, symbol: str, side: str, quantity: float, reference_price: float,
                             reduce_only: bool = False) -> Fill:
        price = reference_price * (1 + self.slippage) if side == "buy" else reference_price * (1 - self.slippage)
        fee = price * quantity * self.fee_rate
        return Fill(price=price, quantity=quantity, fee=fee, order_id=f"paper-{uuid.uuid4().hex[:12]}")

    def _cash_base(self) -> float:
        return self.starting_balance + self.state.realized_pnl(self.mode) - self.state.open_fees(self.mode)

    def get_equity(self, prices: Mapping[str, float]) -> float:
        equity = self._cash_base()
        for p in self.open_positions():
            price = prices.get(p["symbol"], p["entry_price"])
            equity += unrealized_pnl(p["side"], p["entry_price"], price, p["quantity"])
        return equity

    def get_available_cash(self, prices: Mapping[str, float]) -> float:
        committed = sum(p["quantity"] * p["entry_price"] for p in self.open_positions())
        return max(0.0, self._cash_base() - committed)
