"""Main trading loop.

Per loop (every POLL_INTERVAL_SEC):
1. For each symbol fetch the last price and enforce stop-loss / take-profit
   on open positions.
2. Fetch OHLCV, drop the still-forming candle, and act only when a *new*
   closed candle appeared (the last processed candle is persisted, so a
   restart never re-trades the same candle):
   update trailing stops, apply exit signals, then evaluate entries through
   the risk manager.
3. Write a heartbeat for the dashboard.

Between loops the engine sleeps in 1 second steps, processing dashboard
commands (manual close) and reacting to SIGINT/SIGTERM within ~1 second.
"""

from __future__ import annotations

import signal
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Mapping, Optional

import ccxt

from config import Config
from execution.base import BaseExecutionClient
from exchange_client import ExchangeClient
from logging_setup import get_logger
from risk_manager import RiskManager, check_exit
from state_manager import StateManager, utc_today
from strategy import StrategyParams, compute_indicators, signal_from_row

log = get_logger("engine")


def _iso_to_ms(iso: str) -> int:
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


class BotEngine:
    def __init__(
        self,
        config: Config,
        state: StateManager,
        exchange: ExchangeClient,
        executor: BaseExecutionClient,
        risk_manager: Optional[RiskManager] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        self.config = config
        self.state = state
        self.exchange = exchange
        self.executor = executor
        self.risk = risk_manager or RiskManager(state.get_all_settings)
        self._sleep = sleep_fn
        self._stop = threading.Event()
        self._last_prices: Dict[str, float] = {}
        self._once = False

    # --------------------------------------------------------------- control
    def install_signal_handlers(self) -> None:
        def handler(signum, _frame):
            self.request_stop(f"signal {signal.Signals(signum).name}")

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):  # not in main thread / unsupported platform
                log.warning("Could not install handler", extra={"signal": str(sig)})

    def request_stop(self, reason: str = "requested") -> None:
        if not self._stop.is_set():
            log.info("Shutdown requested", extra={"reason": reason})
            self._stop.set()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    # ------------------------------------------------------------------- run
    def startup(self) -> None:
        log.info("Starting bot", extra={"mode": self.executor.mode, "exchange": self.config.exchange_id,
                                        "symbols": self.config.symbols, "timeframe": self.config.timeframe})
        self.state.log_event("INFO", "lifecycle", f"Bot starting in {self.executor.mode.upper()} mode",
                             data={"symbols": self.config.symbols, "timeframe": self.config.timeframe})
        self.executor.restore_open_positions()  # from SQLite; works even if the exchange is down
        while True:
            try:
                self.exchange.load_markets()
                break
            except ccxt.NetworkError as exc:
                if self._once or self.stopping:
                    raise
                log.error("Exchange unreachable at startup; retrying in 30s", extra={"error": type(exc).__name__})
                self.state.log_event("ERROR", "error", f"Exchange unreachable at startup: {type(exc).__name__}")
                self._interruptible_sleep(30)
                if self.stopping:
                    raise
        self._sync_exchange_stops()  # a stop that filled while the bot was off is recorded now
        self.state.set_state("bot_status", {"status": "running", "mode": self.executor.mode,
                                            "pid_started": time.time()})

    def run(self, once: bool = False) -> None:
        self._once = once
        try:
            self.startup()
            while not self.stopping:
                self._safe_tick()
                if once:
                    break
                self._interruptible_sleep(self.config.poll_interval_sec)
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self.state.set_state("bot_status", {"status": "stopped", "mode": self.executor.mode,
                                            "stopped_at": time.time()})
        try:
            self.executor.log_performance_summary(self._starting_equity_hint())
        except Exception:  # pragma: no cover - never block shutdown
            log.exception("Could not compute performance summary")
        self.state.log_event("INFO", "lifecycle", "Bot stopped")
        log.info("Bot stopped cleanly")

    def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep in 1s steps so signals and dashboard commands are handled quickly."""
        deadline = time.monotonic() + seconds
        while not self.stopping and time.monotonic() < deadline:
            self._process_commands()
            self._sleep(min(1.0, max(0.0, deadline - time.monotonic())))

    def _safe_tick(self) -> None:
        try:
            self.tick()
        except (ccxt.AuthenticationError, ccxt.PermissionDenied) as exc:
            log.critical("Authentication failed - stopping bot", extra={"error": type(exc).__name__})
            self.state.log_event("CRITICAL", "error", f"Authentication failed: {type(exc).__name__}")
            self.request_stop("authentication error")
        except Exception as exc:
            log.exception("Tick failed")
            self.state.log_event("ERROR", "error", f"Tick failed: {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------ tick
    def tick(self) -> None:
        settings = self.state.get_all_settings()
        params = StrategyParams.from_settings(settings)
        self._sync_exchange_stops()

        # Positions whose symbol was removed from SYMBOLS (e.g. .env edited while a
        # position was open) still get their stop-loss / take-profit enforced.
        watched = list(self.config.symbols)
        watched += sorted({p["symbol"] for p in self.executor.open_positions()} - set(watched))
        for symbol in watched:
            try:
                self._last_prices[symbol] = self.exchange.fetch_last_price(symbol)
            except ccxt.BaseError as exc:
                log.warning("Price fetch failed", extra={"symbol": symbol, "error": type(exc).__name__})
                continue
            self._enforce_stops(symbol, self._last_prices[symbol])

        self._snapshot_day_start_equity()
        self._check_safety_halt(settings)

        for symbol in self.config.symbols:
            if self.stopping:
                return
            if symbol not in self._last_prices:
                continue
            try:
                self._process_symbol(symbol, params, settings)
            except (ccxt.AuthenticationError, ccxt.PermissionDenied):
                raise
            except Exception as exc:
                log.exception("Symbol processing failed", extra={"symbol": symbol})
                self.state.log_event("ERROR", "error", f"{symbol}: {type(exc).__name__}: {exc}", symbol=symbol)

        equity = self.executor.get_equity(self._last_prices)
        self.state.set_state("heartbeat", {"ts": time.time(), "equity": equity, "prices": self._last_prices,
                                           "mode": self.executor.mode})

    def _check_safety_halt(self, settings: Dict[str, Any]) -> None:
        """Stop new entries after a deep drawdown or a long losing streak.

        The halt is the live setting ``safety_halt_active``, so it survives
        restarts and shows in the apps; open positions keep their stops and
        exits. It clears only when the user sets the setting back to false,
        which also restarts peak-equity and losing-streak tracking.
        ``settings`` (this tick's snapshot) is updated in place.
        """
        mode = self.executor.mode
        halt_key = f"safety_halt:{mode}"
        active = bool(settings.get("safety_halt_active", False))
        try:
            equity = float(self.executor.get_equity(self._last_prices))
        except ccxt.BaseError as exc:
            log.warning("Equity unavailable for safety check", extra={"error": type(exc).__name__})
            return

        if not active and self.state.get_state(halt_key) is not None:
            self.state.reset_safety_tracking(mode, equity)
            log.info("Safety halt cleared by user; peak equity and losing streak reset", extra={"equity": equity})
            self.state.log_event("INFO", "risk", "Güvenlik durdurması kaldırıldı; zirve özsermaye ve kayıp serisi "
                                                 "sıfırlandı", data={"equity": equity})

        peak_key = f"safety_peak_equity:{mode}"
        peak = self.state.get_state(peak_key)
        if peak is None or equity > float(peak):
            peak = equity
            self.state.set_state(peak_key, peak)
        if active:
            return

        peak = float(peak)
        drawdown = (peak - equity) / peak * 100.0 if peak > 0 else 0.0
        streak = self.state.losing_streak(mode)
        dd_limit = float(settings.get("max_drawdown_halt_pct", 0) or 0)
        streak_limit = int(settings.get("max_losing_streak_halt", 0) or 0)
        reason = None
        if dd_limit > 0 and drawdown >= dd_limit:
            reason = f"drawdown {drawdown:.2f}% from peak {peak:.2f} >= {dd_limit:g}%"
        elif streak_limit > 0 and streak >= streak_limit:
            reason = f"{streak} losing trades in a row >= {streak_limit}"
        if reason is None:
            return

        self.state.set_setting("safety_halt_active", True)
        settings["safety_halt_active"] = True
        self.state.set_state(halt_key, {"reason": reason, "at": time.time(), "equity": equity, "peak": peak,
                                        "drawdown_pct": round(drawdown, 4), "losing_streak": streak})
        log.warning("Safety halt: new entries stopped until the user clears it", extra={"reason": reason})
        self.state.log_event("WARNING", "risk", f"Güvenlik durdurması: yeni pozisyon açılmıyor ({reason}). Açık "
                                                "pozisyonlar stop/hedefleriyle yönetilmeye devam ediyor. Kontrol "
                                                "ettikten sonra safety_halt_active ayarını false yapın.",
                             data={"reason": reason, "drawdown_pct": round(drawdown, 4), "losing_streak": streak})

    def _snapshot_day_start_equity(self) -> None:
        """Record today's start equity on the first tick of the UTC day.

        Doing this every tick (not only when an entry signal appears) makes the
        daily loss limit measure from the start of the day, so losses taken
        before the day's first signal are counted too.
        """
        mode = self.executor.mode
        if self.state.get_day_start_equity(mode) is not None:
            return
        try:
            equity = self.executor.get_equity(self._last_prices)
        except ccxt.BaseError as exc:
            log.warning("Equity unavailable for day start snapshot", extra={"error": type(exc).__name__})
            return
        self.state.get_or_create_day_start_equity(mode, equity)
        self.state.prune_events()

    def _sync_exchange_stops(self) -> None:
        try:
            self.executor.sync_protective_stops()
        except (ccxt.AuthenticationError, ccxt.PermissionDenied):
            raise
        except Exception as exc:  # never block the software stops below
            log.warning("Exchange stop sync failed", extra={"error": type(exc).__name__})

    def _enforce_stops(self, symbol: str, price: float) -> None:
        for pos in self.executor.open_positions():
            if pos["symbol"] != symbol:
                continue
            # an exit whose order filled only partly is finished first
            reason = self.executor.pending_close_reason(pos)
            reason = reason or check_exit(pos["side"], price, pos["stop_loss"], pos["take_profit"])
            if reason:
                log.info("Exit level hit", extra={"symbol": symbol, "position_id": pos["id"], "reason": reason,
                                                  "price": price, "stop": pos["stop_loss"],
                                                  "take_profit": pos["take_profit"]})
                self._close(pos, price, reason)

    def _process_symbol(self, symbol: str, params: StrategyParams, settings: Mapping[str, Any]) -> None:
        limit = max(self.config.ohlcv_limit, params.warmup + 50)
        df = self.exchange.fetch_closed_ohlcv(symbol, self.config.timeframe, limit)
        if len(df) < params.warmup:
            log.warning("Not enough closed candles", extra={"symbol": symbol, "have": len(df),
                                                            "need": params.warmup})
            return

        state_key = f"last_candle:{symbol}:{self.config.timeframe}"
        last_processed = int(self.state.get_state(state_key, 0) or 0)
        last_ts = int(df["timestamp"].iloc[-1])
        if last_ts <= last_processed:
            return  # no new closed candle yet

        ind = compute_indicators(df, params)
        sig = signal_from_row(ind.iloc[-1])
        candle_time = datetime.fromtimestamp(last_ts / 1000, tz=timezone.utc).isoformat()
        log.info("Closed candle evaluated", extra={"symbol": symbol, "candle": candle_time, "action": sig.action,
                                                   "long_layers": sig.reasons["long"],
                                                   "short_layers": sig.reasons["short"],
                                                   "rsi": sig.reasons["rsi"], "atr": sig.reasons["atr"]})
        self.state.log_event("INFO", "signal", f"{symbol} {candle_time}: {sig.action}", symbol=symbol,
                             data=sig.reasons)

        tf_ms = self.exchange.timeframe_ms(self.config.timeframe)
        new_candles = df[df["timestamp"] > last_processed]
        for pos in self.executor.open_positions():
            if pos["symbol"] != symbol:
                continue
            self._update_trailing(pos, new_candles, tf_ms, sig.atr)

        price = self._last_prices[symbol]
        for pos in self.executor.open_positions():
            if pos["symbol"] != symbol:
                continue
            if (pos["side"] == "long" and sig.exit_long) or (pos["side"] == "short" and sig.exit_short):
                self._close(pos, price, "trend_flip")

        if sig.is_entry:
            self._try_entry(symbol, sig, price, settings)

        self.state.set_state(state_key, last_ts)

    def _update_trailing(self, pos: Dict[str, Any], candles, tf_ms: int, atr_value: float) -> None:
        opened_ms = _iso_to_ms(pos["opened_at"])
        relevant = candles[candles["timestamp"] + tf_ms > opened_ms]
        if relevant.empty:
            return
        highest = max(float(pos["highest_price"]), float(relevant["high"].max()))
        lowest = min(float(pos["lowest_price"]), float(relevant["low"].min()))
        pos = {**pos, "highest_price": highest, "lowest_price": lowest}
        new_stop = self.risk.trailing_stop_for(pos, atr_value)
        updates: Dict[str, Any] = {"highest_price": highest, "lowest_price": lowest}
        if new_stop != pos["stop_loss"]:
            updates["stop_loss"] = new_stop
            log.info("Trailing stop moved", extra={"symbol": pos["symbol"], "position_id": pos["id"],
                                                   "old_stop": pos["stop_loss"], "new_stop": new_stop})
            self.state.log_event("INFO", "trailing", f"Stop {pos['stop_loss']:.6g} -> {new_stop:.6g}",
                                 symbol=pos["symbol"], data={"position_id": pos["id"]})
        self.state.update_position(pos["id"], **updates)
        if "stop_loss" in updates:
            try:
                self.executor.on_stop_moved(self.state.get_position(pos["id"]))
            except ccxt.BaseError as exc:  # next loop's sync retries; the software stop is already updated
                log.warning("Could not move exchange stop", extra={"position_id": pos["id"],
                                                                   "error": type(exc).__name__})

    def _try_entry(self, symbol: str, sig, price: float, settings: Mapping[str, Any]) -> None:
        def skip(reason: str, level: str = "INFO") -> None:
            log.info("Entry skipped", extra={"symbol": symbol, "side": sig.action, "reason": reason})
            self.state.log_event(level, "decision", f"{sig.action} signal skipped: {reason}", symbol=symbol)

        if not settings.get("trading_enabled", True):
            return skip("trading disabled (kill switch)")
        if settings.get("safety_halt_active", False):
            halt = self.state.get_state(f"safety_halt:{self.executor.mode}") or {}
            return skip(f"safety halt ({halt.get('reason') or 'set by user'})")
        open_positions = self.executor.open_positions()
        if any(p["symbol"] == symbol for p in open_positions):
            return skip("position already open for symbol")

        equity = self.executor.get_equity(self._last_prices)
        day_start = self.state.get_or_create_day_start_equity(self.executor.mode, equity)
        cash = self.executor.get_available_cash(self._last_prices)
        plan = self.risk.plan_trade(symbol, sig.action, price, sig.atr, equity, open_positions,
                                    day_start_equity=day_start, available_cash=cash)
        if not plan.allowed:
            if plan.reason.startswith("daily loss limit"):
                if self.state.get_state("daily_limit_logged") != utc_today():
                    self.state.set_state("daily_limit_logged", utc_today())
                    self.state.log_event("WARNING", "risk", f"New entries paused until UTC midnight: {plan.reason}")
                    log.warning("Daily loss limit reached", extra={"reason": plan.reason})
            return skip(plan.reason)

        log.info("Entry approved", extra={"symbol": symbol, "side": plan.side, "qty": plan.quantity,
                                          "price": price, "stop": plan.stop_loss, "take_profit": plan.take_profit,
                                          "risk_amount": round(plan.risk_amount, 4), "equity": round(equity, 2)})
        try:
            self.executor.open_position(symbol, plan.side, plan.quantity, price, plan.stop_loss, plan.take_profit,
                                        sig.atr, reason="signal")
        except ccxt.InsufficientFunds:
            skip("insufficient funds", "WARNING")
        except ccxt.InvalidOrder as exc:
            skip(f"invalid order: {exc}", "WARNING")
        except (ccxt.AuthenticationError, ccxt.PermissionDenied):
            raise
        except ccxt.NetworkError as exc:
            # The order may have reached the exchange even though no answer came back.
            # Do not place it again for this candle: a retry could open a duplicate.
            log.error("Entry order status unknown; not retrying this signal",
                      extra={"symbol": symbol, "error": type(exc).__name__})
            skip(f"order status unknown after {type(exc).__name__}; check the exchange", "ERROR")
        except ccxt.BaseError as exc:
            skip(f"order rejected: {type(exc).__name__}: {exc}", "WARNING")

    def _close(self, pos: Dict[str, Any], price: float, reason: str) -> None:
        try:
            self.executor.close_position(pos, price, reason)
        except ccxt.BaseError as exc:
            log.error("Close failed; will retry next loop", extra={"position_id": pos["id"],
                                                                   "error": type(exc).__name__})
            self.state.log_event("ERROR", "error", f"Close failed for #{pos['id']}: {type(exc).__name__}",
                                 symbol=pos["symbol"])

    # --------------------------------------------------------- dashboard cmds
    def _process_commands(self) -> None:
        try:
            commands = self.state.get_pending_commands()
        except Exception:  # pragma: no cover
            log.exception("Could not read commands")
            return
        for cmd in commands:
            try:
                note = self._run_command(cmd["command"], cmd["payload"])
                self.state.complete_command(cmd["id"], "done", note)
            except Exception as exc:
                log.exception("Command failed", extra={"command": cmd["command"]})
                self.state.complete_command(cmd["id"], "failed", f"{type(exc).__name__}: {exc}")

    def _run_command(self, command: str, payload: Mapping[str, Any]) -> str:
        if command == "close_position":
            pos = self.state.get_position(int(payload["position_id"]))
            if not pos or pos["status"] != "open" or pos["mode"] != self.executor.mode:
                return "position not open in this mode"
            price = self.exchange.fetch_last_price(pos["symbol"])
            self._last_prices[pos["symbol"]] = price
            self.executor.close_position(pos, price, "manual")
            return f"closed at {price}"
        if command == "close_all":
            closed, failed = 0, []
            for pos in self.executor.open_positions():
                try:  # one failing symbol must not leave the others open
                    price = self.exchange.fetch_last_price(pos["symbol"])
                    self._last_prices[pos["symbol"]] = price
                    self.executor.close_position(pos, price, "manual")
                    closed += 1
                except ccxt.BaseError as exc:
                    log.error("Close failed", extra={"position_id": pos["id"], "error": type(exc).__name__})
                    failed.append(f"#{pos['id']} {pos['symbol']}: {type(exc).__name__}")
            if failed:
                raise RuntimeError(f"closed {closed}, failed {len(failed)}: {'; '.join(failed)}")
            return f"closed {closed} position(s)"
        raise ValueError(f"unknown command {command!r}")

    def _starting_equity_hint(self) -> float:
        return float(getattr(self.executor, "starting_balance", 0.0) or 0.0)
