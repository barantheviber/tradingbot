"""Shared execution logic.

Subclasses only implement *how* an order is filled (``_submit_market_order``)
and how equity is measured. Opening/closing bookkeeping, PnL, trade logging
and the performance summary are identical for paper and live, so the two
modes cannot drift apart.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from exchange_client import AmbiguousOrderError
from logging_setup import get_logger
from performance import compute_performance, format_performance
from risk_manager import unrealized_pnl


@dataclass
class Fill:
    price: float
    quantity: float
    fee: float
    order_id: Optional[str] = None
    requested: Optional[float] = None  # amount asked for; None = the whole position


# Relative tolerance when comparing a filled amount with the requested one.
FILL_TOLERANCE = 1e-6


def check_market_limits(limits: Mapping[str, Any], quantity: float, price: float) -> Tuple[bool, str]:
    """Compare an order with the exchange's minimum amount / minimum cost."""
    if limits.get("min_amount") and quantity < limits["min_amount"]:
        return False, f"quantity {quantity} < min amount {limits['min_amount']}"
    if limits.get("min_cost") and quantity * price < limits["min_cost"]:
        return False, f"notional {quantity * price:.4f} < min cost {limits['min_cost']}"
    return True, "ok"


class BaseExecutionClient(ABC):
    mode: str = "base"

    def __init__(self, state, exchange):
        self.state = state
        self.exchange = exchange
        self.log = get_logger(f"execution.{self.mode}")

    # ------------------------------------------------------------ abstract
    @abstractmethod
    def _submit_market_order(self, symbol: str, side: str, quantity: float, reference_price: float,
                             reduce_only: bool = False) -> Fill:
        """Execute a market order; ``side`` is 'buy' or 'sell'."""

    @abstractmethod
    def get_equity(self, prices: Mapping[str, float]) -> float:
        """Account equity in quote currency, marking open positions at ``prices``."""

    @abstractmethod
    def get_available_cash(self, prices: Mapping[str, float]) -> float:
        """Quote currency that can still be committed to new positions."""

    # ---------------------------------------------------------- overridable
    def normalize_quantity(self, symbol: str, quantity: float) -> float:
        return quantity

    def check_order_limits(self, symbol: str, quantity: float, price: float) -> Tuple[bool, str]:
        return (quantity > 0, "ok" if quantity > 0 else "zero quantity")

    def supports_side(self, side: str) -> bool:
        return side in ("long", "short")

    def reconcile(self, positions: List[Dict[str, Any]]) -> None:
        """Hook to compare restored positions with the exchange (live only)."""

    # Exchange-side protective stops (live only; no-ops for paper).
    def protect_position(self, position: Mapping[str, Any]) -> None:
        """Place (or re-place) a resting stop order for ``position`` on the exchange."""

    def on_stop_moved(self, position: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        """The position's stop in state changed (trailing). Returns the closed
        position if the old exchange stop turned out to have filled already."""
        return None

    def sync_protective_stops(self) -> None:
        """Record positions whose exchange stop filled; re-place missing stops."""

    def _release_protective_stop(self, position: Mapping[str, Any]) -> Optional[Fill]:
        """Cancel the resting stop before the bot closes the position itself.
        Returns the stop's fill if it had already executed (position is gone)."""
        return None

    # Positions whose close order did not fill completely; the engine retries them.
    def pending_close_reason(self, position: Mapping[str, Any]) -> Optional[str]:
        return self.state.get_state(f"pending_close:{position['id']}")

    # ------------------------------------------------------------- shared
    def _contract_size(self, symbol: str) -> float:
        """Base units per exchange amount unit (1 on spot; e.g. 0.01 BTC per
        contract on OKX swaps). Exchange precision and minimums are stated in
        these units, while positions are kept in base units."""
        getter = getattr(self.exchange, "contract_size", None)
        size = float(getter(symbol)) if getter else 1.0
        return size if size > 0 else 1.0

    def open_positions(self) -> List[Dict[str, Any]]:
        return self.state.get_open_positions(mode=self.mode)

    def restore_open_positions(self) -> List[Dict[str, Any]]:
        positions = self.open_positions()
        for p in positions:
            self.log.info("Restored open position", extra={"position_id": p["id"], "symbol": p["symbol"],
                                                          "side": p["side"], "qty": p["quantity"],
                                                          "entry": p["entry_price"], "stop": p["stop_loss"]})
        self.reconcile(positions)
        self.state.log_event("INFO", "restore", f"Restored {len(positions)} open position(s)",
                             data={"ids": [p["id"] for p in positions]})
        return positions

    def open_position(self, symbol: str, side: str, quantity: float, reference_price: float, stop_loss: float,
                      take_profit: float, atr: float, reason: str = "signal") -> Optional[Dict[str, Any]]:
        if not self.supports_side(side):
            self._decision("WARNING", symbol, f"{side} not supported in {self.mode} mode on this market; skipped")
            return None
        qty = self.normalize_quantity(symbol, quantity)
        ok, why = self.check_order_limits(symbol, qty, reference_price)
        if not ok:
            self._decision("INFO", symbol, f"Entry skipped: {why}", {"qty": qty, "price": reference_price})
            return None

        try:
            fill = self._submit_market_order(symbol, "buy" if side == "long" else "sell", qty, reference_price)
        except AmbiguousOrderError as exc:
            # The order may exist. Remember the plan so it can be booked (with its
            # stop) once the exchange shows the order, and block new entries on
            # this symbol until then.
            self.state.set_state(f"pending_entry:{symbol}", {
                "client_order_id": exc.client_order_id, "since_ms": exc.since_ms, "side": side, "quantity": qty,
                "reference_price": reference_price, "stop_loss": stop_loss, "take_profit": take_profit,
                "atr": atr, "reason": reason})
            self._decision("ERROR", symbol, f"Entry order outcome unknown ({exc}); it will be looked up on the "
                                            "exchange and booked with its stop if it was filled")
            raise
        return self._book_entry(symbol, side, fill, reference_price, stop_loss, take_profit, atr, reason)

    def has_pending_entry(self, symbol: str) -> bool:
        return self.state.get_state(f"pending_entry:{symbol}") is not None

    def resolve_pending_orders(self) -> None:
        """Settle orders whose outcome was unknown (live only)."""

    def _book_entry(self, symbol: str, side: str, fill: Fill, reference_price: float, stop_loss: float,
                    take_profit: float, atr: float, reason: str) -> Optional[Dict[str, Any]]:
        if fill.quantity <= 0:
            self._decision("WARNING", symbol, "Entry order did not fill; no position opened",
                           {"order_id": fill.order_id})
            return None
        # keep the planned stop/target distances relative to the actual fill price
        shift = fill.price - reference_price
        stop = stop_loss + shift
        target = take_profit + shift if take_profit else take_profit

        position_id = self.state.open_position(
            symbol=symbol, side=side, quantity=fill.quantity, entry_price=fill.price, stop_loss=stop,
            take_profit=target, initial_stop=stop, atr_at_entry=atr, mode=self.mode, fees=fill.fee,
            entry_order_id=fill.order_id,
        )
        self.state.record_trade(position_id=position_id, symbol=symbol, side="buy" if side == "long" else "sell",
                                action="open", quantity=fill.quantity, price=fill.price, fee=fill.fee,
                                reason=reason, mode=self.mode, order_id=fill.order_id)
        self._trade_log("OPEN", symbol, {"position_id": position_id, "side": side, "qty": fill.quantity,
                                         "price": fill.price, "stop": stop, "take_profit": target,
                                         "fee": fill.fee, "reason": reason})
        position = self.state.get_position(position_id)
        self.protect_position(position)
        return position

    def close_position(self, position: Mapping[str, Any], reference_price: float,
                       reason: str) -> Optional[Dict[str, Any]]:
        earlier = self._resolve_unknown_exit(position)  # raises while still unknown
        if earlier is not None:  # an earlier exit order with an unclear answer did execute
            return self._record_close(position, earlier, reason)
        stop_fill = self._release_protective_stop(position)
        if stop_fill is not None:  # the exchange stop already closed it
            return self._record_close(position, stop_fill, "exchange_stop")
        side = position["side"]
        try:
            fill = self._submit_market_order(position["symbol"], "sell" if side == "long" else "buy",
                                             float(position["quantity"]), reference_price, reduce_only=True)
        except AmbiguousOrderError as exc:
            # Never re-send an exit whose outcome is unknown: look it up first next time.
            self.state.set_state(f"unknown_exit:{position['id']}", {
                "client_order_id": exc.client_order_id, "since_ms": exc.since_ms,
                "requested": float(position["quantity"]), "reference_price": reference_price})
            self.state.set_state(f"pending_close:{position['id']}", reason)
            self._decision("ERROR", position["symbol"], f"#{position['id']}: exit order outcome unknown ({exc}); "
                                                        "it will be looked up before any new exit order")
            raise
        return self._record_close(position, fill, reason)

    def _resolve_unknown_exit(self, position: Mapping[str, Any]) -> Optional[Fill]:
        """Live only: settle an exit order whose outcome was unknown."""
        return None

    def _record_close(self, position: Mapping[str, Any], fill: Fill, reason: str) -> Optional[Dict[str, Any]]:
        """Book a (possibly partial) exit fill.

        The position is only marked closed when the whole requested amount
        filled. Otherwise the remainder stays open under stop management, the
        exit is remembered as pending so the engine retries it, and the realised
        part is carried in runtime state until the final close.
        """
        pid, symbol, side = position["id"], position["symbol"], position["side"]
        quantity = float(position["quantity"])
        requested = quantity if fill.requested is None else float(fill.requested)
        remaining = max(0.0, requested - fill.quantity)
        if remaining > requested * FILL_TOLERANCE:
            remaining_n = self.normalize_quantity(symbol, remaining)
            ok, _ = self.check_order_limits(symbol, remaining_n, fill.price or float(position["entry_price"]))
            if not ok:  # below the exchange minimum: nothing more can be sold, treat as dust
                self._decision("WARNING", symbol, f"#{pid}: unfilled remainder {remaining} is below exchange "
                                                  "minimums; closing the position in the books")
                remaining = 0.0
        else:
            remaining = 0.0

        gross_key, pending_key = f"partial_gross:{pid}", f"pending_close:{pid}"
        carried = float(self.state.get_state(gross_key, 0.0) or 0.0)
        gross = carried + unrealized_pnl(side, float(position["entry_price"]), fill.price, fill.quantity)
        total_fees = float(position.get("fees") or 0.0) + fill.fee
        exit_side = "sell" if side == "long" else "buy"

        if remaining > 0:
            self.state.update_position(pid, quantity=remaining, fees=total_fees)
            self.state.set_state(gross_key, gross)
            self.state.set_state(pending_key, reason)
            if fill.quantity > 0:
                self.state.record_trade(position_id=pid, symbol=symbol, side=exit_side, action="close",
                                        quantity=fill.quantity, price=fill.price, fee=fill.fee,
                                        reason=f"{reason} (partial)", mode=self.mode, order_id=fill.order_id)
            self._decision("WARNING", symbol, f"#{pid}: exit filled {fill.quantity} of {requested}; "
                                              f"{remaining} stays open and will be closed on the next attempt",
                           {"position_id": pid, "filled": fill.quantity, "remaining": remaining})
            updated = self.state.get_position(pid)
            self.protect_position(updated)
            return updated

        net = gross - total_fees
        self.state.mark_position_closed(pid, exit_price=fill.price, pnl=net, fees=total_fees,
                                        reason=reason, exit_order_id=fill.order_id)
        self.state.record_trade(position_id=pid, symbol=symbol, side=exit_side, action="close",
                                quantity=fill.quantity, price=fill.price, fee=fill.fee, pnl=net, reason=reason,
                                mode=self.mode, order_id=fill.order_id)
        for key in (gross_key, pending_key, f"stop_order:{pid}", f"stop_retry_after:{pid}", f"unknown_exit:{pid}"):
            self.state.delete_state(key)
        self._trade_log("CLOSE", symbol, {"position_id": pid, "side": side, "qty": fill.quantity,
                                          "price": fill.price, "pnl": round(net, 8), "fees": total_fees,
                                          "reason": reason})
        return self.state.get_position(pid)

    def performance_summary(self, starting_equity: float = 0.0) -> Dict[str, Any]:
        return compute_performance(self.state.get_closed_positions(mode=self.mode, limit=100000), starting_equity)

    def log_performance_summary(self, starting_equity: float = 0.0) -> Dict[str, Any]:
        stats = self.performance_summary(starting_equity)
        self.log.info(f"Performance summary [{self.mode}]: {format_performance(stats)}")
        self.state.log_event("INFO", "performance", format_performance(stats))
        return stats

    # ------------------------------------------------------------ logging
    def _trade_log(self, action: str, symbol: str, data: Dict[str, Any]) -> None:
        self.log.info(f"TRADE {action} {symbol}", extra={"mode": self.mode, **data})
        self.state.log_event("INFO", "trade", f"[{self.mode}] {action} {symbol}", symbol=symbol, data=data)

    def _decision(self, level: str, symbol: str, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        self.log.log(20 if level == "INFO" else 30, message, extra={"symbol": symbol, **(data or {})})
        self.state.log_event(level, "decision", message, symbol=symbol, data=data)
