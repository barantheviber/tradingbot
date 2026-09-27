"""
Streamlit + Plotly dashboard.

Run with:
    streamlit run dashboard/app.py

Provides:
  * Live candlestick chart for the configured symbol/timeframe.
  * Open positions table with a manual "Close" button per row.
  * PnL summary (from execution.base.performance_summary).
  * A scrolling decision/trade log terminal (from state_manager.event_log).
  * A live editor for state_manager's strategy/risk settings table.

This file intentionally does NOT import bot_engine.BotEngine: the engine
installs SIGINT/SIGTERM handlers meant for the long-running trading
process, which is a different OS process from the dashboard. The manual
close path below re-implements the same close+record logic against
state_manager/execution client directly.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running via `streamlit run dashboard/app.py` from any cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import config
from exchange_client import ExchangeClient
from execution.live import LiveExecutionClient
from execution.paper import PaperExecutionClient
from state_manager import StateManager, TradeRecord
from strategy import Side, StrategyParams, compute_indicators

st.set_page_config(page_title="Trading Bot Dashboard", layout="wide")


@st.cache_resource
def get_state() -> StateManager:
    return StateManager(config.paths.db_path)


@st.cache_resource
def get_exchange_client() -> ExchangeClient:
    return ExchangeClient(config)


@st.cache_resource
def get_execution_client():
    state = get_state()
    exchange_client = get_exchange_client()
    if config.paper_trading:
        starting_balance = state.get_setting("paper_balance", config.account.paper_starting_balance)
        return PaperExecutionClient(starting_balance=starting_balance)
    return LiveExecutionClient(exchange_client, quote_currency=config.account.quote_currency)


def manual_close_position(position, price: float) -> None:
    state = get_state()
    execution_client = get_execution_client()
    side = Side(position.side)
    result = execution_client.close_position(position.symbol, side, position.quantity, price)
    if not result.success:
        st.error(f"Close failed: {result.error}")
        return

    fill_price = result.filled_price or price
    if side == Side.LONG:
        pnl = (fill_price - position.entry_price) * position.quantity
    else:
        pnl = (position.entry_price - fill_price) * position.quantity

    state.close_position(position.id, fill_price, pnl)
    state.record_trade(
        TradeRecord(
            id=None,
            symbol=position.symbol,
            side=position.side,
            entry_price=position.entry_price,
            exit_price=fill_price,
            quantity=position.quantity,
            pnl=pnl,
            opened_at=position.opened_at,
            closed_at=datetime.now(timezone.utc).isoformat(),
            reason="manual_close",
        )
    )
    if isinstance(execution_client, PaperExecutionClient):
        execution_client.apply_realized_pnl(pnl)
        state.set_setting("paper_balance", execution_client.get_account_equity())
    state.log_event("INFO", f"Manually closed position {position.id} @ {fill_price:.8f} pnl={pnl:.4f}")
    st.success(f"Closed position {position.id} @ {fill_price:.4f} (pnl={pnl:.4f})")


def render_chart(state: StateManager, exchange_client: ExchangeClient) -> None:
    st.subheader(f"{config.trading.symbol} - {config.trading.timeframe}")
    try:
        raw = exchange_client.fetch_ohlcv(
            config.trading.symbol, config.trading.timeframe, limit=config.trading.candle_lookback
        )
    except Exception as exc:
        st.warning(f"Could not fetch live candles: {exc}")
        return

    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["dt"] = pd.to_datetime(df["timestamp"], unit="ms")

    settings = state.get_all_settings()
    params = StrategyParams(
        ema_trend_period=int(settings.get("ema_trend_period", config.risk_defaults.ema_trend_period)),
        rsi_period=int(settings.get("rsi_period", config.risk_defaults.rsi_period)),
        rsi_lower=float(settings.get("rsi_lower", config.risk_defaults.rsi_lower)),
        rsi_upper=float(settings.get("rsi_upper", config.risk_defaults.rsi_upper)),
        macd_fast=int(settings.get("macd_fast", config.risk_defaults.macd_fast)),
        macd_slow=int(settings.get("macd_slow", config.risk_defaults.macd_slow)),
        macd_signal=int(settings.get("macd_signal", config.risk_defaults.macd_signal)),
        volume_ma_period=int(settings.get("volume_ma_period", config.risk_defaults.volume_ma_period)),
        volume_confirmation_multiplier=float(
            settings.get("volume_confirmation_multiplier", config.risk_defaults.volume_confirmation_multiplier)
        ),
        donchian_period=int(settings.get("donchian_period", config.risk_defaults.donchian_period)),
        atr_period=int(settings.get("atr_period", config.risk_defaults.atr_period)),
    )
    enriched = compute_indicators(df, params)

    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=enriched["dt"],
            open=enriched["open"],
            high=enriched["high"],
            low=enriched["low"],
            close=enriched["close"],
            name="Price",
        )
    )
    fig.add_trace(
        go.Scatter(x=enriched["dt"], y=enriched["ema_trend"], line=dict(color="orange", width=1), name="EMA trend")
    )
    fig.add_trace(
        go.Scatter(x=enriched["dt"], y=enriched["donchian_high"], line=dict(color="grey", width=1, dash="dot"), name="Donchian high")
    )
    fig.add_trace(
        go.Scatter(x=enriched["dt"], y=enriched["donchian_low"], line=dict(color="grey", width=1, dash="dot"), name="Donchian low")
    )
    fig.update_layout(height=500, xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=30, b=10))
    st.plotly_chart(fig, use_container_width=True)


def render_positions(state: StateManager) -> None:
    st.subheader("Open Positions")
    positions = state.get_open_positions()
    if not positions:
        st.info("No open positions.")
        return

    for pos in positions:
        cols = st.columns([2, 1, 1, 1, 1, 1, 1])
        cols[0].write(f"#{pos.id} {pos.symbol}")
        cols[1].write(pos.side)
        cols[2].write(f"qty {pos.quantity:.6f}")
        cols[3].write(f"entry {pos.entry_price:.4f}")
        cols[4].write(f"SL {pos.stop_loss:.4f}")
        cols[5].write(f"TP {pos.take_profit:.4f}")
        if cols[6].button("Close", key=f"close_{pos.id}"):
            try:
                ticker = get_exchange_client().fetch_ticker(pos.symbol)
                price = float(ticker["last"])
            except Exception:
                price = pos.entry_price
            manual_close_position(pos, price)
            st.rerun()


def render_pnl_summary(state: StateManager) -> None:
    st.subheader("PnL Summary")
    execution_client = get_execution_client()
    trades = state.get_trade_history(limit=500)
    summary = execution_client.performance_summary(trades)
    cols = st.columns(6)
    cols[0].metric("Total trades", summary["total_trades"])
    cols[1].metric("Win rate", f"{summary['win_rate']:.1f}%")
    cols[2].metric("Total PnL", f"{summary['total_pnl']:.2f}")
    cols[3].metric("Avg PnL", f"{summary['avg_pnl']:.2f}")
    cols[4].metric("Best trade", f"{summary['best_trade']:.2f}")
    cols[5].metric("Worst trade", f"{summary['worst_trade']:.2f}")
    st.metric("Account equity", f"{execution_client.get_account_equity():.2f} {config.account.quote_currency}")


def render_log_terminal(state: StateManager) -> None:
    st.subheader("Decision / Trade Log")
    events = state.get_recent_events(limit=200)
    lines = [f"{e['ts']} [{e['level']}] {e['message']}" for e in events]
    st.text_area("log", value="\n".join(lines), height=250, label_visibility="collapsed")


def render_settings_editor(state: StateManager) -> None:
    st.subheader("Live Strategy / Risk Parameters")
    settings = state.get_all_settings()
    if not settings:
        st.info("No settings seeded yet - start the bot once to populate defaults.")
        return

    with st.form("settings_form"):
        new_values = {}
        cols = st.columns(2)
        keys = sorted(settings.keys())
        for i, key in enumerate(keys):
            col = cols[i % 2]
            current = settings[key]
            if isinstance(current, bool):
                new_values[key] = col.checkbox(key, value=current)
            elif isinstance(current, int):
                new_values[key] = col.number_input(key, value=current, step=1)
            elif isinstance(current, float):
                new_values[key] = col.number_input(key, value=current, format="%.4f")
            else:
                new_values[key] = col.text_input(key, value=str(current))
        submitted = st.form_submit_button("Save")
        if submitted:
            for key, value in new_values.items():
                state.set_setting(key, value)
            st.success("Settings updated. The running bot picks these up on its next cycle.")


def main() -> None:
    st.title("Trading Bot Dashboard")
    mode = "PAPER" if config.paper_trading else "LIVE"
    st.caption(f"Mode: **{mode}** | Exchange: {config.exchange.exchange_id} | Symbol: {config.trading.symbol}")

    state = get_state()
    exchange_client = get_exchange_client()

    render_chart(state, exchange_client)
    render_pnl_summary(state)
    render_positions(state)
    render_settings_editor(state)
    render_log_terminal(state)

    if st.button("Refresh"):
        st.rerun()


if __name__ == "__main__":
    main()
