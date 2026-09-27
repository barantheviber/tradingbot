"""
Position sizing, SL/TP, trailing stop and daily-drawdown risk controls.

This module is intentionally free of any exchange/database calls: it takes
plain numbers in and returns plain numbers/decisions out, so it is trivial
to unit test (see tests/test_risk_manager.py) and to reuse from backtest.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from strategy import Side


@dataclass(frozen=True)
class RiskParams:
    risk_per_trade_pct: float = 1.0
    risk_reward_ratio: float = 2.0
    atr_sl_multiplier: float = 1.5
    trailing_atr_multiplier: float = 1.5
    max_daily_drawdown_pct: float = 5.0
    max_concurrent_positions: int = 3
    max_exposure_per_symbol_pct: float = 20.0


@dataclass(frozen=True)
class PositionSizeResult:
    quantity: float
    stop_loss: float
    take_profit: float
    risk_amount: float
    stop_distance: float


class RiskLimitExceeded(Exception):
    """Raised when an entry would violate a hard risk limit."""


def compute_position_size(
    side: Side,
    entry_price: float,
    atr_value: float,
    account_equity: float,
    params: RiskParams,
) -> PositionSizeResult:
    """
    Position size = risk_amount / stop_distance, where:
      risk_amount   = account_equity * risk_per_trade_pct / 100
      stop_distance = atr_value * atr_sl_multiplier

    Take-profit is placed at risk_reward_ratio * stop_distance beyond entry,
    in the trade's favorable direction.
    """
    if atr_value <= 0:
        raise ValueError("atr_value must be > 0 to size a position")
    if entry_price <= 0:
        raise ValueError("entry_price must be > 0")

    stop_distance = atr_value * params.atr_sl_multiplier
    if stop_distance <= 0:
        raise ValueError("Computed stop_distance must be > 0")

    risk_amount = account_equity * (params.risk_per_trade_pct / 100.0)
    quantity = risk_amount / stop_distance

    if side == Side.LONG:
        stop_loss = entry_price - stop_distance
        take_profit = entry_price + stop_distance * params.risk_reward_ratio
    else:
        stop_loss = entry_price + stop_distance
        take_profit = entry_price - stop_distance * params.risk_reward_ratio

    return PositionSizeResult(
        quantity=quantity,
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_amount=risk_amount,
        stop_distance=stop_distance,
    )


def update_trailing_stop(
    side: Side,
    current_stop: float,
    current_price: float,
    atr_value: float,
    params: RiskParams,
) -> float:
    """
    Moves the stop only in the direction that locks in more profit; never
    loosens it. Returns the (possibly unchanged) new stop level.
    """
    trail_distance = atr_value * params.trailing_atr_multiplier
    if side == Side.LONG:
        candidate = current_price - trail_distance
        return max(current_stop, candidate)
    else:
        candidate = current_price + trail_distance
        return min(current_stop, candidate)


def check_exposure_limit(
    symbol_notional: float,
    trade_notional: float,
    account_equity: float,
    params: RiskParams,
) -> None:
    """Raises RiskLimitExceeded if adding trade_notional would breach the
    per-symbol exposure cap."""
    if account_equity <= 0:
        raise RiskLimitExceeded("Account equity must be > 0")
    projected_pct = (symbol_notional + trade_notional) / account_equity * 100.0
    if projected_pct > params.max_exposure_per_symbol_pct:
        raise RiskLimitExceeded(
            f"Per-symbol exposure {projected_pct:.2f}% would exceed limit "
            f"{params.max_exposure_per_symbol_pct:.2f}%"
        )


def check_max_positions(open_position_count: int, params: RiskParams) -> None:
    if open_position_count >= params.max_concurrent_positions:
        raise RiskLimitExceeded(
            f"Max concurrent positions ({params.max_concurrent_positions}) reached"
        )


@dataclass
class DailyPnLTracker:
    """
    Tracks realized PnL since the last UTC-midnight reset and decides
    whether new position entries are currently allowed.
    """
    starting_equity: float
    realized_pnl: float = 0.0
    last_reset_date: Optional[str] = None  # ISO date string, UTC

    def _today_utc(self) -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def maybe_reset(self) -> bool:
        today = self._today_utc()
        if self.last_reset_date != today:
            self.realized_pnl = 0.0
            self.last_reset_date = today
            return True
        return False

    def record_realized_pnl(self, pnl: float) -> None:
        self.maybe_reset()
        self.realized_pnl += pnl

    def drawdown_pct(self) -> float:
        if self.starting_equity <= 0:
            return 0.0
        return max(0.0, -self.realized_pnl) / self.starting_equity * 100.0

    def trading_halted(self, params: RiskParams) -> bool:
        self.maybe_reset()
        return self.drawdown_pct() >= params.max_daily_drawdown_pct
