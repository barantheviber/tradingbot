"""Dashboard logic that does not need Streamlit (kept here so it can be tested)."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Tuple

from api.validation import UnknownSettingError, validate_setting

LOOPBACK_ADDRESSES = {"127.0.0.1", "localhost", "::1"}


def dashboard_is_local_only(address: Any) -> bool:
    """True when Streamlit listens only on this computer."""
    return str(address or "").strip().lower() in LOOPBACK_ADDRESSES


def apply_setting_changes(state, current: Mapping[str, Any],
                          new_values: Mapping[str, Any]) -> Tuple[List[str], List[str]]:
    """Save changed settings through the same range / cross-field validation as
    the apps' API. Returns (changed keys, error messages)."""
    changed: List[str] = []
    errors: List[str] = []
    merged: Dict[str, Any] = dict(current)
    for key, value in new_values.items():
        if key in current and value == current[key]:
            continue
        try:
            value = validate_setting(key, value, merged)
        except UnknownSettingError:
            errors.append(f"{key}: bilinmeyen ayar")
            continue
        except ValueError as exc:
            errors.append(f"{key}: {exc}")
            continue
        state.set_setting(key, value)
        merged[key] = value
        changed.append(key)
    return changed, errors
