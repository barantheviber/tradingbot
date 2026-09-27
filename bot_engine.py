"""
Main trading loop.

Design points called out in the spec:
  * Signals are generated ONLY on closed candles - the last candle ccxt
    returns for the *current* timeframe is still forming, so it is always
    dropped before strategy.generate_signal ever sees the data. This is
    the single place look-ahead bias is prevented.
  * Graceful shutdown on SIGINT/SIGTERM: instead of one long time.sleep(),
    the loop sleeps in 1-second increments and checks a shutdown flag
    between each one, so a signal received mid-wait still exits promptly.
  * On startup, open positions are restored from state_manager so a crash
    and restart doesn't lose track of what's on the books.
"""
from __future__ import annotations

import logging
import signal
import time
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from config import Config
from exchange_client import ExchangeClient
from execution.base import BaseExecutionClient
from execution.paper import PaperExecutionClient
from risk_manager import (
    DailyPnLTracker,
    RiskLimitExceeded,
    RiskParams,
    check_exposure_limit,
    check_max_positions,
    compute_position_size,
    update_trailing_stop,
)
from state_manager import Position, StateManager, TradeRecord
from strategy import Side, Signal, StrategyParams, generate_signal

logger = logging.getLogger(__name__)


SETTINGS_KEYS = (
    "risk_per_trade_pct",
    "risk_reward_ratio",
    "atr_period",
    "atr_sl_multiplier",
    "trailing_atr_multiplier",
    "max_daily_drawdown_pct",
    "max_concurrent_positions",
    "max_exposure_per_symbol_pct",
    "ema_trend_period",
    "rsi_period",
    "rsi_lower",
    "rsi_upper",
    "macd_fast",
    "macd_slow",
    "macd_signal",
    "volume_ma_period",
    "volume_confirmation_multiplier",
    "donchian_period",
)


def setup_logging(cfg: Config) -> None:
    log_path = cfg.paths.log_dir / "trading_bot.log"
    level = getattr(logging, cfg.log_level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )

    file_handler = logging.FileHandler(log_path)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    root.addHandler(console_handler)


def ohlcv_to_dataframe(raw: list) -> pd.DataFrame:
    df = pd.DataFrame(
        raw, columns=["timestamp", "open", "high", "low", "close", "volume"]
    )
    return df


def drop_unclosed_candle(df: pd.DataFrame, timeframe_ms: int) -> pd.DataFrame:
    """
    ccxt's fetch_ohlcv includes the currently-forming candle as its last
    row. We only ever want to act on closed candles, so drop the last row
    unless it's clearly already closed (its close time is in the past).
    """
    if df.empty:
        return df
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    last_open_ms = int(df.iloc[-1]["timestamp"])
    candle_close_ms = last_open_ms + timeframe_ms
    if candle_close_ms > now_ms:
        return df.iloc[:-1].reset_index(drop=True)
    return df


TIMEFRAME_MS = {
    "1m": 60_000,
    "3m": 3 * 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1h": 60 * 60_000,
    "2h": 2 * 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "6h": 6 * 60 * 60_000,
    "12h": 12 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}


