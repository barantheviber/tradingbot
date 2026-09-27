"""
Real execution against the exchange via exchange_client.ExchangeClient.
Every order goes through the same retry/backoff wrapper as market data
calls, and a non-retryable error (e.g. InsufficientFunds) is surfaced as a
failed ExecutionResult rather than raised, so bot_engine can log and skip
the cycle instead of crashing the whole process.
"""
from __future__ import annotations

from exchange_client import ExchangeClient, ExchangeClientError, RetryExhaustedError
from execution.base import BaseExecutionClient, ExecutionResult
from strategy import Side


class LiveExecutionClient(BaseExecutionClient):
    def __init__(self, exchange_client: ExchangeClient, quote_currency: str = "USDT"):
        super().__init__(name="live")
        self.exchange_client = exchange_client
        self.quote_currency = quote_currency

    def _market_side(self, side: Side, closing: bool) -> str:
        # Opening a long or closing a short = buy; opening a short or
        # closing a long = sell. (Spot-style; for a futures/margin
        # exchange with native short support, ccxt's `side` param behaves
        # the same way at the order level.)
        if (side == Side.LONG and not closing) or (side == Side.SHORT and closing):
            return "buy"
        return "sell"

    def open_position(self, symbol: str, side: Side, quantity: float, price: float) -> ExecutionResult:
        order_side = self._market_side(side, closing=False)
        try:
            order = self.exchange_client.create_market_order(symbol, order_side, quantity)
        except (ExchangeClientError, RetryExhaustedError) as exc:
            self.log_error(f"[LIVE] Failed to open {side.value} {symbol}: {exc}")
            return ExecutionResult(success=False, error=str(exc))

        filled_price = order.get("average") or order.get("price") or price
        filled_qty = order.get("filled") or quantity
        self.log_decision(
            f"[LIVE] Opened {side.value} {filled_qty:.8f} {symbol} @ {filled_price:.8f} "
            f"(order_id={order.get('id')})"
        )
        return ExecutionResult(
            success=True,
            filled_price=filled_price,
            filled_quantity=filled_qty,
            order_id=str(order.get("id")),
            raw=order,
        )

    def close_position(self, symbol: str, side: Side, quantity: float, price: float) -> ExecutionResult:
        order_side = self._market_side(side, closing=True)
        try:
            order = self.exchange_client.create_market_order(symbol, order_side, quantity)
        except (ExchangeClientError, RetryExhaustedError) as exc:
            self.log_error(f"[LIVE] Failed to close {side.value} {symbol}: {exc}")
            return ExecutionResult(success=False, error=str(exc))

        filled_price = order.get("average") or order.get("price") or price
        filled_qty = order.get("filled") or quantity
        self.log_decision(
            f"[LIVE] Closed {side.value} {filled_qty:.8f} {symbol} @ {filled_price:.8f} "
            f"(order_id={order.get('id')})"
        )
        return ExecutionResult(
            success=True,
            filled_price=filled_price,
            filled_quantity=filled_qty,
            order_id=str(order.get("id")),
            raw=order,
        )

    def get_account_equity(self) -> float:
        balance = self.exchange_client.fetch_balance()
        total = balance.get("total", {}) if isinstance(balance, dict) else {}
        return float(total.get(self.quote_currency, 0.0))
