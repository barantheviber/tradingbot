"""Real order execution through ``ExchangeClient``.

Stops and targets are enforced by the bot on every loop (software stops), so
the bot must be running for them to trigger. Keep that in mind before going
live and prefer testnet (USE_TESTNET=true) first.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Tuple

from execution.base import BaseExecutionClient, Fill, check_market_limits
from risk_manager import unrealized_pnl


class LiveExecutionClient(BaseExecutionClient):
    mode = "live"

    def __init__(self, state, exchange, market_type: str = "spot", quote_currency: str = "USDT",
                 fee_rate_estimate: float = 0.001):
        super().__init__(state, exchange)
        self.market_type = market_type
        self.quote = quote_currency
        self.fee_rate_estimate = fee_rate_estimate

    def supports_side(self, side: str) -> bool:
        return side == "long" or self.market_type != "spot"

    def normalize_quantity(self, symbol: str, quantity: float) -> float:
        return self.exchange.amount_to_precision(symbol, quantity)

    def check_order_limits(self, symbol: str, quantity: float, price: float) -> Tuple[bool, str]:
        if quantity <= 0:
            return False, "quantity below exchange precision"
        limits = self.exchange.market_limits(symbol)
        return check_market_limits(limits, quantity, price)

    def _submit_market_order(self, symbol: str, side: str, quantity: float, reference_price: float,
                             reduce_only: bool = False) -> Fill:
        params: Dict[str, Any] = {}
        if reduce_only and self.market_type != "spot":
            params["reduceOnly"] = True
        if reduce_only and self.market_type == "spot" and side == "sell":
            quantity = self._sellable_quantity(symbol, quantity)
        order = self.exchange.create_market_order(symbol, side, quantity, params)
        if not order.get("average") and order.get("id"):
            try:
                order = {**order, **{k: v for k, v in self.exchange.fetch_order(order["id"], symbol).items() if v}}
            except Exception as exc:  # fill details are best-effort; the order itself went through
                self.log.warning("Could not fetch order details", extra={"symbol": symbol, "error": str(exc)})
        price = float(order.get("average") or order.get("price") or reference_price)
        filled = float(order.get("filled") or quantity)
        fee = self._fee_in_quote(order, symbol, price, filled)
        base_fee = self._fee_in_base(order, symbol)
        if side == "buy" and self.market_type == "spot" and 0 < base_fee < filled:
            # The exchange took the fee out of the bought coins, so we hold less than
            # `filled`. Track what we actually hold, or the closing sell would ask for
            # more than the balance and fail with InsufficientFunds on every loop.
            filled -= base_fee
        return Fill(price=price, quantity=filled, fee=fee,
                    order_id=str(order.get("id")) if order.get("id") else None)

    def _sellable_quantity(self, symbol: str, quantity: float) -> float:
        """Cap a spot sell at the free base balance (positions opened before the
        base-fee fix recorded the gross amount). Falls back to ``quantity``."""
        base = symbol.split("/")[0]
        try:
            free = float((self.exchange.fetch_balance().get("free") or {}).get(base) or 0.0)
        except Exception as exc:
            self.log.warning("Balance unavailable before sell", extra={"symbol": symbol, "error": str(exc)})
            return quantity
        if 0 < free < quantity:
            self.log.warning("Selling the free balance instead of the recorded quantity",
                             extra={"symbol": symbol, "recorded": quantity, "free": free})
            return free
        return quantity

    @staticmethod
    def _fee_in_base(order: Mapping[str, Any], symbol: str) -> float:
        base = symbol.split("/")[0]
        fees = order.get("fees") or ([order["fee"]] if order.get("fee") else [])
        return sum(float(f.get("cost") or 0.0) for f in fees if f and f.get("currency") == base)

    def _fee_in_quote(self, order: Mapping[str, Any], symbol: str, price: float, filled: float) -> float:
        fee = order.get("fee") or {}
        cost, currency = fee.get("cost"), fee.get("currency")
        base = symbol.split("/")[0]
        if cost is not None and currency == self.quote:
            return float(cost)
        if cost is not None and currency == base:
            return float(cost) * price
        return price * filled * self.fee_rate_estimate  # unknown/other currency (e.g. BNB): estimate

    def _quote_balance(self) -> Tuple[float, float]:
        balance = self.exchange.fetch_balance()
        total = float((balance.get("total") or {}).get(self.quote) or 0.0)
        free = float((balance.get("free") or {}).get(self.quote) or 0.0)
        return total, free

    def get_equity(self, prices: Mapping[str, float]) -> float:
        total, _ = self._quote_balance()
        for p in self.open_positions():
            price = prices.get(p["symbol"], p["entry_price"])
            if self.market_type == "spot":
                total += p["quantity"] * price  # base asset held
            else:
                total += unrealized_pnl(p["side"], p["entry_price"], price, p["quantity"])
        return total

    def get_available_cash(self, prices: Mapping[str, float]) -> float:
        return self._quote_balance()[1]

    def reconcile(self, positions: List[Dict[str, Any]]) -> None:
        """Warn when the exchange balance cannot cover a restored spot position."""
        if self.market_type != "spot" or not positions:
            return
        try:
            totals = self.exchange.fetch_balance().get("total") or {}
        except Exception as exc:
            self.log.warning("Reconcile skipped: balance unavailable", extra={"error": str(exc)})
            return
        needed: Dict[str, float] = {}
        for p in positions:
            base = p["symbol"].split("/")[0]
            needed[base] = needed.get(base, 0.0) + float(p["quantity"])
        for asset, qty in needed.items():
            held = float(totals.get(asset) or 0.0)
            if held + 1e-12 < qty * 0.99:
                msg = f"Reconcile: DB expects {qty} {asset} but exchange holds {held}; check manually"
                self.log.warning(msg)
                self.state.log_event("WARNING", "reconcile", msg, data={"asset": asset, "expected": qty,
                                                                        "held": held})