class BotEngine:
    def __init__(
        self,
        cfg: Config,
        exchange_client: ExchangeClient,
        execution_client: BaseExecutionClient,
        state: StateManager,
    ):
        self.cfg = cfg
        self.exchange_client = exchange_client
        self.execution_client = execution_client
        self.state = state
        self._shutdown_requested = False
        self._last_seen_candle_ts: Optional[int] = None

        self.state.seed_default_settings(
            {
                "risk_per_trade_pct": cfg.risk_defaults.risk_per_trade_pct,
                "risk_reward_ratio": cfg.risk_defaults.risk_reward_ratio,
                "atr_period": cfg.risk_defaults.atr_period,
                "atr_sl_multiplier": cfg.risk_defaults.atr_sl_multiplier,
                "trailing_atr_multiplier": cfg.risk_defaults.trailing_atr_multiplier,
                "max_daily_drawdown_pct": cfg.risk_defaults.max_daily_drawdown_pct,
                "max_concurrent_positions": cfg.risk_defaults.max_concurrent_positions,
                "max_exposure_per_symbol_pct": cfg.risk_defaults.max_exposure_per_symbol_pct,
                "ema_trend_period": cfg.risk_defaults.ema_trend_period,
                "rsi_period": cfg.risk_defaults.rsi_period,
                "rsi_lower": cfg.risk_defaults.rsi_lower,
                "rsi_upper": cfg.risk_defaults.rsi_upper,
                "macd_fast": cfg.risk_defaults.macd_fast,
                "macd_slow": cfg.risk_defaults.macd_slow,
                "macd_signal": cfg.risk_defaults.macd_signal,
                "volume_ma_period": cfg.risk_defaults.volume_ma_period,
                "volume_confirmation_multiplier": cfg.risk_defaults.volume_confirmation_multiplier,
                "donchian_period": cfg.risk_defaults.donchian_period,
            }
        )

        starting_equity = self._current_equity()
        self.daily_pnl = DailyPnLTracker(starting_equity=starting_equity)

        self._restore_open_positions()
        self._install_signal_handlers()

    # ------------------------------------------------------------------
    # Setup / lifecycle
    # ------------------------------------------------------------------
    def _install_signal_handlers(self) -> None:
        signal.signal(signal.SIGINT, self._handle_shutdown_signal)
        signal.signal(signal.SIGTERM, self._handle_shutdown_signal)

    def _handle_shutdown_signal(self, signum, frame) -> None:
        logger.info("Received signal %s, shutting down gracefully...", signum)
        self._shutdown_requested = True

    def _restore_open_positions(self) -> None:
        open_positions = self.state.get_open_positions(symbol=self.cfg.trading.symbol)
        if open_positions:
            logger.info(
                "Restored %d open position(s) for %s from state_manager",
                len(open_positions),
                self.cfg.trading.symbol,
            )
            for pos in open_positions:
                self.state.log_event(
                    "INFO",
                    f"Restored open position id={pos.id} side={pos.side} "
                    f"qty={pos.quantity} entry={pos.entry_price}",
                )

    def _current_equity(self) -> float:
        if isinstance(self.execution_client, PaperExecutionClient):
            return self.execution_client.get_account_equity()
        return self.execution_client.get_account_equity()

    def _load_strategy_params(self) -> StrategyParams:
        settings = self.state.get_all_settings()
        return StrategyParams(
            ema_trend_period=int(settings.get("ema_trend_period", self.cfg.risk_defaults.ema_trend_period)),
            rsi_period=int(settings.get("rsi_period", self.cfg.risk_defaults.rsi_period)),
            rsi_lower=float(settings.get("rsi_lower", self.cfg.risk_defaults.rsi_lower)),
            rsi_upper=float(settings.get("rsi_upper", self.cfg.risk_defaults.rsi_upper)),
            macd_fast=int(settings.get("macd_fast", self.cfg.risk_defaults.macd_fast)),
            macd_slow=int(settings.get("macd_slow", self.cfg.risk_defaults.macd_slow)),
            macd_signal=int(settings.get("macd_signal", self.cfg.risk_defaults.macd_signal)),
            volume_ma_period=int(settings.get("volume_ma_period", self.cfg.risk_defaults.volume_ma_period)),
            volume_confirmation_multiplier=float(
                settings.get("volume_confirmation_multiplier", self.cfg.risk_defaults.volume_confirmation_multiplier)
            ),
            donchian_period=int(settings.get("donchian_period", self.cfg.risk_defaults.donchian_period)),
            atr_period=int(settings.get("atr_period", self.cfg.risk_defaults.atr_period)),
        )

    def _load_risk_params(self) -> RiskParams:
        settings = self.state.get_all_settings()
        return RiskParams(
            risk_per_trade_pct=float(settings.get("risk_per_trade_pct", self.cfg.risk_defaults.risk_per_trade_pct)),
            risk_reward_ratio=float(settings.get("risk_reward_ratio", self.cfg.risk_defaults.risk_reward_ratio)),
            atr_sl_multiplier=float(settings.get("atr_sl_multiplier", self.cfg.risk_defaults.atr_sl_multiplier)),
            trailing_atr_multiplier=float(
                settings.get("trailing_atr_multiplier", self.cfg.risk_defaults.trailing_atr_multiplier)
            ),
            max_daily_drawdown_pct=float(
                settings.get("max_daily_drawdown_pct", self.cfg.risk_defaults.max_daily_drawdown_pct)
            ),
            max_concurrent_positions=int(
                settings.get("max_concurrent_positions", self.cfg.risk_defaults.max_concurrent_positions)
            ),
            max_exposure_per_symbol_pct=float(
                settings.get("max_exposure_per_symbol_pct", self.cfg.risk_defaults.max_exposure_per_symbol_pct)
            ),
        )

    # ------------------------------------------------------------------
    # Core loop
    # ------------------------------------------------------------------
    def run_forever(self) -> None:
        logger.info(
            "Starting bot_engine: symbol=%s timeframe=%s paper_trading=%s",
            self.cfg.trading.symbol,
            self.cfg.trading.timeframe,
            self.cfg.paper_trading,
        )
        while not self._shutdown_requested:
            try:
                self._run_cycle()
            except Exception:
                logger.exception("Unhandled error in trading cycle; continuing loop")
                self.state.log_event("ERROR", "Unhandled exception in trading cycle")
            self._sleep_interruptible(self.cfg.trading.poll_interval_seconds)
        logger.info("Shutdown complete.")

    def _sleep_interruptible(self, seconds: int) -> None:
        for _ in range(max(1, seconds)):
            if self._shutdown_requested:
                return
            time.sleep(1)

    def _run_cycle(self) -> None:
        timeframe = self.cfg.trading.timeframe
        symbol = self.cfg.trading.symbol
        timeframe_ms = TIMEFRAME_MS.get(timeframe)
        if timeframe_ms is None:
            raise ValueError(f"Unsupported timeframe {timeframe!r}")

        raw = self.exchange_client.fetch_ohlcv(
            symbol, timeframe, limit=self.cfg.trading.candle_lookback
        )
        df = ohlcv_to_dataframe(raw)
        df = drop_unclosed_candle(df, timeframe_ms)
        if df.empty:
            logger.debug("No closed candle data yet for %s %s", symbol, timeframe)
            return

        latest_candle_ts = int(df.iloc[-1]["timestamp"])
        is_new_candle = latest_candle_ts != self._last_seen_candle_ts

        # Always manage trailing stops / TP-SL checks on every cycle using
        # the latest price, regardless of whether a new candle closed.
        self._manage_open_positions(symbol, df)

        if not is_new_candle:
            return
        self._last_seen_candle_ts = latest_candle_ts

        strategy_params = self._load_strategy_params()
        risk_params = self._load_risk_params()

        signal = generate_signal(df, strategy_params)
        self.state.log_event(
            "INFO", f"Signal @ {latest_candle_ts}: side={signal.side} reasons={signal.reasons}"
        )
        logger.info("Signal: side=%s reasons=%s", signal.side, signal.reasons)

        if self.daily_pnl.trading_halted(risk_params):
            msg = (
                f"Daily drawdown limit reached ({self.daily_pnl.drawdown_pct():.2f}% >= "
                f"{risk_params.max_daily_drawdown_pct:.2f}%); skipping new entries until UTC midnight."
            )
            logger.warning(msg)
            self.state.log_event("WARNING", msg)
            return

        if not signal.is_actionable:
            return

        self._maybe_enter_position(symbol, signal, risk_params)

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------
    def _manage_open_positions(self, symbol: str, df: pd.DataFrame) -> None:
        open_positions = self.state.get_open_positions(symbol=symbol)
        if not open_positions:
            return

        current_price = float(df.iloc[-1]["close"])
        risk_params = self._load_risk_params()
        strategy_params = self._load_strategy_params()
        from strategy import atr as atr_fn  # local import to avoid cycle at module load

        atr_series = atr_fn(df, strategy_params.atr_period)
        current_atr = float(atr_series.iloc[-1]) if not atr_series.empty and not pd.isna(atr_series.iloc[-1]) else 0.0

        for pos in open_positions:
            side = Side(pos.side)
            hit_stop = (side == Side.LONG and current_price <= pos.stop_loss) or (
                side == Side.SHORT and current_price >= pos.stop_loss
            )
            hit_target = (side == Side.LONG and current_price >= pos.take_profit) or (
                side == Side.SHORT and current_price <= pos.take_profit
            )

            if hit_stop or hit_target:
                reason = "stop_loss" if hit_stop else "take_profit"
                self._close_position(pos, current_price, reason)
                continue

            if current_atr > 0:
                new_stop = update_trailing_stop(
                    side, pos.stop_loss, current_price, current_atr, risk_params
                )
                if new_stop != pos.stop_loss:
                    self.state.update_position_stop(pos.id, new_stop)
                    logger.info(
                        "Trailing stop updated for position %s: %.8f -> %.8f",
                        pos.id,
                        pos.stop_loss,
                        new_stop,
                    )

    def _close_position(self, pos: Position, price: float, reason: str) -> None:
        side = Side(pos.side)
        result = self.execution_client.close_position(pos.symbol, side, pos.quantity, price)
        if not result.success:
            logger.error("Failed to close position %s: %s", pos.id, result.error)
            self.state.log_event("ERROR", f"Failed to close position {pos.id}: {result.error}")
            return

        fill_price = result.filled_price or price
        if side == Side.LONG:
            pnl = (fill_price - pos.entry_price) * pos.quantity
        else:
            pnl = (pos.entry_price - fill_price) * pos.quantity

        self.state.close_position(pos.id, fill_price, pnl)
        self.state.record_trade(
            TradeRecord(
                id=None,
                symbol=pos.symbol,
                side=pos.side,
                entry_price=pos.entry_price,
                exit_price=fill_price,
                quantity=pos.quantity,
                pnl=pnl,
                opened_at=pos.opened_at,
                closed_at=datetime.now(timezone.utc).isoformat(),
                reason=reason,
            )
        )
        self.daily_pnl.record_realized_pnl(pnl)
        if isinstance(self.execution_client, PaperExecutionClient):
            self.execution_client.apply_realized_pnl(pnl)

        msg = f"Closed position {pos.id} ({reason}) @ {fill_price:.8f} pnl={pnl:.4f}"
        logger.info(msg)
        self.state.log_event("INFO", msg)

    def _maybe_enter_position(self, symbol: str, signal: Signal, risk_params: RiskParams) -> None:
        open_positions = self.state.get_open_positions(symbol=symbol)
        try:
            check_max_positions(len(self.state.get_open_positions()), risk_params)
        except RiskLimitExceeded as exc:
            logger.info("Skipping entry: %s", exc)
            return

        equity = self._current_equity()
        entry_price = signal.indicators.close
        atr_value = signal.indicators.atr

        try:
            sizing = compute_position_size(signal.side, entry_price, atr_value, equity, risk_params)
        except ValueError as exc:
            logger.warning("Cannot size position: %s", exc)
            return

        existing_notional = sum(p.entry_price * p.quantity for p in open_positions)
        trade_notional = entry_price * sizing.quantity
        try:
            check_exposure_limit(existing_notional, trade_notional, equity, risk_params)
        except RiskLimitExceeded as exc:
            logger.info("Skipping entry: %s", exc)
            return

        result = self.execution_client.open_position(symbol, signal.side, sizing.quantity, entry_price)
        if not result.success:
            logger.error("Failed to open position: %s", result.error)
            self.state.log_event("ERROR", f"Failed to open position: {result.error}")
            return

        fill_price = result.filled_price or entry_price
        position = Position(
            id=None,
            symbol=symbol,
            side=signal.side.value,
            entry_price=fill_price,
            quantity=sizing.quantity,
            stop_loss=sizing.stop_loss,
            take_profit=sizing.take_profit,
            opened_at=datetime.now(timezone.utc).isoformat(),
            exchange_order_id=result.order_id,
            meta={"reasons": signal.reasons},
        )
        position_id = self.state.open_position(position)
        msg = (
            f"Opened position {position_id}: {signal.side.value} {sizing.quantity:.8f} {symbol} "
            f"@ {fill_price:.8f} SL={sizing.stop_loss:.8f} TP={sizing.take_profit:.8f}"
        )
        logger.info(msg)
        self.state.log_event("INFO", msg)
