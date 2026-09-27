"""Read models the API serves, built from the bot's SQLite state.

Everything here reads what the running bot wrote (``heartbeat``,
``bot_status``, positions, trades, event log). Nothing here talks to the
exchange with API keys or places an order; closing a position only adds a
row to the bot's command queue.
"""

from __future__ import annotations

import json
import math
import time
from typing import Any, Dict, List, Optional

from config import Config
from performance import compute_performance
from risk_manager import daily_loss_pct, unrealized_pnl
from state_manager import StateManager

POSITION_KEYS = ("id", "symbol", "side", "quantity", "entry_price", "stop_loss", "take_profit", "initial_stop",
                 "highest_price", "lowest_price", "atr_at_entry", "fees", "mode", "opened_at")
TRADE_KEYS = ("id", "symbol", "side", "quantity", "entry_price", "exit_price", "pnl", "fees", "exit_reason",
              "mode", "opened_at", "closed_at")


def _finite(value: Optional[float]) -> Optional[float]:
    """JSON has no inf/nan; report them as null."""
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def heartbeat_stale_after(config: Config) -> float:
    """Same threshold the Streamlit dashboard uses."""
    return float(max(120, config.poll_interval_sec * 4))


class BotReadModel:
    def __init__(self, config: Config, state: StateManager):
        self.config = config
        self.state = state

    @property
    def mode(self) -> str:
        return self.config.mode

    def _prices(self) -> Dict[str, float]:
        return (self.state.get_state("heartbeat") or {}).get("prices", {}) or {}

    # -------------------------------------------------------------- status
    def status(self) -> Dict[str, Any]:
        hb = self.state.get_state("heartbeat") or {}
        bot_status = (self.state.get_state("bot_status") or {}).get("status", "unknown")
        hb_ts = hb.get("ts")
        hb_age = (time.time() - float(hb_ts)) if hb_ts else None
        running = bot_status == "running" and hb_age is not None and hb_age <= heartbeat_stale_after(self.config)

        equity = hb.get("equity")
        day_start = self.state.get_day_start_equity(self.mode)
        limit_pct = float(self.state.get_setting("daily_loss_limit_pct", 5.0))
        today_pnl = loss_pct = None
        halted = False
        if equity is not None and day_start:
            today_pnl = float(equity) - day_start
            loss_pct = daily_loss_pct(day_start, float(equity))
            halted = limit_pct > 0 and loss_pct >= limit_pct

        open_positions = self.state.get_open_positions(mode=self.mode)
        return {
            "mode": self.mode,
            "exchange": self.config.exchange_id,
            "market_type": self.config.market_type,
            "testnet": self.config.use_testnet,
            "symbols": list(self.config.symbols),
            "timeframe": self.config.timeframe,
            "bot_running": running,
            "bot_state": bot_status,
            "heartbeat_age_sec": _finite(hb_age),
            "equity": _finite(equity),
            "day_start_equity": _finite(day_start),
            "today_pnl": _finite(today_pnl),
            "daily_loss_pct": _finite(loss_pct),
            "daily_loss_limit_pct": limit_pct,
            "entries_halted_by_daily_limit": halted,
            "trading_enabled": bool(self.state.get_setting("trading_enabled", True)),
            "open_positions": len(open_positions),
            "max_open_positions": self.state.get_setting("max_open_positions"),
            "pending_commands": len(self.state.get_pending_commands()),
            "server_time": time.time(),
        }

    # ----------------------------------------------------------- positions
    def positions(self) -> List[Dict[str, Any]]:
        prices = self._prices()
        pending_closes = self._pending_close_ids()
        out = []
        for p in self.state.get_open_positions(mode=self.mode):
            price = prices.get(p["symbol"])
            row = {k: p.get(k) for k in POSITION_KEYS}
            row["current_price"] = _finite(price)
            row["unrealized_pnl"] = (
                _finite(unrealized_pnl(p["side"], p["entry_price"], float(price), p["quantity"]) - (p["fees"] or 0))
                if price is not None else None
            )
            # the bot moves stop_loss when trailing; initial_stop keeps the original
            row["trailing_stop"] = p["stop_loss"] if p["stop_loss"] != p["initial_stop"] else None
            row["trailing_active"] = p["stop_loss"] != p["initial_stop"]
            row["close_pending"] = p["id"] in pending_closes
            out.append(row)
        return out

    def _pending_close_ids(self) -> set:
        ids = set()
        for cmd in self.state.get_pending_commands():
            if cmd["command"] == "close_position":
                try:
                    ids.add(int(cmd["payload"].get("position_id")))
                except (TypeError, ValueError):
                    continue
            elif cmd["command"] == "close_all":
                ids.update(p["id"] for p in self.state.get_open_positions(mode=self.mode))
        return ids

    def request_close(self, position_id: int, source: str = "api") -> Dict[str, Any]:
        """Queue a close for the running bot. Raises LookupError if the
        position is not open in the bot's current mode."""
        pos = self.state.get_position(position_id)
        if not pos or pos["status"] != "open" or pos["mode"] != self.mode:
            raise LookupError(f"position {position_id} is not open")
        for cmd in self.state.get_pending_commands():
            if cmd["command"] == "close_position" and cmd["payload"].get("position_id") == position_id:
                return {"command_id": cmd["id"], "status": "pending", "already_queued": True}
        command_id = self.state.enqueue_command("close_position", {"position_id": position_id, "source": source})
        self.state.log_event("INFO", "command", f"Close #{position_id} queued from {source}", symbol=pos["symbol"])
        return {"command_id": command_id, "status": "pending", "already_queued": False}

    def command(self, command_id: int) -> Optional[Dict[str, Any]]:
        return self.state.get_command(command_id)

    # -------------------------------------------------------- trades / pnl
    def trades(self, limit: int) -> List[Dict[str, Any]]:
        return [{k: p.get(k) for k in TRADE_KEYS} for p in self.state.get_closed_positions(mode=self.mode, limit=limit)]

    def pnl(self) -> Dict[str, Any]:
        closed = self.state.get_closed_positions(mode=self.mode, limit=1_000_000)
        starting = self.config.paper_starting_balance if self.mode == "paper" else 0.0
        stats = compute_performance(closed, starting)
        unreal = [p["unrealized_pnl"] for p in self.positions() if p["unrealized_pnl"] is not None]
        out = {k: (_finite(v) if isinstance(v, float) else v) for k, v in stats.items()}
        out["profit_factor_infinite"] = stats["profit_factor"] == float("inf")
        out["realized_pnl"] = _finite(self.state.realized_pnl(self.mode))
        out["unrealized_pnl"] = _finite(sum(unreal))
        out["starting_equity"] = starting
        return out

    # ------------------------------------------------------------ settings
    def settings(self) -> List[Dict[str, Any]]:
        rows = self.state.get_settings_with_meta()
        for r in rows:
            r["type"] = {bool: "bool", int: "int", float: "float"}.get(type(r["value"]), "str")
        return rows

    # ---------------------------------------------------------------- logs
    def logs(self, limit: int, after_id: int = 0, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Newest first, like ``StateManager.get_events``."""
        rows = self.state.get_events(limit=limit, after_id=after_id, category=category)
        for r in rows:
            try:
                r["data"] = json.loads(r["data"]) if r["data"] else None
            except ValueError:
                pass
        return rows
