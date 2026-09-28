"""Real order execution through ``ExchangeClient``.

Stops and targets are enforced by the bot on every loop (software stops).
In addition, when the ``exchange_stop_enabled`` setting is on (default) and
the exchange supports it, a stop-market order rests on the exchange at the
position's stop level, so the position stays protected while the bot is off.
The bot cancels it before any exit it starts itself, replaces it when the
trailing stop moves, and records it as the exit if it executed. Take-profit is
still bot-managed. Prefer testnet (USE_TESTNET=true) before going live.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

import time

import ccxt

from exchange_client import OrderNotPlaced
from execution.base import BaseExecutionClient, Fill, check_market_limits
from risk_manager import unrealized_pnl


# ccxt exchange ids whose derivative balance `total` already includes unrealised PnL.
BALANCE_INCLUDES_UPNL = ("binance",)

STOP_RETRY_SEC = 600  # wait before re-trying a stop order the exchange refused


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

    # Quantities in state are base units (BTC). ccxt futures/swap order amounts are
    # contracts, so convert at the exchange boundary (contract size 1 for spot).
    def normalize_quantity(self, symbol: str, quantity: float) -> float:
        size = self._contract_size(symbol)
        return self.exchange.amount_to_precision(symbol, quantity / size) * size

    def check_order_limits(self, symbol: str, quantity: float, price: float) -> Tuple[bool, str]:
        if quantity <= 0:
            return False, "quantity below exchange precision"
        limits = dict(self.exchange.market_limits(symbol))
        if limits.get("min_amount"):  # the exchange states it in contracts
            limits["min_amount"] = float(limits["min_amount"]) * self._contract_size(symbol)
        return check_market_limits(limits, quantity, price)

    def _submit_market_order(self, symbol: str, side: str, quantity: float, reference_price: float,
                             reduce_only: bool = False) -> Fill:
        params: Dict[str, Any] = {}
        if reduce_only and self.market_type != "spot":
            params["reduceOnly"] = True
        if reduce_only and self.market_type == "spot" and side == "sell":
            quantity = self._sellable_quantity(symbol, quantity)
        requested = self.normalize_quantity(symbol, quantity) or quantity
        order = self.exchange.create_market_order(symbol, side, quantity / self._contract_size(symbol), params)
        return self._fill_from_order(order, symbol, side, requested, reference_price)

    def _fill_from_order(self, order: Mapping[str, Any], symbol: str, side: str, requested: float,
                         reference_price: float) -> Fill:
        if order.get("id") and (not order.get("average") or order.get("filled") is None
                                or order.get("status") == "open"):
            try:
                fetched = self.exchange.fetch_order(order["id"], symbol)
                order = {**order, **{k: v for k, v in fetched.items() if v is not None}}
            except Exception as exc:  # fill details are best-effort; the order itself went through
                self.log.warning("Could not fetch order details", extra={"symbol": symbol, "error": str(exc)})
        price = float(order.get("average") or order.get("price") or reference_price)
        if order.get("filled") is None:
            self.log.warning("Exchange did not report the filled amount; assuming a full fill",
                             extra={"symbol": symbol, "order_id": order.get("id")})
            filled = requested
        else:
            filled = float(order["filled"]) * self._contract_size(symbol)
        fee = self._fee_in_quote(order, symbol, price, filled)
        base_fee = self._fee_in_base(order, symbol)
        if side == "buy" and self.market_type == "spot" and 0 < base_fee < filled:
            # The exchange took the fee out of the bought coins, so we hold less than
            # `filled`. Track what we actually hold, or the closing sell would ask for
            # more than the balance and fail with InsufficientFunds on every loop.
            filled -= base_fee
        return Fill(price=price, quantity=filled, fee=fee, requested=requested,
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

    def _balance_includes_unrealized(self) -> bool:
        """Binance derivatives report `total` as margin balance (wallet + unrealised
        PnL); most others (e.g. Bybit) report the wallet balance."""
        exchange_id = str(getattr(self.exchange, "exchange_id", "") or "")
        return self.market_type != "spot" and exchange_id.startswith(BALANCE_INCLUDES_UPNL)

    def get_equity(self, prices: Mapping[str, float]) -> float:
        total, _ = self._quote_balance()
        for p in self.open_positions():
            price = prices.get(p["symbol"], p["entry_price"])
            if self.market_type == "spot":
                total += p["quantity"] * price  # base asset held
            elif not self._balance_includes_unrealized():
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

    # ------------------------------------------------- exchange-side stops
    def _exchange_stops_enabled(self) -> bool:
        return bool(self.state.get_setting("exchange_stop_enabled", True))

    def _stop_key(self, position: Mapping[str, Any]) -> str:
        return f"stop_order:{position['id']}"

    def protect_position(self, position: Mapping[str, Any]) -> None:
        """Rest a stop-market order on the exchange at the position's stop level,
        so it stays protected while the bot is off. On failure the bot keeps
        enforcing the stop itself (software stop) and says so once."""
        if not position or position.get("status") != "open" or not self._exchange_stops_enabled():
            return
        if self.state.get_state(self._stop_key(position)):
            return
        if time.time() < float(self.state.get_state(f"stop_retry_after:{position['id']}", 0) or 0):
            return
        symbol = position["symbol"]
        if not self.exchange.supports_stop_orders():
            self._warn_once(f"stop_unsupported:{symbol}", symbol,
                            "Exchange stop orders are not supported here; the bot enforces stops itself "
                            "and positions are unprotected while it is off")
            return
        side = "sell" if position["side"] == "long" else "buy"
        params: Dict[str, Any] = {"reduceOnly": True} if self.market_type != "spot" else {}
        try:
            order = self.exchange.create_stop_order(symbol, side,
                                                    float(position["quantity"]) / self._contract_size(symbol),
                                                    float(position["stop_loss"]), params)
        except ccxt.NotSupported as exc:
            self._warn_once(f"stop_unsupported:{symbol}", symbol,
                            f"Exchange stop order not supported ({exc}); the bot enforces stops itself")
            return
        except ccxt.BaseError as exc:
            retry_key = f"stop_retry_after:{position['id']}"
            if time.time() >= float(self.state.get_state(retry_key, 0) or 0):
                self._decision("WARNING", symbol, f"#{position['id']}: could not place exchange stop "
                                                  f"({type(exc).__name__}: {exc}); bot-managed stop stays active, "
                                                  "retrying", {"position_id": position["id"]})
            self.state.set_state(retry_key, time.time() + STOP_RETRY_SEC)
            return
        self.state.set_state(self._stop_key(position), {"id": str(order.get("id")),
                                                        "stop": float(position["stop_loss"]),
                                                        "quantity": float(position["quantity"])})
        self._decision("INFO", symbol, f"#{position['id']}: exchange stop placed at {position['stop_loss']:.6g}",
                       {"position_id": position["id"], "order_id": order.get("id")})

    def _release_protective_stop(self, position: Mapping[str, Any]) -> Optional[Fill]:
        """Cancel the resting stop. If it already executed, return its fill so the
        caller records that close instead of sending a second order. Errors other
        than 'order not found' propagate, so the close is retried next loop rather
        than risking a double exit."""
        info = self.state.get_state(self._stop_key(position))
        if not info:
            return None
        symbol = position["symbol"]
        try:
            self.exchange.cancel_order(info["id"], symbol)
        except ccxt.OrderNotFound:
            pass  # already executed or gone: look at it below
        else:
            self.state.delete_state(self._stop_key(position))
            return None
        order = self.exchange.fetch_order(info["id"], symbol)
        self.state.delete_state(self._stop_key(position))
        return self._stop_fill(order, position)

    def _stop_fill(self, order: Mapping[str, Any], position: Mapping[str, Any]) -> Optional[Fill]:
        filled = float(order.get("filled") or 0.0) * self._contract_size(position["symbol"])
        if filled <= 0:
            return None
        price = float(order.get("average") or order.get("price") or order.get("stopPrice")
                      or position["stop_loss"])
        return Fill(price=price, quantity=filled, fee=self._fee_in_quote(order, position["symbol"], price, filled),
                    order_id=str(order.get("id")) if order.get("id") else None,
                    requested=float(position["quantity"]))

    def on_stop_moved(self, position: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        if not self.state.get_state(self._stop_key(position)):
            self.protect_position(position)
            return None
        fill = self._release_protective_stop(position)
        if fill is not None:
            return self._record_close(position, fill, "exchange_stop")
        self.protect_position(position)
        return None

    def sync_protective_stops(self) -> None:
        """Run every loop and at startup: a stop that executed on the exchange
        (e.g. while the bot was off) is recorded as a close at its fill price; a
        stop that disappeared (cancelled by hand, expired) or was never placed is
        placed again; a stop for the wrong amount or level is replaced."""
        for position in self.open_positions():
            if self.state.get_state(f"unknown_exit:{position['id']}"):
                continue  # an exit may already have happened; settle that first
            info = self.state.get_state(self._stop_key(position))
            if not info:
                self.protect_position(position)
                continue
            try:
                order = self.exchange.fetch_order(info["id"], position["symbol"])
            except ccxt.OrderNotFound:
                order = {"status": "canceled", "filled": 0}
            except ccxt.BaseError as exc:
                self.log.warning("Could not check exchange stop", extra={"position_id": position["id"],
                                                                         "error": type(exc).__name__})
                continue
            status = order.get("status")
            if status == "closed" or float(order.get("filled") or 0.0) > 0:
                if status == "open":  # partly executed and still working: settle it first
                    fill = self._release_protective_stop(position)
                else:
                    self.state.delete_state(self._stop_key(position))
                    fill = self._stop_fill(order, position)
                if fill is not None:
                    self._decision("WARNING", position["symbol"],
                                   f"#{position['id']}: exchange stop executed at {fill.price:.6g}",
                                   {"position_id": position["id"], "filled": fill.quantity})
                    self._record_close(position, fill, "exchange_stop")
                    continue
            if status in ("canceled", "cancelled", "expired", "rejected"):
                self.state.delete_state(self._stop_key(position))
                self.protect_position(position)
                continue
            if (abs(float(info.get("stop", 0)) - float(position["stop_loss"])) > 1e-12
                    or abs(float(info.get("quantity", 0)) - float(position["quantity"])) > 1e-12):
                self.on_stop_moved(position)

    def _warn_once(self, key: str, symbol: str, message: str) -> None:
        if self.state.get_state(key):
            return
        self.state.set_state(key, True)
        self._decision("WARNING", symbol, message)

    # ------------------------------------------- orders with unknown outcome
    def resolve_pending_orders(self) -> None:
        """Every loop: book an entry whose order turned out to exist (with its stop),
        or drop it when the exchange confirms it was never placed."""
        for key, plan in self.state.get_states_with_prefix("pending_entry:").items():
            symbol = key.split(":", 1)[1]
            try:
                order = self.exchange.resolve_order(symbol, plan["client_order_id"], int(plan["since_ms"]))
            except OrderNotPlaced:
                self.state.delete_state(key)
                self._decision("INFO", symbol, "Earlier entry order with unknown outcome was not placed")
                continue
            except ccxt.BaseError as exc:
                self.log.warning("Entry order still unknown", extra={"symbol": symbol, "error": type(exc).__name__})
                continue
            side = plan["side"]
            fill = self._fill_from_order(order, symbol, "buy" if side == "long" else "sell",
                                         float(plan["quantity"]), float(plan["reference_price"]))
            self.state.delete_state(key)
            self._decision("WARNING", symbol, f"Earlier entry order was filled ({fill.quantity}); booking it")
            self._book_entry(symbol, side, fill, float(plan["reference_price"]), float(plan["stop_loss"]),
                             float(plan["take_profit"] or 0.0), float(plan["atr"] or 0.0), plan.get("reason", "signal"))

    def _resolve_unknown_exit(self, position: Mapping[str, Any]) -> Optional[Fill]:
        info = self.state.get_state(f"unknown_exit:{position['id']}")
        if not info:
            return None
        symbol = position["symbol"]
        try:
            order = self.exchange.resolve_order(symbol, info["client_order_id"], int(info["since_ms"]))
        except OrderNotPlaced:
            self.state.delete_state(f"unknown_exit:{position['id']}")
            return None  # safe to send a new exit order
        # AmbiguousOrderError / network errors propagate: no new order while unknown
        self.state.delete_state(f"unknown_exit:{position['id']}")
        side = "sell" if position["side"] == "long" else "buy"
        return self._fill_from_order(order, symbol, side, float(info["requested"]), float(info["reference_price"]))
