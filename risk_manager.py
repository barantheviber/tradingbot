"""Risk management: sizing, SL/TP, trailing stop, daily loss limit, exposure.

The module-level functions are pure (easy to unit test and reused by the
backtest). ``RiskManager`` reads the current parameters from a settings
provider (normally ``StateManager.get_all_settings``) on every decision, so
edits made from the dashboard take effect on the next candle.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Any, Callable, Iterable, Mapping, Optional, Tuple

from logging_setup import get_logger

log = get_logger("risk")


@dataclass
class RiskParams:
    risk_per_trade_pct: float = 1.0
    atr_sl_multiplier: float = 1.5
    risk_reward_ratio: float = 2.0
    trailing_enabled: bool = True
    trailing_atr_multiplier: float = 2.0
    trailing_activation_r: float = 1.0
    daily_loss_limit_pct: float = 5.0
    max_open_positions: int = 3
    max_symbol_exposure_pct: float = 25.0

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any]) -> "RiskParams":
        kwargs = {}
        for f in fields(cls):
            if f.name in settings and settings[f.name] is not None:
                kwargs[f.name] = type(getattr(cls, f.name))(settings[f.name])
        return cls(**kwargs)


@dataclass
class TradePlan:
    allowed: bool
    reason: str
    side: str = ""
    entry_price: float = 0.0
    quantity: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    risk_amount: float = 0.0

    @property
    def notional(self) -> float:
        return self.quantity * self.entry_price


# ------------------------------------------------------------ pure helpers
def calculate_sl_tp(entry: float, atr: float, side: str, atr_multiplier: float,
                    risk_reward: float) -> Tuple[float, float]:
    """Stop = entry -/+ ATR*mult; target = entry +/- stop distance * R:R."""
    if entry <= 0 or atr <= 0 or atr_multiplier <= 0 or risk_reward <= 0:
        raise ValueError("entry, atr, atr_multiplier and risk_reward must be positive")
    distance = atr * atr_multiplier
    if side == "long":
        stop = entry - distance
        if stop <= 0:
            raise ValueError("stop distance larger than price")
        return stop, entry + distance * risk_reward
    if side == "short":
        return entry + distance, entry - distance * risk_reward
    raise ValueError(f"unknown side {side!r}")


def calculate_position_size(
    equity: float,
    entry: float,
    stop: float,
    risk_pct: float,
    max_notional: Optional[float] = None,
    qty_step: Optional[float] = None,
) -> float:
    """Quantity such that hitting the stop loses ``risk_pct`` % of equity.

    qty = (equity * risk_pct / 100) / |entry - stop|, then capped so that
    qty * entry <= max_notional, then rounded *down* to ``qty_step``.
    """
    if equity <= 0 or entry <= 0 or risk_pct <= 0:
        return 0.0
    stop_distance = abs(entry - stop)
    if stop_distance <= 0:
        return 0.0
    qty = (equity * risk_pct / 100.0) / stop_distance
    if max_notional is not None:
        qty = min(qty, max(0.0, max_notional) / entry)
    if qty_step and qty_step > 0:
        qty = math.floor(qty / qty_step + 1e-9) * qty_step
    return max(0.0, qty)


def update_trailing_stop(
    side: str,
    current_stop: float,
    entry: float,
    initial_stop: float,
    extreme_price: float,
    atr: float,
    atr_multiplier: float,
    activation_r: float = 0.0,
) -> float:
    """Return the new stop. It can only move in the profit-protecting direction.

    ``extreme_price`` is the highest high (long) / lowest low (short) since
    entry. Trailing only starts once price has moved ``activation_r`` times
    the initial risk in our favour.
    """
    if atr <= 0 or atr_multiplier <= 0:
        return current_stop
    initial_risk = abs(entry - initial_stop)
    if side == "long":
        if extreme_price - entry < activation_r * initial_risk:
            return current_stop
        return max(current_stop, extreme_price - atr * atr_multiplier)
    if side == "short":
        if entry - extreme_price < activation_r * initial_risk:
            return current_stop
        return min(current_stop, extreme_price + atr * atr_multiplier)
    raise ValueError(f"unknown side {side!r}")


def check_exit(side: str, price: float, stop_loss: float, take_profit: float) -> Optional[str]:
    """'stop_loss' / 'take_profit' if the price crossed a level, else None."""
    if side == "long":
        if price <= stop_loss:
            return "stop_loss"
        if take_profit and price >= take_profit:
            return "take_profit"
    elif side == "short":
        if price >= stop_loss:
            return "stop_loss"
        if take_profit and price <= take_profit:
            return "take_profit"
    return None


def unrealized_pnl(side: str, entry: float, price: float, qty: float) -> float:
    return (price - entry) * qty if side == "long" else (entry - price) * qty


def daily_loss_pct(start_equity: float, current_equity: float) -> float:
    """Loss since start of day as a positive percentage (0 when in profit)."""
    if start_equity <= 0:
        return 0.0
    return max(0.0, (start_equity - current_equity) / start_equity * 100.0)


def is_daily_loss_limit_hit(start_equity: float, current_equity: float, limit_pct: float) -> bool:
    return limit_pct > 0 and daily_loss_pct(start_equity, current_equity) >= limit_pct


# ------------------------------------------------------------ RiskManager
class RiskManager:
    def __init__(self, settings_provider: Callable[[], Mapping[str, Any]]):
        self._settings_provider = settings_provider

    @property
    def params(self) -> RiskParams:
        return RiskParams.from_settings(self._settings_provider())

    def plan_trade(
        self,
        symbol: str,
        side: str,
        entry: float,
        atr: float,
        equity: float,
        open_positions: Iterable[Mapping[str, Any]],
        day_start_equity: Optional[float] = None,
        available_cash: Optional[float] = None,
        qty_step: Optional[float] = None,
    ) -> TradePlan:
        """Run every pre-trade check and size the position. Never raises."""
        p = self.params
        positions = list(open_positions)

        if day_start_equity and is_daily_loss_limit_hit(day_start_equity, equity, p.daily_loss_limit_pct):
            return TradePlan(False, f"daily loss limit hit ({daily_loss_pct(day_start_equity, equity):.2f}% "
                                    f">= {p.daily_loss_limit_pct}%)")
        if len(positions) >= p.max_open_positions:
            return TradePlan(False, f"max open positions reached ({len(positions)}/{p.max_open_positions})")
        if atr <= 0 or entry <= 0:
            return TradePlan(False, "invalid ATR/entry")

        try:
            stop, target = calculate_sl_tp(entry, atr, side, p.atr_sl_multiplier, p.risk_reward_ratio)
        except ValueError as exc:
            return TradePlan(False, f"cannot compute SL/TP: {exc}")

        existing = sum(float(pos["quantity"]) * float(pos["entry_price"])
                       for pos in positions if pos["symbol"] == symbol)
        max_notional = equity * p.max_symbol_exposure_pct / 100.0 - existing
        if available_cash is not None:
            max_notional = min(max_notional, available_cash)
        if max_notional <= 0:
            return TradePlan(False, f"symbol exposure cap reached for {symbol}")

        qty = calculate_position_size(equity, entry, stop, p.risk_per_trade_pct, max_notional, qty_step)
        if qty <= 0:
            return TradePlan(False, "position size rounds to zero")
        return TradePlan(
            allowed=True, reason="ok", side=side, entry_price=entry, quantity=qty, stop_loss=stop,
            take_profit=target, risk_amount=qty * abs(entry - stop),
        )

    def trailing_stop_for(self, position: Mapping[str, Any], atr: float) -> float:
        p = self.params
        current = float(position["stop_loss"])
        if not p.trailing_enabled:
            return current
        side = position["side"]
        extreme = float(position["highest_price"] if side == "long" else position["lowest_price"])
        return update_trailing_stop(side, current, float(position["entry_price"]), float(position["initial_stop"]),
                                    extreme, atr, p.trailing_atr_multiplier, p.trailing_activation_r)
