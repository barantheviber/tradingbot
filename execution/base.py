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

from logging_setup import get_logger
from performance import compute_performance, format_performance
from risk_manager import unrealized_pnl


@dataclass
class Fill:
    price: float
    quantity: float
    fee: float
    order_id: Optional[str] = None


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

    # ------------------------------------------------------------- shared
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

        fill = self._submit_market_order(symbol, "buy" if side == "long" else "sell", qty, reference_price)
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
        return self.state.get_position(position_id)

    def close_position(self, position: Mapping[str, Any], reference_price: float,
                       reason: str) -> Optional[Dict[str, Any]]:
        side = position["side"]
        fill = self._submit_market_order(position["symbol"], "sell" if side == "long" else "buy",
                                         float(position["quantity"]), reference_price, reduce_only=True)
        gross = unrealized_pnl(side, float(position["entry_price"]), fill.price, fill.quantity)
        total_fees = float(position.get("fees") or 0.0) + fill.fee
        net = gross - total_fees
        self.state.mark_position_closed(position["id"], exit_price=fill.price, pnl=net, fees=total_fees,
                                        reason=reason, exit_order_id=fill.order_id)
        self.state.record_trade(position_id=position["id"], symbol=position["symbol"],
                                side="sell" if side == "long" else "buy", action="close", quantity=fill.quantity,
                                price=fill.price, fee=fill.fee, pnl=net, reason=reason, mode=self.mode,
                                order_id=fill.order_id)
        self._trade_log("CLOSE", position["symbol"], {"position_id": position["id"], "side": side,
                                                      "qty": fill.quantity, "price": fill.price, "pnl": round(net, 8),
                                                      "fees": total_fees, "reason": reason})
        return self.state.get_position(position["id"])

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
