"""Validation for settings edited through the API.

``StateManager.set_setting`` already coerces a value to the stored type; this
module adds the range and cross-field checks a remote client must not be
able to bypass (e.g. a negative period or ``macd_fast >= macd_slow``).
"""

from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Optional, Tuple

from config import DEFAULT_SETTINGS
from state_manager import coerce_to_type

# key -> (min, max, min_inclusive). None = unbounded on that side.
_Bounds = Tuple[Optional[float], Optional[float], bool]

_PERIODS = ("ema_trend_period", "rsi_period", "macd_fast", "macd_slow", "macd_signal", "macd_cross_lookback",
            "volume_ma_period", "atr_period", "donchian_period")

BOUNDS: Dict[str, _Bounds] = {
    **{k: (1, 1000, True) for k in _PERIODS},
    "rsi_long_min": (0, 100, True),
    "rsi_long_max": (0, 100, True),
    "rsi_short_min": (0, 100, True),
    "rsi_short_max": (0, 100, True),
    "volume_factor": (0, None, True),
    "breakout_atr_buffer": (0, None, True),
    "min_confirmations": (1, 3, True),
    "risk_per_trade_pct": (0, 100, False),
    "atr_sl_multiplier": (0, None, False),
    "risk_reward_ratio": (0, None, False),
    "trailing_atr_multiplier": (0, None, False),
    "trailing_activation_r": (0, None, True),
    "daily_loss_limit_pct": (0, 100, True),
    "max_open_positions": (0, 100, True),
    "max_symbol_exposure_pct": (0, 100, False),
}

# (smaller key, larger key): the first must stay strictly below the second.
ORDERED_PAIRS = (
    ("macd_fast", "macd_slow"),
    ("rsi_long_min", "rsi_long_max"),
    ("rsi_short_min", "rsi_short_max"),
)


class UnknownSettingError(KeyError):
    pass


def validate_setting(key: str, raw_value: Any, current: Mapping[str, Any]) -> Any:
    """Return the coerced value for ``key`` or raise ``ValueError`` /
    ``UnknownSettingError``. ``current`` holds all current settings."""
    if key not in DEFAULT_SETTINGS:
        raise UnknownSettingError(key)
    target = type(DEFAULT_SETTINGS[key][0])
    if target is bool and not isinstance(raw_value, (bool, str)):
        raise ValueError("expected true/false")
    if target in (int, float) and isinstance(raw_value, str) and raw_value.strip() == "":
        raise ValueError("value is empty")
    value = coerce_to_type(raw_value, target)

    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("value must be a finite number")
    bounds = BOUNDS.get(key)
    if bounds is not None:
        low, high, low_inclusive = bounds
        if low is not None and (value < low if low_inclusive else value <= low):
            raise ValueError(f"must be {'>=' if low_inclusive else '>'} {low}")
        if high is not None and value > high:
            raise ValueError(f"must be <= {high}")

    merged = dict(current)
    merged[key] = value
    for small, large in ORDERED_PAIRS:
        if key in (small, large) and small in merged and large in merged and not merged[small] < merged[large]:
            raise ValueError(f"{small} must be less than {large} ({merged[small]} >= {merged[large]})")
    return value
